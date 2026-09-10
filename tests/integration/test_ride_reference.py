from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.agents.context import RideContext
from boloride.domain.enums import RideStatus
from boloride.domain.models.cancellation import RideReferenceResolutionStatus
from boloride.domain.models.location import ResolvedLocation, TollStatus
from boloride.domain.models.quote import (
    FareComponent,
    FareComponentType,
    PricingResult,
    Quote,
)
from boloride.domain.policies import CustomerIdentityState
from boloride.repositories.ride_repository import RideRepository
from boloride.repositories.user_repository import UserRepository
from boloride.services.ride_service import RideService


def location(name: str, latitude: str, longitude: str) -> ResolvedLocation:
    return ResolvedLocation(
        name,
        Decimal(latitude),
        Decimal(longitude),
        display_name=name,
        city="Kota",
        state="Rajasthan",
        country="India",
    )


def quote(session_id: str, vehicle: str = "auto") -> Quote:
    now = datetime.now(UTC)
    pricing = PricingResult(
        uuid4(),
        vehicle,
        5_000,
        900,
        "mock",
        (
            FareComponent(FareComponentType.BASE_FARE, Decimal("30.00")),
            FareComponent(FareComponentType.DISTANCE_FARE, Decimal("50.00")),
            FareComponent(FareComponentType.NIGHT_CHARGE, Decimal("0.00")),
            FareComponent(FareComponentType.AIRPORT_FEE, Decimal("0.00")),
        ),
        TollStatus.NO_TOLL,
        Decimal("80.00"),
        "INR",
    )
    return Quote(uuid4(), session_id, "f" * 64, pricing, now, now + timedelta(minutes=20))


def context(customer_id) -> RideContext:
    return RideContext(
        session_id=f"reference-{uuid4()}",
        caller_id=customer_id,
        identity_state=CustomerIdentityState.VERIFIED_RETURNING_CUSTOMER,
        verified_customer_id=customer_id,
    )


async def customer(session: AsyncSession, name: str):
    return await UserRepository(session).create(
        f"9{uuid4().int % 10**9:09d}", name, 30
    )


async def ride(
    session: AsyncSession,
    customer_id,
    destination: str,
    requested_at: datetime,
):
    return await RideRepository(session).create_booked(
        uuid4(),
        customer_id,
        location("Home", "25.18", "75.83"),
        location(destination, "25.22", "75.88"),
        requested_at,
        provider="mock",
        provider_booking_id=f"reference-{uuid4()}",
        accepted_quote=quote(f"reference-{uuid4()}"),
    )


async def complete_ride(session: AsyncSession, ride_id) -> None:
    repository = RideRepository(session)
    for current, requested in (
        (RideStatus.BOOKED, RideStatus.ASSIGNED),
        (RideStatus.ASSIGNED, RideStatus.ON_TRIP),
        (RideStatus.ON_TRIP, RideStatus.COMPLETED),
    ):
        assert await repository.transition_internal(
            ride_id,
            expected_status=current,
            requested_status=requested,
        )


@pytest.mark.asyncio
async def test_single_owned_ride_resolves_without_customer_uuid(
    db_session: AsyncSession,
) -> None:
    owner = await customer(db_session, "Reference Owner")
    expected = await ride(
        db_session, owner.id, "Kota Junction", datetime.now(UTC) + timedelta(hours=1)
    )

    result = await RideService(
        db_session, RideRepository(db_session)
    ).resolve_customer_ride_reference(owner.id, context(owner.id))

    assert result.status is RideReferenceResolutionStatus.RESOLVED
    assert result.ride is not None and result.ride.ride_id == expected.id


