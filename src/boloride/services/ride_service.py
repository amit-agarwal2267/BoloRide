import logging
import re
from datetime import datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.db.models.ride import Ride
from boloride.domain.enums import RideStatus
from boloride.domain.models.cancellation import (
    CancellationResult,
    CancellationSetResult,
    CancellationResultStatus,
    RideReferenceResolution,
    RideReferenceResolutionStatus,
    RideStatusDetails,
)
from boloride.domain.models.ride import CANCELLABLE_RIDE_STATUSES
from boloride.repositories.ride_repository import RideRepository
from boloride.services.offer_service import OfferService

logger = logging.getLogger(__name__)


class DriverAssignmentReleasePort(Protocol):
    """Stage 8 boundary: implementations must make repeated releases safe."""

    async def release_assignment_idempotently(self, ride_id: UUID) -> None: ...


class NoOpDriverAssignmentRelease:
    async def release_assignment_idempotently(self, ride_id: UUID) -> None:
        return None


class RideService:
    """Customer-owned ride status and deterministic lifecycle operations."""

    def __init__(
        self,
        session: AsyncSession,
        rides: RideRepository,
        offers: OfferService | None = None,
        driver_assignments: DriverAssignmentReleasePort | None = None,
    ) -> None:
        self._session = session
        self._rides = rides
        self._offers = offers
        self._driver_assignments = (
            driver_assignments or NoOpDriverAssignmentRelease()
        )

    async def get_customer_ride(
        self, customer_id: UUID, ride_id: UUID
    ) -> Ride | None:
        return await self._rides.get_for_customer(customer_id, ride_id)

    async def get_customer_ride_status(
        self, customer_id: UUID, ride_id: UUID, context: RideContext
    ) -> RideStatusDetails | None:
        if not self._identity_matches(customer_id, context):
            logger.info(
                "ride_status_lookup_rejected",
                extra={"event": "ride_status_lookup_rejected", "reason": "identity"},
            )
            return None
        details = await self._rides.get_status_for_customer(customer_id, ride_id)
        logger.info(
            "ride_status_lookup",
            extra={
                "event": "ride_status_lookup",
                "session_id": context.session_id,
                "found": details is not None,
                "ride_status": details.status.value if details else None,
            },
        )
        return details

    async def list_customer_rides(
        self, customer_id: UUID, *, limit: int = 5
    ) -> list[Ride]:
        return await self._rides.list_for_customer(customer_id, limit=limit)

    async def resolve_customer_ride_reference(
        self,
        customer_id: UUID,
        context: RideContext,
        *,
        reference: str | None = None,
        candidate_number: int | None = None,
        cancellable_only: bool = False,
        all_requested: bool = False,
        limit: int = 5,
    ) -> RideReferenceResolution:
        """Resolve natural customer language to one owned internal ride ID."""
        if not self._identity_matches(customer_id, context):
            return RideReferenceResolution(RideReferenceResolutionStatus.NOT_FOUND)
        purpose = "cancellation" if cancellable_only else "status"
        logger.info(
            "ride_reference_resolution_started",
            extra={
                "event": "ride_reference_resolution_started",
                "session_id": context.session_id,
                "purpose": purpose,
            },
        )
        if candidate_number is not None:
            if (
                context.ride_reference_purpose != purpose
                or not 1 <= candidate_number <= len(context.ride_reference_candidates)
            ):
                return RideReferenceResolution(RideReferenceResolutionStatus.NOT_FOUND)
            ride_id = context.ride_reference_candidates[candidate_number - 1]
            details = await self._rides.get_status_for_customer(customer_id, ride_id)
            context.clear_ride_reference_candidates()
            if details is None or (
                cancellable_only and details.status not in CANCELLABLE_RIDE_STATUSES
            ):
                return RideReferenceResolution(RideReferenceResolutionStatus.NOT_FOUND)
            return self._resolved_reference(context, details, purpose)

        rides = await self._rides.list_status_for_customer(customer_id, limit=limit)
        if cancellable_only:
            rides = [ride for ride in rides if ride.status in CANCELLABLE_RIDE_STATUSES]
        if not rides:
            context.clear_ride_reference_candidates()
            logger.info(
                "ride_reference_not_found",
                extra={
                    "event": "ride_reference_not_found",
                    "session_id": context.session_id,
                    "purpose": purpose,
                },
            )
            return RideReferenceResolution(RideReferenceResolutionStatus.NOT_FOUND)

        if all_requested:
            context.set_ride_reference_candidates(
                tuple(ride.ride_id for ride in rides), purpose
            )
            logger.info(
                "cancellation_set_resolved",
                extra={
                    "event": "cancellation_set_resolved",
                    "session_id": context.session_id,
                    "candidate_count": len(rides),
                },
            )
            return RideReferenceResolution(
                RideReferenceResolutionStatus.RESOLVED_SET,
                candidates=tuple(rides),
            )

        normalized_reference = " ".join((reference or "").casefold().split())
        if any(word in normalized_reference for word in ("latest", "recent", "haal hi")):
            return self._resolved_reference(context, rides[0], purpose)
        meaningful = _reference_tokens(normalized_reference)
        if not meaningful and not cancellable_only:
            active = [
                ride
                for ride in rides
                if ride.status
                in {RideStatus.BOOKED, RideStatus.ASSIGNED, RideStatus.ON_TRIP}
            ]
            if len(active) == 1:
                return self._resolved_reference(context, active[0], purpose)
        matches = rides
        if meaningful:
            scored = [
                (len(meaningful.intersection(_ride_reference_tokens(ride))), ride)
                for ride in rides
            ]
            best_score = max(score for score, _ in scored)
            matches = [ride for score, ride in scored if score == best_score and score > 0]
        if len(matches) == 1:
            return self._resolved_reference(context, matches[0], purpose)
        if not matches:
            context.clear_ride_reference_candidates()
            logger.info(
                "ride_reference_not_found",
                extra={
                    "event": "ride_reference_not_found",
                    "session_id": context.session_id,
                    "purpose": purpose,
                },
            )
            return RideReferenceResolution(RideReferenceResolutionStatus.NOT_FOUND)
        context.set_ride_reference_candidates(
            tuple(ride.ride_id for ride in matches), purpose
        )
        logger.info(
            "ride_reference_ambiguous",
            extra={
                "event": "ride_reference_ambiguous",
                "session_id": context.session_id,
                "purpose": purpose,
                "candidate_count": len(matches),
            },
        )
        return RideReferenceResolution(
            RideReferenceResolutionStatus.AMBIGUOUS, candidates=tuple(matches)
        )

    @staticmethod
    def _resolved_reference(
        context: RideContext, details: RideStatusDetails, purpose: str
    ) -> RideReferenceResolution:
        context.clear_ride_reference_candidates()
        logger.info(
            "ride_reference_resolution_completed",
            extra={
                "event": "ride_reference_resolution_completed",
                "session_id": context.session_id,
                "purpose": purpose,
                "ride_status": details.status.value,
            },
        )
        return RideReferenceResolution(
            RideReferenceResolutionStatus.RESOLVED, ride=details
        )

    async def cancel_customer_ride(
        self, customer_id: UUID, ride_id: UUID, context: RideContext
    ) -> CancellationResult:
        logger.info(
            "ride_cancellation_requested",
            extra={"event": "ride_cancellation_requested", "session_id": context.session_id},
        )
        if not self._identity_matches(customer_id, context):
            context.clear_cancellation()
            await self._session.rollback()
            return CancellationResult(CancellationResultStatus.NOT_FOUND)

        ride = await self._rides.get_for_customer(
            customer_id, ride_id, for_update=True
        )
        if ride is None:
            context.clear_cancellation()
            await self._session.rollback()
            return CancellationResult(CancellationResultStatus.NOT_FOUND)

        if ride.status is RideStatus.CANCELLED:
            await self._session.rollback()
            context.clear_cancellation()
            details = await self._rides.get_status_for_customer(customer_id, ride_id)
            logger.info(
                "ride_cancellation_idempotent",
                extra={"event": "ride_cancellation_idempotent", "session_id": context.session_id},
            )
            return CancellationResult(
                CancellationResultStatus.IDEMPOTENT_SUCCESS, details
            )

        if ride.status not in CANCELLABLE_RIDE_STATUSES:
            current_status = ride.status
            await self._session.rollback()
            context.clear_cancellation()
            details = await self._rides.get_status_for_customer(customer_id, ride_id)
            logger.info(
                "ride_cancellation_invalid_lifecycle",
                extra={
                    "event": "ride_cancellation_invalid_lifecycle",
                    "session_id": context.session_id,
                    "ride_status": current_status.value,
                },
            )
            return CancellationResult(CancellationResultStatus.NOT_CANCELLABLE, details)

        if not context.cancellation_is_confirmed_for(ride_id):
            await self._session.rollback()
            logger.info(
                "ride_cancellation_confirmation_required",
                extra={
                    "event": "ride_cancellation_confirmation_required",
                    "session_id": context.session_id,
                },
            )
            return CancellationResult(CancellationResultStatus.CONFIRMATION_REQUIRED)

        previous_status = ride.status
        cancelled = await self._rides.cancel_for_customer(
            customer_id, ride_id, expected_status=previous_status
        )
        if cancelled is None:
            await self._session.rollback()
            context.clear_cancellation()
            details = await self._rides.get_status_for_customer(customer_id, ride_id)
            logger.info(
                "ride_cancellation_transition_not_applied",
                extra={
                    "event": "ride_cancellation_transition_not_applied",
                    "session_id": context.session_id,
                    "current_status": details.status.value if details else None,
                },
            )
            return CancellationResult(CancellationResultStatus.RACE_LOST, details)

        if self._offers is not None:
            await self._offers.cancel_pending_redemption(customer_id, ride_id)
        await self._session.commit()
        context.clear_cancellation()
        logger.info(
            "ride_cancellation_succeeded",
            extra={
                "event": "ride_cancellation_succeeded",
                "session_id": context.session_id,
                "previous_status": previous_status.value,
            },
        )

        if previous_status is RideStatus.ASSIGNED:
            try:
                await self._driver_assignments.release_assignment_idempotently(ride_id)
            except Exception as exc:
                logger.warning(
                    "driver_release_failed",
                    extra={
                        "event": "driver_release_failed",
                        "session_id": context.session_id,
                        "error_type": type(exc).__name__,
                    },
                )
        details = await self._rides.get_status_for_customer(customer_id, ride_id)
        return CancellationResult(CancellationResultStatus.SUCCESS, details)

    async def cancel_customer_rides(
        self,
        customer_id: UUID,
        ride_ids: tuple[UUID, ...],
        context: RideContext,
    ) -> CancellationSetResult:
        """Apply one confirmed customer cancellation intent to an exact owned set."""
        if not self._identity_matches(customer_id, context):
            context.clear_cancellation()
            return CancellationSetResult(
                tuple(
                    CancellationResult(CancellationResultStatus.NOT_FOUND)
                    for _ in ride_ids
                )
            )
        if not context.cancellation_set_is_confirmed_for(ride_ids):
            return CancellationSetResult(
                tuple(
                    CancellationResult(CancellationResultStatus.CONFIRMATION_REQUIRED)
                    for _ in ride_ids
                )
            )
        confirmed_ids = ride_ids
        results: list[CancellationResult] = []
        for ride_id in confirmed_ids:
            context.select_cancellation_target(ride_id)
            context.record_cancellation_confirmation(ride_id, True)
            results.append(
                await self.cancel_customer_ride(customer_id, ride_id, context)
            )
        context.clear_cancellation()
        result = CancellationSetResult(tuple(results))
        succeeded = sum(
            item.status
            in {
                CancellationResultStatus.SUCCESS,
                CancellationResultStatus.IDEMPOTENT_SUCCESS,
            }
            for item in result.results
        )
        logger.info(
            "cancellation_set_completed"
            if succeeded == len(result.results)
            else "cancellation_set_partial_failure",
            extra={
                "event": "cancellation_set_completed"
                if succeeded == len(result.results)
                else "cancellation_set_partial_failure",
                "session_id": context.session_id,
                "requested_count": len(result.results),
                "succeeded_count": succeeded,
            },
        )
        return result

    async def transition_customer_ride(
        self,
        customer_id: UUID,
        ride_id: UUID,
        *,
        expected_status: RideStatus,
        requested_status: RideStatus,
    ) -> Ride | None:
        ride = await self._rides.transition_for_customer(
            customer_id,
            ride_id,
            expected_status=expected_status,
            requested_status=requested_status,
        )
        if ride is not None and self._offers is not None:
            await self._offers.finalize_redemption(customer_id, ride_id, requested_status)
        return ride

    @staticmethod
    def _identity_matches(customer_id: UUID, context: RideContext) -> bool:
        return context.identity_verified and context.verified_customer_id == customer_id


_REFERENCE_STOP_WORDS = {
    "meri", "mera", "ride", "status", "wali", "wala", "ki", "ka", "ko",
    "cancel", "karo", "kar", "do", "baje", "at", "to", "from", "the",
    "dono", "both", "all", "sabhi", "current", "active", "jo", "book", "hai",
}
_INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")


def _reference_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w]+", value.casefold())
        if token not in _REFERENCE_STOP_WORDS
    }


def _ride_reference_tokens(ride: RideStatusDetails) -> set[str]:
    local = ride.requested_ride_at.astimezone(_INDIA_TIMEZONE)
    values = " ".join(
        filter(
            None,
            (
                ride.pickup,
                ride.destination,
                ride.status.value,
                ride.vehicle_type_code,
                local.strftime("%Y %m %d %H %I %p"),
            ),
        )
    )
    tokens = _reference_tokens(values)
    tokens.update({str(local.hour), str(int(local.strftime("%I"))), str(local.day)})
    today = datetime.now(_INDIA_TIMEZONE).date()
    if local.date() == today:
        tokens.update({"today", "aaj"})
    elif (local.date() - today).days == 1:
        tokens.update({"tomorrow", "kal"})
    return tokens
