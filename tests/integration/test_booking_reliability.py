import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.db.models.accepted_quote import AcceptedQuote
from boloride.db.models.booking_attempt import BookingAttempt
from boloride.db.models.offer_redemption import OfferRedemption
from boloride.db.models.ride import Ride
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.booking import BookingAttemptState, BookingResultStatus
from boloride.domain.models.location import ResolvedLocation, TollStatus
from boloride.domain.models.offer import AppliedOfferSnapshot, DiscountType
from boloride.domain.models.quote import FareComponent, FareComponentType, PricingResult, Quote
from boloride.domain.policies import CustomerIdentityState
from boloride.integrations.rideprovider.base import ProviderCreateStatus, ProviderReconciliationStatus
from boloride.integrations.rideprovider.mock_provider import MockRideProvider
from boloride.repositories.booking_attempt_repository import BookingAttemptRepository
from boloride.repositories.offer_repository import OfferRepository
from boloride.repositories.ride_repository import RideRepository
from boloride.repositories.user_repository import UserRepository
from boloride.repositories.vehicle_type_repository import VehicleTypeRepository
from boloride.services.booking_service import BookingService
from boloride.services.offer_service import OfferService
from boloride.services.vehicle_service import VehicleService


class QuoteGuard:
    async def require_bookable_quote(self, context: RideContext) -> Quote:
        quote = context.current_quote
        if quote is None or context.confirmed_quote_id != quote.id:
            raise DomainValidationError("confirmation for current quote required")
        if not quote.is_time_valid(datetime.now(UTC)):
            raise DomainValidationError("fare quote has expired")
        return quote


class FailOnceRideRepository(RideRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.fail = True

    async def create_booked(self, *args, **kwargs):
        if self.fail:
            self.fail = False
            raise RuntimeError("controlled finalization failure")
        return await super().create_booked(*args, **kwargs)


class NoSafeRetryProvider(MockRideProvider):
    supports_safe_retry_after_definitive_absence = False


def make_context(customer_id, *, quote_id=None, expires_at=None, offer=None) -> RideContext:
    now = datetime.now(UTC)
    context = RideContext(
        session_id=f"booking-{uuid4()}", caller_id=customer_id,
        identity_state=CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        verified_customer_id=customer_id,
        pickup=ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83")),
        destination=ResolvedLocation("Station", Decimal("25.22"), Decimal("75.88")),
        ride_time=now + timedelta(hours=1), passenger_count=4,
        selected_vehicle_type_code="sedan",
    )
    components = (
        FareComponent(FareComponentType.BASE_FARE, Decimal("50.00")),
        FareComponent(FareComponentType.DISTANCE_FARE, Decimal("150.00")),
        FareComponent(FareComponentType.NIGHT_CHARGE, Decimal("0.00")),
        FareComponent(FareComponentType.AIRPORT_FEE, Decimal("0.00")),
    )
    applied = None
    total = Decimal("200.00")
    pre_total = None
    if offer is not None:
        applied = AppliedOfferSnapshot(
            offer.id, offer.code, offer.display_name, DiscountType(offer.discount_type),
            offer.percentage, offer.maximum_discount, Decimal("20.00"), offer.currency, offer.version,
        )
        total, pre_total = Decimal("180.00"), Decimal("200.00")
    pricing = PricingResult(uuid4(), "sedan", 10000, 900, "mock", components, TollStatus.UNKNOWN, total, "INR", pre_total, applied)
    quote = Quote(quote_id or uuid4(), context.session_id, "b" * 64, pricing, now, expires_at or now + timedelta(minutes=20))
    context.set_quote(quote)
    context.confirm_quote(quote.id)
    return context


def service(session, provider, *, rides=None, offers=None, lease=timedelta(seconds=30)):
    return BookingService(
        session, rides or RideRepository(session), BookingAttemptRepository(session), provider,
        VehicleService(VehicleTypeRepository(session)), QuoteGuard(), offers,
        provider_call_lease=lease,
    )


async def customer(session: AsyncSession):
    return await UserRepository(session).create(f"9{uuid4().int % 10**9:09d}", "Stage Six", 30)


@pytest.mark.asyncio
async def test_successful_retry_reuses_attempt_provider_booking_and_local_rows(db_session: AsyncSession):
    user = await customer(db_session)
    user_id = user.id
    context = make_context(user_id)
    provider = MockRideProvider()
    booking = service(db_session, provider)
    first = await booking.book_ride(user.id, context)
    second = await booking.book_ride(user.id, context)
    assert first.status is BookingResultStatus.SUCCESS
    assert second.status is BookingResultStatus.IDEMPOTENT_SUCCESS
    assert first.ride.id == second.ride.id
    assert provider.create_call_count == 1
    assert await db_session.scalar(select(func.count()).select_from(BookingAttempt).where(BookingAttempt.quote_id == context.current_quote.id)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Ride).where(Ride.id == first.ride.id)) == 1
    assert await db_session.scalar(select(func.count()).select_from(AcceptedQuote).where(AcceptedQuote.ride_id == first.ride.id)) == 1