@pytest.mark.asyncio
async def test_multiple_rides_return_customer_safe_ambiguity_and_natural_match(
    db_session: AsyncSession,
) -> None:
    owner = await customer(db_session, "Multiple Reference Owner")
    now = datetime.now(UTC)
    station = await ride(db_session, owner.id, "Kota Junction", now + timedelta(hours=2))
    await complete_ride(db_session, station.id)
    mall = await ride(db_session, owner.id, "City Mall", now + timedelta(days=1))
    await complete_ride(db_session, mall.id)
    service = RideService(db_session, RideRepository(db_session))
    ride_context = context(owner.id)

    ambiguous = await service.resolve_customer_ride_reference(owner.id, ride_context)
    resolved = await service.resolve_customer_ride_reference(
        owner.id, ride_context, reference="Kota Junction wali"
    )

    assert ambiguous.status is RideReferenceResolutionStatus.AMBIGUOUS
    assert len(ambiguous.candidates) == 2
    assert resolved.status is RideReferenceResolutionStatus.RESOLVED
    assert resolved.ride is not None and resolved.ride.ride_id == station.id


@pytest.mark.asyncio
async def test_local_spoken_hour_and_numbered_follow_up_resolve_internal_ride(
    db_session: AsyncSession,
) -> None:
    owner = await customer(db_session, "Spoken Time Owner")
    service = RideService(db_session, RideRepository(db_session))
    ride_context = context(owner.id)
    six_pm = datetime.now(ZoneInfo("Asia/Kolkata")).replace(
        hour=18, minute=0, second=0, microsecond=0
    ).astimezone(UTC)
    expected = await ride(db_session, owner.id, "Kota Junction", six_pm)
    await complete_ride(db_session, expected.id)
    mall = await ride(db_session, owner.id, "City Mall", six_pm + timedelta(hours=2))
    await complete_ride(db_session, mall.id)

    by_time = await service.resolve_customer_ride_reference(
        owner.id, ride_context, reference="6 baje wali"
    )
    ambiguous = await service.resolve_customer_ride_reference(
        owner.id, ride_context
    )
    by_number = await service.resolve_customer_ride_reference(
        owner.id, ride_context, candidate_number=2
    )

    assert by_time.status is RideReferenceResolutionStatus.RESOLVED
    assert by_time.ride is not None and by_time.ride.ride_id == expected.id
    assert ambiguous.status is RideReferenceResolutionStatus.AMBIGUOUS
    assert by_number.status is RideReferenceResolutionStatus.RESOLVED
    assert by_number.ride is not None


@pytest.mark.asyncio
async def test_no_ride_and_other_customer_reference_never_resolve(
    db_session: AsyncSession,
) -> None:
    owner = await customer(db_session, "Empty Reference Owner")
    other = await customer(db_session, "Other Reference Owner")
    other_ride = await ride(
        db_session, other.id, "Secret Destination", datetime.now(UTC) + timedelta(hours=1)
    )
    service = RideService(db_session, RideRepository(db_session))

    empty = await service.resolve_customer_ride_reference(owner.id, context(owner.id))
    supplied_uuid = await service.resolve_customer_ride_reference(
        owner.id, context(owner.id), reference=str(other_ride.id)
    )

    assert empty.status is RideReferenceResolutionStatus.NOT_FOUND
    assert supplied_uuid.status is RideReferenceResolutionStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_cancellation_reference_only_considers_owned_cancellable_rides(
    db_session: AsyncSession,
) -> None:
    owner = await customer(db_session, "Cancellation Reference Owner")
    completed = await ride(
        db_session, owner.id, "Old Station", datetime.now(UTC) - timedelta(days=1)
    )
    await complete_ride(db_session, completed.id)
    expected = await ride(
        db_session, owner.id, "Kota Junction", datetime.now(UTC) + timedelta(hours=1)
    )
    repository = RideRepository(db_session)

    result = await RideService(
        db_session, repository
    ).resolve_customer_ride_reference(
        owner.id, context(owner.id), cancellable_only=True
    )

    assert result.status is RideReferenceResolutionStatus.RESOLVED
    assert result.ride is not None and result.ride.ride_id == expected.id
