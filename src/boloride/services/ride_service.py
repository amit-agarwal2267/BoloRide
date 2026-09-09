import logging
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.db.models.ride import Ride
from boloride.domain.enums import RideStatus
from boloride.domain.models.cancellation import (
    CancellationResult,
    CancellationResultStatus,
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
                    "driver_assignment_release_failed",
                    extra={
                        "event": "driver_assignment_release_failed",
                        "session_id": context.session_id,
                        "error_type": type(exc).__name__,
                    },
                )
        details = await self._rides.get_status_for_customer(customer_id, ride_id)
        return CancellationResult(CancellationResultStatus.SUCCESS, details)

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
