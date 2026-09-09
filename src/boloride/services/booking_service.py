import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.db.models.booking_attempt import BookingAttempt
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.booking import BookingAttemptState, BookingOutcome, BookingResultStatus
from boloride.integrations.rideprovider.base import (
    ProviderCreateStatus,
    ProviderReconciliationStatus,
    RideBookingRequest,
    RideBookingResult,
    RideProvider,
)
from boloride.repositories.booking_attempt_repository import BookingAttemptRepository
from boloride.repositories.ride_repository import RideRepository
from boloride.services.booking_snapshots import (
    deserialize_authorization,
    deserialize_provider_result,
    serialize_authorization,
    serialize_provider_result,
)
from boloride.services.offer_service import OfferService
from boloride.services.quote_service import QuoteService
from boloride.services.vehicle_service import VehicleService

logger = logging.getLogger(__name__)


class BookingService:
    def __init__(
        self,
        session: AsyncSession,
        rides: RideRepository,
        attempts: BookingAttemptRepository,
        provider: RideProvider,
        vehicles: VehicleService,
        quotes: QuoteService,
        offers: OfferService | None = None,
        *,
        provider_call_lease: timedelta = timedelta(seconds=30),
    ) -> None:
        self._session = session
        self._rides = rides
        self._attempts = attempts
        self._provider = provider
        self._vehicles = vehicles
        self._quotes = quotes
        self._offers = offers
        self._provider_call_lease = provider_call_lease

    async def book_ride(self, user_id: UUID, context: RideContext) -> BookingOutcome:
        self._validate_identity_and_inputs(user_id, context)
        quote = context.current_quote
        if quote is None:
            raise DomainValidationError("a current fare quote is required before booking")

        attempt = await self._attempts.get_by_quote(quote.id)
        if attempt is None:
            vehicle = await self._vehicles.require_eligible_vehicle_type(
                context.selected_vehicle_type_code, context.passenger_count
            )
            quote = await self._quotes.require_bookable_quote(context)
            offer = None
            if quote.pricing.applied_offer is not None:
                if self._offers is None:
                    raise DomainValidationError("offer service is required for discounted booking")
                offer = await self._offers.revalidate_quote(user_id, quote)
            request_id = uuid4()
            request = RideBookingRequest(
                request_id, context.pickup, context.destination, context.ride_time,
                context.passenger_count, vehicle.code,
            )
            attempt = await self._create_attempt(user_id, request, quote, offer)
            if attempt.quote_id != quote.id:
                raise DomainValidationError("booking attempt quote binding is invalid")
        elif attempt.customer_id != user_id or attempt.request_fingerprint != quote.request_fingerprint:
            raise DomainValidationError("booking attempt does not belong to this customer and quote")

        return await self._continue_attempt(attempt, context)

    async def _create_attempt(self, user_id, request, quote, offer) -> BookingAttempt:
        attempt_id = request.request_id
        created = True
        values = {
            "id": attempt_id,
            "quote_id": quote.id,
            "customer_id": user_id,
            "request_fingerprint": quote.request_fingerprint,
            "provider": self._provider.provider_name.strip().casefold(),
            "provider_idempotency_key": f"booking-attempt-{attempt_id}",
            "state": BookingAttemptState.READY.value,
            "snapshot_version": 1,
            "authorized_quote_snapshot": serialize_authorization(request, quote),
            "offer_id": offer.id if offer else None,
            "capacity_reserved": offer is not None,
            "reconciliation_count": 0,
        }
        try:
            async with self._session.begin_nested():
                if offer is not None and self._offers is not None:
                    should_create = await self._offers.reserve_booking_attempt(
                        user_id, offer, quote.id
                    )
                    if not should_create:
                        attempt = await self._attempts.get_by_quote(quote.id)
                        if attempt is None:
                            raise DomainValidationError("booking attempt reservation race could not be resolved")
                        created = False
                    else:
                        attempt = await self._attempts.create(**values)
                else:
                    attempt = await self._attempts.create(**values)
        except IntegrityError:
            created = False
            attempt = await self._attempts.get_by_quote(quote.id)
            if attempt is None:
                raise
            logger.info("booking_attempt_reused", extra={"event": "booking_attempt_reused", "attempt_id": str(attempt.id)})
        await self._session.commit()
        if created:
            logger.info("booking_attempt_created", extra={"event": "booking_attempt_created", "attempt_id": str(attempt.id), "provider": attempt.provider})
        return attempt

    async def _continue_attempt(self, attempt: BookingAttempt, context: RideContext) -> BookingOutcome:
        state = BookingAttemptState(attempt.state)
        if state is BookingAttemptState.FINALIZED:
            return await self._successful_outcome(attempt, context, idempotent=True)
        if state is BookingAttemptState.DEFINITIVELY_FAILED:
            return BookingOutcome(BookingResultStatus.DEFINITIVE_FAILURE)
        if state is BookingAttemptState.REQUOTE_REQUIRED:
            return BookingOutcome(BookingResultStatus.REQUOTE_REQUIRED)
        if state is BookingAttemptState.PROVIDER_CONFIRMED:
            return await self._finalize(attempt, context)
        if state is BookingAttemptState.PROVIDER_CALLING:
            started = attempt.provider_call_started_at
            if started is not None and datetime.now(UTC) - started < self._provider_call_lease:
                logger.info("duplicate_provider_call_prevented", extra={"event": "duplicate_provider_call_prevented", "attempt_id": str(attempt.id), "attempt_state": state.value})
                return BookingOutcome(BookingResultStatus.IN_PROGRESS)
            return await self._reconcile(attempt, context)
        if state is BookingAttemptState.OUTCOME_UNKNOWN:
            return await self._reconcile(attempt, context)
        return await self._create_with_claim(attempt, context, BookingAttemptState.READY)

    async def _create_with_claim(self, attempt, context, expected) -> BookingOutcome:
        started = datetime.now(UTC)
        if not await self._attempts.claim(attempt.id, expected, started):
            await self._session.rollback()
            return BookingOutcome(BookingResultStatus.IN_PROGRESS)
        await self._session.commit()
        request, _ = deserialize_authorization(attempt.authorized_quote_snapshot)
        logger.info("provider_create_attempted", extra={"event": "provider_create_attempted", "attempt_id": str(attempt.id), "provider": attempt.provider})
        try:
            outcome = await self._provider.create_booking(request, idempotency_key=attempt.provider_idempotency_key)
        except Exception as exc:
            logger.warning("provider_outcome_unknown", extra={"event": "provider_outcome_unknown", "attempt_id": str(attempt.id), "provider": attempt.provider, "error_type": type(exc).__name__})
            await self._persist_unknown(attempt.id, type(exc).__name__)
            return BookingOutcome(BookingResultStatus.OUTCOME_UNKNOWN)
        if outcome.status is ProviderCreateStatus.REJECTED:
            await self._persist_terminal(attempt.id, BookingAttemptState.DEFINITIVELY_FAILED, outcome.failure_category)
            return BookingOutcome(BookingResultStatus.DEFINITIVE_FAILURE)
        if outcome.status is ProviderCreateStatus.UNKNOWN or outcome.booking is None:
            await self._persist_unknown(attempt.id, outcome.failure_category)
            return BookingOutcome(BookingResultStatus.OUTCOME_UNKNOWN)
        attempt_id, provider_name = attempt.id, attempt.provider
        try:
            attempt = await self._persist_confirmation(attempt.id, outcome.booking)
        except Exception as exc:
            await self._session.rollback()
            logger.warning("provider_confirmation_persistence_failed", extra={"event": "provider_confirmation_persistence_failed", "attempt_id": str(attempt_id), "provider": provider_name, "error_type": type(exc).__name__})
            return BookingOutcome(BookingResultStatus.OUTCOME_UNKNOWN)
        return await self._finalize(attempt, context)

    async def _reconcile(self, attempt, context) -> BookingOutcome:
        logger.info("booking_reconciliation_attempted", extra={"event": "booking_reconciliation_attempted", "attempt_id": str(attempt.id), "provider": attempt.provider})
        try:
            outcome = await self._provider.reconcile_booking(attempt.provider_idempotency_key)
        except Exception as exc:
            await self._persist_unknown(attempt.id, type(exc).__name__, reconciled=True)
            return BookingOutcome(BookingResultStatus.OUTCOME_UNKNOWN)
        if outcome.status is ProviderReconciliationStatus.CONFIRMED and outcome.booking is not None:
            attempt_id, provider_name = attempt.id, attempt.provider
            try:
                attempt = await self._persist_confirmation(attempt.id, outcome.booking, reconciled=True)
            except Exception as exc:
                await self._session.rollback()
                logger.warning("provider_confirmation_persistence_failed", extra={"event": "provider_confirmation_persistence_failed", "attempt_id": str(attempt_id), "provider": provider_name, "error_type": type(exc).__name__})
                return BookingOutcome(BookingResultStatus.OUTCOME_UNKNOWN)
            return await self._finalize(attempt, context)
        if outcome.status is ProviderReconciliationStatus.UNKNOWN:
            await self._persist_unknown(attempt.id, outcome.failure_category, reconciled=True)
            return BookingOutcome(BookingResultStatus.OUTCOME_UNKNOWN)

        if not self._provider.supports_safe_retry_after_definitive_absence:
            await self._persist_terminal(attempt.id, BookingAttemptState.REQUOTE_REQUIRED, "provider_retry_not_safe")
            return BookingOutcome(BookingResultStatus.REQUOTE_REQUIRED)
        try:
            quote = await self._quotes.require_bookable_quote(context)
            if quote.pricing.applied_offer is not None:
                if self._offers is None:
                    raise DomainValidationError("offer service is required for discounted booking")
                await self._offers.revalidate_quote(attempt.customer_id, quote)
        except DomainValidationError:
            await self._persist_terminal(attempt.id, BookingAttemptState.REQUOTE_REQUIRED, "authorization_expired")
            return BookingOutcome(BookingResultStatus.REQUOTE_REQUIRED)
        current_state = BookingAttemptState(attempt.state)
        return await self._create_with_claim(attempt, context, current_state)

    async def _persist_confirmation(self, attempt_id: UUID, result: RideBookingResult, *, reconciled: bool = False) -> BookingAttempt:
        attempt = await self._attempts.get(attempt_id, for_update=True)
        if attempt is None:
            raise DomainValidationError("booking attempt disappeared")
        if result.provider.strip().casefold() != attempt.provider:
            raise DomainValidationError("provider result identity does not match booking attempt")
        attempt.state = BookingAttemptState.PROVIDER_CONFIRMED.value
        attempt.provider_booking_id = result.provider_booking_id.strip()
        attempt.provider_result_snapshot = serialize_provider_result(result)
        if reconciled:
            attempt.reconciliation_count += 1
            attempt.last_reconciled_at = datetime.now(UTC)
        await self._session.commit()
        logger.info("provider_booking_confirmed", extra={"event": "provider_booking_confirmed", "attempt_id": str(attempt.id), "provider": attempt.provider})
        return attempt

    async def _persist_unknown(self, attempt_id: UUID, category: str | None, *, reconciled: bool = False) -> None:
        attempt = await self._attempts.get(attempt_id, for_update=True)
        if attempt is None:
            return
        attempt.state = BookingAttemptState.OUTCOME_UNKNOWN.value
        attempt.failure_category = (category or "unknown")[:64]
        if reconciled:
            attempt.reconciliation_count += 1
            attempt.last_reconciled_at = datetime.now(UTC)
        await self._session.commit()

    async def _persist_terminal(self, attempt_id: UUID, state: BookingAttemptState, category: str | None) -> None:
        attempt = await self._attempts.get(attempt_id, for_update=True)
        if attempt is None:
            return
        attempt.state = state.value
        attempt.failure_category = (category or state.value)[:64]
        attempt.capacity_reserved = False
        await self._session.commit()

    async def _finalize(self, attempt: BookingAttempt, context: RideContext) -> BookingOutcome:
        attempt_id = attempt.id
        provider_name = attempt.provider
        try:
            locked = await self._attempts.get(attempt_id, for_update=True)
            if locked is None:
                raise DomainValidationError("booking attempt disappeared")
            if locked.state == BookingAttemptState.FINALIZED.value:
                await self._session.commit()
                return await self._successful_outcome(locked, context, idempotent=True)
            request, quote = deserialize_authorization(locked.authorized_quote_snapshot)
            result = deserialize_provider_result(locked.provider_result_snapshot)
            ride = await self._rides.get_by_id_internal(locked.id)
            if ride is None:
                ride = await self._rides.create_booked(
                    locked.id, locked.customer_id, request.pickup, request.destination,
                    request.requested_ride_at, provider=result.provider,
                    provider_booking_id=result.provider_booking_id, accepted_quote=quote,
                )
            if locked.offer_id is not None and locked.capacity_reserved:
                if self._offers is None:
                    raise DomainValidationError("offer service is required to finalize reservation")
                await self._offers.convert_attempt_reservation(locked.customer_id, locked.offer_id, ride.id)
            locked.ride_id = ride.id
            locked.capacity_reserved = False
            locked.state = BookingAttemptState.FINALIZED.value
            await self._session.commit()
        except Exception as exc:
            await self._session.rollback()
            logger.warning("local_booking_finalization_failed", extra={"event": "local_booking_finalization_failed", "attempt_id": str(attempt_id), "provider": provider_name, "error_type": type(exc).__name__})
            return BookingOutcome(BookingResultStatus.OUTCOME_UNKNOWN)
        context.booking_id = ride.id
        context.booking_confirmed = True
        return BookingOutcome(BookingResultStatus.SUCCESS, ride, result, quote)

    async def _successful_outcome(self, attempt: BookingAttempt, context: RideContext, *, idempotent: bool) -> BookingOutcome:
        ride = await self._rides.get_by_id_internal(attempt.ride_id or attempt.id)
        _, quote = deserialize_authorization(attempt.authorized_quote_snapshot)
        result = deserialize_provider_result(attempt.provider_result_snapshot)
        if ride is None:
            raise DomainValidationError("finalized booking is missing its ride")
        context.booking_id = ride.id
        context.booking_confirmed = True
        return BookingOutcome(BookingResultStatus.IDEMPOTENT_SUCCESS if idempotent else BookingResultStatus.SUCCESS, ride, result, quote)

    @staticmethod
    def _validate_identity_and_inputs(user_id: UUID, context: RideContext) -> None:
        if not context.identity_verified or context.verified_customer_id != user_id:
            raise DomainValidationError("verified customer identity is required before booking")
        if context.pickup is None or context.destination is None:
            raise DomainValidationError("pickup and destination are required before booking")
        if context.ride_time is None or context.ride_time.tzinfo is None:
            raise DomainValidationError("timezone-aware ride time is required before booking")
        if context.clarification_required:
            raise DomainValidationError("location clarification is required")
        if context.selected_vehicle_type_code is None:
            raise DomainValidationError("vehicle type must be selected before booking")