@pytest.mark.asyncio
async def test_pickup_instruction_reaches_provider_snapshot_and_persisted_ride(db_session: AsyncSession):
    user = await customer(db_session)
    user_id = user.id
    context = make_context(user_id)
    context.set_pickup_instructions("HDFC Bank ke bagal mein")
    provider = MockRideProvider()

    result = await service(db_session, provider).book_ride(user.id, context)

    assert result.status is BookingResultStatus.SUCCESS
    assert provider.create_requests[0].pickup_instructions == "HDFC Bank ke bagal mein"
    attempt = await BookingAttemptRepository(db_session).get_by_quote(
        context.current_quote.id
    )
    assert attempt.authorized_quote_snapshot["request"]["pickup_instructions"] == "HDFC Bank ke bagal mein"
    ride = await RideRepository(db_session).get_by_id_internal(result.ride.id)
    assert ride.pickup_instructions == "HDFC Bank ke bagal mein"


@pytest.mark.asyncio
async def test_unknown_reconciles_before_create_and_can_finalize(db_session: AsyncSession):
    user = await customer(db_session)
    context = make_context(user.id)
    provider = MockRideProvider()
    provider.queue_create(ProviderCreateStatus.UNKNOWN, booking_created=True)
    booking = service(db_session, provider)
    first = await booking.book_ride(user.id, context)
    second = await booking.book_ride(user.id, context)
    assert first.status is BookingResultStatus.OUTCOME_UNKNOWN
    assert second.status is BookingResultStatus.SUCCESS
    assert provider.create_call_count == 1
    assert provider.reconciliation_call_count == 1


@pytest.mark.asyncio
async def test_reconciliation_unknown_never_retries_create(db_session: AsyncSession):
    user = await customer(db_session)
    context = make_context(user.id)
    provider = MockRideProvider()
    provider.queue_create(ProviderCreateStatus.UNKNOWN)
    provider.queue_reconciliation(ProviderReconciliationStatus.UNKNOWN)
    booking = service(db_session, provider)
    assert (await booking.book_ride(user.id, context)).status is BookingResultStatus.OUTCOME_UNKNOWN
    assert (await booking.book_ride(user.id, context)).status is BookingResultStatus.OUTCOME_UNKNOWN
    assert provider.create_call_count == 1


@pytest.mark.asyncio
async def test_confirmed_absence_retries_only_with_same_key_when_provider_supports_it(db_session: AsyncSession):
    user = await customer(db_session)
    context = make_context(user.id)
    provider = MockRideProvider()
    provider.queue_create(ProviderCreateStatus.UNKNOWN)
    provider.queue_reconciliation(ProviderReconciliationStatus.DEFINITIVELY_ABSENT)
    booking = service(db_session, provider)
    assert (await booking.book_ride(user.id, context)).status is BookingResultStatus.OUTCOME_UNKNOWN
    assert (await booking.book_ride(user.id, context)).status is BookingResultStatus.SUCCESS
    assert provider.create_call_count == 2
    assert len(set(provider.create_idempotency_keys)) == 1
    assert provider.logical_booking_count == 1


