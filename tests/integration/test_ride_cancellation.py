from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.db.models.accepted_quote import AcceptedQuote
from boloride.db.models.offer_redemption import OfferRedemption
from boloride.domain.enums import RideStatus
from boloride.domain.models.cancellation import CancellationResultStatus
from boloride.domain.models.location import ResolvedLocation, TollStatus
from boloride.domain.models.offer import AppliedOfferSnapshot, DiscountType, RedemptionStatus
from boloride.domain.models.quote import FareComponent, FareComponentType, PricingResult, Quote
from boloride.domain.policies import CustomerIdentityState
from boloride.repositories.offer_repository import OfferRepository
from boloride.repositories.ride_repository import RideRepository
from boloride.repositories.user_repository import UserRepository
from boloride.services.offer_service import OfferService
from boloride.services.ride_service import RideService


class RecordingDriverRelease:
    def __init__(self, failure: Exception | None = None) -> None:
        self.calls = []
        self.failure = failure

    async def release_assignment_idempotently(self, ride_id):
        self.calls.append(ride_id)
        if self.failure:
            raise self.failure


def location(name: str, lat: str, lon: str) -> ResolvedLocation:
    return ResolvedLocation(name, Decimal(lat), Decimal(lon), display_name=name)


def quote(offer=None) -> Quote:
    now = datetime.now(UTC)
    components = (
        FareComponent(FareComponentType.BASE_FARE, Decimal("50.00")),
        FareComponent(FareComponentType.DISTANCE_FARE, Decimal("150.00")),
        FareComponent(FareComponentType.NIGHT_CHARGE, Decimal("0.00")),
        FareComponent(FareComponentType.AIRPORT_FEE, Decimal("0.00")),
    )
    applied = None
    if offer is not None:
        applied = AppliedOfferSnapshot(
            offer.id, offer.code, offer.display_name, DiscountType(offer.discount_type),
            offer.percentage, offer.maximum_discount, Decimal("20.00"), offer.currency,
            offer.version,
        )
    pricing = PricingResult(
        uuid4(), "sedan", 10000, 900, "mock", components, TollStatus.UNKNOWN,
        Decimal("180.00") if offer else Decimal("200.00"), "INR",
        Decimal("200.00") if offer else None, applied,
    )
    return Quote(uuid4(), "cancel-test", "d" * 64, pricing, now, now + timedelta(minutes=20))


def verified_context(customer_id) -> RideContext:
    return RideContext(
        session_id=f"cancel-{uuid4()}",
        caller_id=customer_id,
        identity_state=CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        verified_customer_id=customer_id,
    )


async def create_ride(session: AsyncSession, customer_id, suffix: str, *, offer=None):
    return await RideRepository(session).create_booked(
        uuid4(), customer_id,
        location("Home", "25.18", "75.83"),
        location("Station", "25.22", "75.88"),
        datetime.now(UTC) + timedelta(hours=1),
        provider="mock", provider_booking_id=f"cancel-{suffix}", accepted_quote=quote(offer),
    )


async def create_customer(session: AsyncSession, name: str):
    return await UserRepository(session).create(
        f"9{uuid4().int % 10**9:09d}", name, 30
    )


async def confirm(context: RideContext, ride_id) -> None:
    context.select_cancellation_target(ride_id)
    context.record_cancellation_confirmation(ride_id, True)