@pytest.mark.asyncio
async def test_definitive_rejection_creates_no_ride_and_releases_reservation(db_session: AsyncSession):
    user = await customer(db_session)
    context = make_context(user.id)
    provider = MockRideProvider()
    provider.queue_create(ProviderCreateStatus.REJECTED)
    result = await service(db_session, provider).book_ride(user.id, context)
    attempt = await BookingAttemptRepository(db_session).get_by_quote(context.current_quote.id)
    assert result.status is BookingResultStatus.DEFINITIVE_FAILURE
    assert attempt.state == BookingAttemptState.DEFINITIVELY_FAILED.value
    assert await db_session.scalar(select(func.count()).select_from(Ride).where(Ride.id == attempt.id)) == 0


@pytest.mark.asyncio
async def test_provider_without_safe_same_key_retry_requires_requote(db_session: AsyncSession):
    user = await customer(db_session)
    context = make_context(user.id)
    provider = NoSafeRetryProvider()
    provider.queue_create(ProviderCreateStatus.UNKNOWN)
    assert (await service(db_session, provider).book_ride(user.id, context)).status is BookingResultStatus.OUTCOME_UNKNOWN
    assert (await service(db_session, provider).book_ride(user.id, context)).status is BookingResultStatus.REQUOTE_REQUIRED
    assert provider.create_call_count == 1


@pytest.mark.asyncio
async def test_provider_success_then_local_failure_recovers_without_second_create(db_session: AsyncSession):
    user = await customer(db_session)
    user_id = user.id
    context = make_context(user_id)
    provider = MockRideProvider()
    rides = FailOnceRideRepository(db_session)
    booking = service(db_session, provider, rides=rides)
    assert (await booking.book_ride(user_id, context)).status is BookingResultStatus.RECONCILIATION_PENDING
    assert await db_session.scalar(select(func.count()).select_from(Ride).where(Ride.id == (await BookingAttemptRepository(db_session).get_by_quote(context.current_quote.id)).id)) == 0
    context.current_quote = Quote(
        context.current_quote.id, context.current_quote.session_id,
        context.current_quote.request_fingerprint, context.current_quote.pricing,
        datetime.now(UTC) - timedelta(minutes=30), datetime.now(UTC) - timedelta(minutes=10),
    )
    recovered = await booking.book_ride(user_id, context)
    assert recovered.status is BookingResultStatus.SUCCESS
    assert provider.create_call_count == 1
    assert await db_session.scalar(select(func.count()).select_from(Ride).where(Ride.id == recovered.ride.id)) == 1
    assert await db_session.scalar(select(func.count()).select_from(AcceptedQuote).where(AcceptedQuote.ride_id == recovered.ride.id)) == 1


@pytest.mark.asyncio
async def test_status_reconciliation_finalizes_existing_attempt_without_second_create(
    db_session: AsyncSession,
):
    user = await customer(db_session)
    user_id = user.id
    context = make_context(user_id)
    provider = MockRideProvider()
    booking = service(
        db_session, provider, rides=FailOnceRideRepository(db_session)
    )

    first = await booking.book_ride(user_id, context)
    recovered = await booking.reconcile_pending_booking(user_id, context)

    assert first.status is BookingResultStatus.RECONCILIATION_PENDING
    assert recovered is not None
    assert recovered.status is BookingResultStatus.SUCCESS
    assert provider.create_call_count == 1


@pytest.mark.asyncio
async def test_status_reconciliation_unknown_stays_uncertain_without_retrying_create(
    db_session: AsyncSession,
):
    user = await customer(db_session)
    context = make_context(user.id)
    provider = MockRideProvider()
    provider.queue_create(ProviderCreateStatus.UNKNOWN)
    provider.queue_reconciliation(ProviderReconciliationStatus.UNKNOWN)
    booking = service(db_session, provider)

    first = await booking.book_ride(user.id, context)
    pending = await booking.reconcile_pending_booking(user.id, context)

    assert first.status is BookingResultStatus.OUTCOME_UNKNOWN
    assert pending is not None
    assert pending.status is BookingResultStatus.OUTCOME_UNKNOWN
    assert provider.create_call_count == 1
    assert provider.reconciliation_call_count == 1


@pytest.mark.asyncio
async def test_status_reconciliation_definitive_absence_never_retries_create(
    db_session: AsyncSession,
):
    user = await customer(db_session)
    context = make_context(user.id)
    provider = MockRideProvider()
    provider.queue_create(ProviderCreateStatus.UNKNOWN)
    provider.queue_reconciliation(ProviderReconciliationStatus.DEFINITIVELY_ABSENT)
    booking = service(db_session, provider)

    await booking.book_ride(user.id, context)
    result = await booking.reconcile_pending_booking(user.id, context)

    assert result is not None
    assert result.status is BookingResultStatus.DEFINITIVE_FAILURE
    assert provider.create_call_count == 1
    assert provider.reconciliation_call_count == 1


@pytest.mark.asyncio
async def test_offer_change_does_not_block_confirmed_provider_recovery(db_session: AsyncSession):
    user = await customer(db_session)
    user_id = user.id
    offer_repo = OfferRepository(db_session)
    offer = await offer_repo.get_by_code("NEW_CUSTOMER")
    offer_id = offer.id
    context = make_context(user_id, offer=offer)
    provider = MockRideProvider()
    rides = FailOnceRideRepository(db_session)
    offers = OfferService(offer_repo, QuoteGuard())
    booking = service(db_session, provider, rides=rides, offers=offers)
    assert (await booking.book_ride(user_id, context)).status is BookingResultStatus.RECONCILIATION_PENDING
    offer = await offer_repo.get_by_id(offer_id)
    offer.active = False
    offer.version += 1
    await db_session.commit()
    recovered = await booking.book_ride(user_id, context)
    assert recovered.status is BookingResultStatus.SUCCESS
    assert provider.create_call_count == 1
    redemption = await db_session.scalar(select(OfferRedemption).where(OfferRedemption.ride_id == recovered.ride.id))
    assert redemption is not None
    offer.active = True
    offer.version -= 1
    await db_session.commit()


@pytest.mark.asyncio
async def test_fresh_provider_claim_returns_in_progress_without_reconciliation(db_session: AsyncSession):
    user = await customer(db_session)
    context = make_context(user.id)
    provider = MockRideProvider()
    booking = service(db_session, provider)
    provider.queue_create(ProviderCreateStatus.UNKNOWN)
    await booking.book_ride(user.id, context)
    attempt = await BookingAttemptRepository(db_session).get_by_quote(context.current_quote.id)
    attempt.state = BookingAttemptState.PROVIDER_CALLING.value
    attempt.provider_call_started_at = datetime.now(UTC)
    await db_session.commit()
    assert (await booking.book_ride(user.id, context)).status is BookingResultStatus.IN_PROGRESS
    assert provider.reconciliation_call_count == 0