@pytest.mark.asyncio
async def test_booked_cancellation_sets_zero_cost_and_preserves_quote(db_session: AsyncSession):
    user = await create_customer(db_session, "Booked Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    snapshot = await db_session.scalar(select(AcceptedQuote).where(AcceptedQuote.ride_id == ride.id))
    before = (snapshot.estimated_total, snapshot.request_fingerprint, snapshot.quoted_at)
    context = verified_context(user.id)
    await confirm(context, ride.id)

    result = await RideService(db_session, RideRepository(db_session)).cancel_customer_ride(user.id, ride.id, context)

    assert result.status is CancellationResultStatus.SUCCESS
    assert result.ride.status is RideStatus.CANCELLED
    assert result.ride.final_customer_cost == Decimal("0.00")
    await db_session.refresh(snapshot)
    assert (snapshot.estimated_total, snapshot.request_fingerprint, snapshot.quoted_at) == before
    assert context.cancellation_target_ride_id is None


@pytest.mark.asyncio
async def test_assigned_cancellation_releases_driver_after_commit_and_survives_release_failure(db_session: AsyncSession):
    user = await create_customer(db_session, "Assigned Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    await RideRepository(db_session).transition_internal(ride.id, expected_status=RideStatus.BOOKED, requested_status=RideStatus.ASSIGNED)
    release = RecordingDriverRelease(RuntimeError("stage 8 unavailable"))
    context = verified_context(user.id)
    await confirm(context, ride.id)

    result = await RideService(db_session, RideRepository(db_session), driver_assignments=release).cancel_customer_ride(user.id, ride.id, context)

    assert result.status is CancellationResultStatus.SUCCESS
    assert release.calls == [ride.id]
    persisted = await RideRepository(db_session).get_for_customer(user.id, ride.id)
    assert persisted.status is RideStatus.CANCELLED
    assert persisted.final_customer_cost == Decimal("0.00")


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", [RideStatus.ON_TRIP, RideStatus.COMPLETED])
async def test_on_trip_and_completed_rides_are_not_cancellable(db_session: AsyncSession, terminal: RideStatus):
    user = await create_customer(db_session, f"Terminal {terminal.value}")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    repo = RideRepository(db_session)
    await repo.transition_internal(ride.id, expected_status=RideStatus.BOOKED, requested_status=RideStatus.ASSIGNED)
    await repo.transition_internal(ride.id, expected_status=RideStatus.ASSIGNED, requested_status=RideStatus.ON_TRIP)
    if terminal is RideStatus.COMPLETED:
        await repo.transition_internal(ride.id, expected_status=RideStatus.ON_TRIP, requested_status=RideStatus.COMPLETED)
    user_id, ride_id = user.id, ride.id
    await db_session.commit()
    context = verified_context(user_id)
    await confirm(context, ride_id)

    result = await RideService(db_session, repo).cancel_customer_ride(user_id, ride_id, context)
    assert result.status is CancellationResultStatus.NOT_CANCELLABLE
    assert result.ride.status is terminal


@pytest.mark.asyncio
async def test_cancelled_repeat_is_idempotent_only_for_owner(db_session: AsyncSession):
    owner = await create_customer(db_session, "Cancellation Owner")
    other = await create_customer(db_session, "Not Owner")
    ride = await create_ride(db_session, owner.id, uuid4().hex)
    owner_id, other_id, ride_id = owner.id, other.id, ride.id
    owner_context = verified_context(owner_id)
    await confirm(owner_context, ride_id)
    service = RideService(db_session, RideRepository(db_session))
    assert (await service.cancel_customer_ride(owner_id, ride_id, owner_context)).status is CancellationResultStatus.SUCCESS

    repeat_context = verified_context(owner_id)
    repeated = await service.cancel_customer_ride(owner_id, ride_id, repeat_context)
    assert repeated.status is CancellationResultStatus.IDEMPOTENT_SUCCESS
    other_result = await service.cancel_customer_ride(other_id, ride_id, verified_context(other_id))
    assert other_result.status is CancellationResultStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_cancellation_requires_separate_exact_ride_confirmation(db_session: AsyncSession):
    user = await create_customer(db_session, "Confirm Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    user_id, ride_id = user.id, ride.id
    await db_session.commit()
    context = verified_context(user_id)
    context.user_confirmed = True
    result = await RideService(db_session, RideRepository(db_session)).cancel_customer_ride(user_id, ride_id, context)
    assert result.status is CancellationResultStatus.CONFIRMATION_REQUIRED
    persisted = await RideRepository(db_session).get_for_customer(user_id, ride_id)
    assert persisted.status is RideStatus.BOOKED


@pytest.mark.asyncio
async def test_newer_on_trip_state_is_not_overwritten_by_stale_cancellation(db_session: AsyncSession):
    user = await create_customer(db_session, "Race Owner")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    repo = RideRepository(db_session)
    await repo.transition_internal(ride.id, expected_status=RideStatus.BOOKED, requested_status=RideStatus.ASSIGNED)
    context = verified_context(user.id)
    await confirm(context, ride.id)
    await repo.transition_internal(ride.id, expected_status=RideStatus.ASSIGNED, requested_status=RideStatus.ON_TRIP)
    user_id, ride_id = user.id, ride.id
    await db_session.commit()

    result = await RideService(db_session, repo).cancel_customer_ride(user_id, ride_id, context)
    assert result.status is CancellationResultStatus.NOT_CANCELLABLE
    assert result.ride.status is RideStatus.ON_TRIP


@pytest.mark.asyncio
async def test_pending_redemption_is_cancelled_in_same_operation(db_session: AsyncSession):
    user = await create_customer(db_session, "Offer Cancellation")
    offer_repo = OfferRepository(db_session)
    offer = await offer_repo.get_by_code("NEW_CUSTOMER")
    ride = await create_ride(db_session, user.id, uuid4().hex, offer=offer)
    offers = OfferService(offer_repo)
    await offers.create_pending_redemption(user.id, offer, ride.id)
    context = verified_context(user.id)
    await confirm(context, ride.id)

    result = await RideService(db_session, RideRepository(db_session), offers).cancel_customer_ride(user.id, ride.id, context)
    redemption = await db_session.scalar(select(OfferRedemption).where(OfferRedemption.ride_id == ride.id))
    assert result.status is CancellationResultStatus.SUCCESS
    assert redemption.status == RedemptionStatus.CANCELLED.value
    assert redemption.consumed_at is None


@pytest.mark.asyncio
async def test_customer_status_projection_is_current_and_safe(db_session: AsyncSession):
    user = await create_customer(db_session, "Status Owner")
    other = await create_customer(db_session, "Status Other")
    ride = await create_ride(db_session, user.id, uuid4().hex)
    service = RideService(db_session, RideRepository(db_session))
    details = await service.get_customer_ride_status(user.id, ride.id, verified_context(user.id))
    assert details.status is RideStatus.BOOKED
    assert details.destination == "Station"
    assert details.vehicle_type_code == "sedan"
    assert details.estimated_fare == Decimal("200.00")
    assert set(details.__dataclass_fields__) == {
        "ride_id", "status", "destination", "requested_ride_at",
        "vehicle_type_code", "estimated_fare", "currency", "final_customer_cost",
    }
    assert await service.get_customer_ride_status(other.id, ride.id, verified_context(other.id)) is None