@pytest.mark.asyncio
async def test_confirmed_absence_with_expired_quote_releases_offer_reservation(db_session: AsyncSession):
    user = await customer(db_session)
    offer_repo = OfferRepository(db_session)
    offer = await offer_repo.get_by_code("NEW_CUSTOMER")
    context = make_context(user.id, offer=offer)
    provider = MockRideProvider()
    provider.queue_create(ProviderCreateStatus.UNKNOWN)
    offers = OfferService(offer_repo, QuoteGuard())
    booking = service(db_session, provider, offers=offers)
    assert (await booking.book_ride(user.id, context)).status is BookingResultStatus.OUTCOME_UNKNOWN
    context.current_quote = Quote(
        context.current_quote.id, context.current_quote.session_id,
        context.current_quote.request_fingerprint, context.current_quote.pricing,
        datetime.now(UTC) - timedelta(minutes=30), datetime.now(UTC) - timedelta(minutes=10),
    )
    result = await booking.book_ride(user.id, context)
    attempt = await BookingAttemptRepository(db_session).get_by_quote(context.current_quote.id)
    assert result.status is BookingResultStatus.REQUOTE_REQUIRED
    assert attempt.capacity_reserved is False
    assert provider.create_call_count == 1


@pytest.mark.asyncio
async def test_discounted_finalization_converts_one_reservation_to_one_pending(db_session: AsyncSession):
    user = await customer(db_session)
    offer_repo = OfferRepository(db_session)
    offer = await offer_repo.get_by_code("NEW_CUSTOMER")
    context = make_context(user.id, offer=offer)
    offers = OfferService(offer_repo, QuoteGuard())
    result = await service(db_session, MockRideProvider(), offers=offers).book_ride(user.id, context)
    attempt = await BookingAttemptRepository(db_session).get_by_quote(context.current_quote.id)
    assert result.status is BookingResultStatus.SUCCESS
    assert attempt.capacity_reserved is False
    assert await db_session.scalar(select(func.count()).select_from(OfferRedemption).where(OfferRedemption.ride_id == result.ride.id)) == 1


@pytest.mark.asyncio
async def test_unknown_discounted_attempt_reserves_capacity(db_session: AsyncSession):
    user = await customer(db_session)
    offer_repo = OfferRepository(db_session)
    offer = await offer_repo.create(
        code=f"STAGE6_{uuid4().hex.upper()}", display_name="Stage 6 Capacity",
        discount_type="percentage", percentage=Decimal("10.00"),
        maximum_discount=Decimal("50.00"), currency="INR",
        maximum_redemptions_per_customer=1, eligibility_type="new_customer",
        active=True, effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_until=None, version=1,
    )
    offers = OfferService(offer_repo, QuoteGuard())
    provider = MockRideProvider()
    provider.queue_create(ProviderCreateStatus.UNKNOWN)
    first = make_context(user.id, offer=offer)
    assert (await service(db_session, provider, offers=offers).book_ride(user.id, first)).status is BookingResultStatus.OUTCOME_UNKNOWN
    second = make_context(user.id, offer=offer)
    with pytest.raises(DomainValidationError, match="capacity"):
        await service(db_session, provider, offers=offers).book_ride(user.id, second)
    await db_session.rollback()
    attempt = await BookingAttemptRepository(db_session).get_by_quote(first.current_quote.id)
    assert attempt.capacity_reserved is True


@pytest.mark.asyncio
async def test_concurrent_same_quote_converges_on_one_attempt_and_ride(app):
    provider = MockRideProvider()
    async with app.state.db_session_factory() as setup:
        user = await customer(setup)
        user_id = user.id
        await setup.commit()
    original = make_context(user_id)
    contexts = (deepcopy(original), deepcopy(original))

    async def run(context):
        async with app.state.db_session_factory() as session:
            return await service(session, provider).book_ride(user_id, context)

    results = await asyncio.gather(*(run(context) for context in contexts))
    async with app.state.db_session_factory() as verify:
        assert await verify.scalar(select(func.count()).select_from(BookingAttempt).where(BookingAttempt.quote_id == original.current_quote.id)) == 1
        attempt = await BookingAttemptRepository(verify).get_by_quote(original.current_quote.id)
        assert await verify.scalar(select(func.count()).select_from(Ride).where(Ride.id == attempt.ride_id)) == 1
    assert provider.create_call_count == 1
    assert {result.status for result in results} <= {
        BookingResultStatus.SUCCESS,
        BookingResultStatus.IDEMPOTENT_SUCCESS,
        BookingResultStatus.IN_PROGRESS,
    }


@pytest.mark.asyncio
async def test_concurrent_discounted_same_quote_reuses_its_reserved_slot(app):
    provider = MockRideProvider()
    async with app.state.db_session_factory() as setup:
        user = await customer(setup)
        offer = await OfferRepository(setup).get_by_code("NEW_CUSTOMER")
        user_id = user.id
        original = make_context(user_id, offer=offer)
        await setup.commit()
    contexts = (deepcopy(original), deepcopy(original))

    async def run(context):
        async with app.state.db_session_factory() as session:
            offers = OfferService(OfferRepository(session), QuoteGuard())
            return await service(session, provider, offers=offers).book_ride(user_id, context)

    results = await asyncio.gather(*(run(context) for context in contexts))
    async with app.state.db_session_factory() as verify:
        attempt = await BookingAttemptRepository(verify).get_by_quote(original.current_quote.id)
        assert attempt is not None and attempt.capacity_reserved is False
        assert await verify.scalar(select(func.count()).select_from(OfferRedemption).where(OfferRedemption.ride_id == attempt.ride_id)) == 1
    assert provider.create_call_count == 1
    assert BookingResultStatus.DEFINITIVE_FAILURE not in {result.status for result in results}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active_status", ["booked", "assigned", "on_trip"]
)
async def test_different_booking_is_blocked_by_existing_active_ride(
    db_session: AsyncSession, active_status: str
) -> None:
    user = await customer(db_session)
    provider = MockRideProvider()
    booking = service(db_session, provider)
    first = await booking.book_ride(user.id, make_context(user.id))
    if active_status != "booked":
        await db_session.execute(
            update(Ride).where(Ride.id == first.ride.id).values(status=active_status)
        )
        await db_session.commit()

    blocked = await booking.book_ride(user.id, make_context(user.id))

    assert blocked.status is BookingResultStatus.ACTIVE_RIDE_EXISTS
    assert blocked.active_ride is not None
    assert blocked.active_ride.status == active_status
    assert provider.create_call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["completed", "cancelled"])
async def test_terminal_ride_allows_subsequent_booking(
    db_session: AsyncSession, terminal_status: str
) -> None:
    user = await customer(db_session)
    provider = MockRideProvider()
    booking = service(db_session, provider)
    first = await booking.book_ride(user.id, make_context(user.id))
    values = {"status": terminal_status}
    if terminal_status == "cancelled":
        values["final_customer_cost"] = Decimal("0.00")
    await db_session.execute(
        update(Ride).where(Ride.id == first.ride.id).values(**values)
    )
    await db_session.commit()

    second = await booking.book_ride(user.id, make_context(user.id))

    assert second.status is BookingResultStatus.SUCCESS
    assert provider.create_call_count == 2


@pytest.mark.asyncio
async def test_concurrent_different_quotes_create_only_one_provider_booking(app):
    provider = MockRideProvider()
    async with app.state.db_session_factory() as setup:
        user = await customer(setup)
        user_id = user.id
        await setup.commit()
    contexts = (make_context(user_id), make_context(user_id))

    async def run(context):
        async with app.state.db_session_factory() as session:
            return await service(session, provider).book_ride(user_id, context)

    results = await asyncio.gather(*(run(context) for context in contexts))

    assert {result.status for result in results} == {
        BookingResultStatus.SUCCESS,
        BookingResultStatus.ACTIVE_RIDE_EXISTS,
    }
    assert provider.create_call_count == 1
    async with app.state.db_session_factory() as verify:
        active_count = await verify.scalar(
            select(func.count())
            .select_from(Ride)
            .where(
                Ride.user_id == user_id,
                Ride.status.in_(("booked", "assigned", "on_trip")),
            )
        )
        assert active_count == 1
