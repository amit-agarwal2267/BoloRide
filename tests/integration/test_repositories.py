from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.domain.enums import RideStatus
from boloride.domain.models.location import ResolvedLocation
from boloride.repositories.ride_repository import RideRepository
from boloride.repositories.saved_place_repository import SavedPlaceRepository
from boloride.repositories.user_repository import UserRepository
from boloride.services.ride_service import RideService


def location(address: str, latitude: str, longitude: str) -> ResolvedLocation:
    return ResolvedLocation(address, Decimal(latitude), Decimal(longitude))


@pytest.mark.asyncio
async def test_user_and_saved_place_repositories(db_session: AsyncSession) -> None:
    users = UserRepository(db_session)
    places = SavedPlaceRepository(db_session)
    user = await users.create("98765 43210", "Test User", 30)
    home = await places.create(
        user.id, " HOME ", location("Original home address", "25.180000", "75.830000")
    )

    assert (await users.get_by_phone("+919876543210")).id == user.id
    assert (await places.get_by_user_and_label(user.id, "home")).id == home.id
    assert [place.id for place in await places.list_for_user(user.id)] == [home.id]


@pytest.mark.asyncio
async def test_ride_repository_lifecycle(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).create("9876543211", "Test User", 30)
    rides = RideRepository(db_session)
    ride = await rides.create_booked(
        uuid4(),
        user.id,
        location("Home", "25.180000", "75.830000"),
        location("Kota Junction", "25.223000", "75.880000"),
        datetime.now(UTC) + timedelta(hours=1),
        provider=" MOCK ",
        provider_booking_id="booking-001",
        fare_amount=Decimal("245.50"),
        fare_currency="inr",
    )

    assert ride.status is RideStatus.BOOKED
    assert (await rides.get_by_id_internal(ride.id)).id == ride.id
    assert ride.confirmed_at is not None
    assert ride.provider == "mock"
    assert ride.fare_currency == "INR"

    assigned = await rides.transition_internal(
        ride.id,
        expected_status=RideStatus.BOOKED,
        requested_status=RideStatus.ASSIGNED,
    )
    assert assigned is not None
    assert assigned.status is RideStatus.ASSIGNED

    stale_transition = await rides.transition_internal(
        ride.id,
        expected_status=RideStatus.BOOKED,
        requested_status=RideStatus.CANCELLED,
    )
    assert stale_transition is None


@pytest.mark.asyncio
async def test_customer_scoped_ride_access_and_transition(
    db_session: AsyncSession,
) -> None:
    users = UserRepository(db_session)
    owner = await users.create("9876543215", "Owner", 30)
    other = await users.create("9876543216", "Other", 31)
    rides = RideRepository(db_session)
    service = RideService(rides)
    ride = await rides.create_booked(
        uuid4(),
        owner.id,
        location("Home", "25.180000", "75.830000"),
        location("Station", "25.223000", "75.880000"),
        datetime.now(UTC) + timedelta(hours=1),
        provider="mock",
        provider_booking_id="booking-owned",
        fare_amount=Decimal("200"),
        fare_currency="INR",
    )

    assert (await service.get_customer_ride(owner.id, ride.id)).id == ride.id
    assert await service.get_customer_ride(other.id, ride.id) is None
    assert [item.id for item in await service.list_customer_rides(owner.id)] == [ride.id]
    assert await service.list_customer_rides(other.id) == []
    assert (
        await service.transition_customer_ride(
            other.id,
            ride.id,
            expected_status=RideStatus.BOOKED,
            requested_status=RideStatus.CANCELLED,
        )
        is None
    )
    await db_session.refresh(ride)
    assert ride.status is RideStatus.BOOKED


@pytest.mark.asyncio
async def test_ride_preserves_saved_place_snapshot(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).create("9876543212", "Test User", 30)
    places = SavedPlaceRepository(db_session)
    saved_place = await places.create(
        user.id, "home", location("Old home", "25.180000", "75.830000")
    )
    ride = await RideRepository(db_session).create_booked(
        uuid4(),
        user.id,
        location(saved_place.address, str(saved_place.latitude), str(saved_place.longitude)),
        location("Station", "25.223000", "75.880000"),
        datetime.now(UTC) + timedelta(hours=1),
        provider="mock",
        provider_booking_id="booking-snapshot",
        fare_amount=Decimal("200"),
        fare_currency="INR",
    )

    saved_place.address = "New home"
    saved_place.latitude = Decimal("25.190000")
    await db_session.flush()
    await db_session.refresh(ride)

    assert ride.pickup_address == "Old home"
    assert ride.pickup_latitude == Decimal("25.180000")


@pytest.mark.asyncio
async def test_location_provenance_is_optional_and_preserved(
    db_session: AsyncSession,
) -> None:
    user = await UserRepository(db_session).create("9876543213", "Test User", 30)
    source_location = ResolvedLocation(
        "Kota Junction, Kota",
        Decimal("25.223000"),
        Decimal("75.880000"),
        display_name="Kota Junction",
        provider="Map Provider A",
        provider_place_id="place-123",
    )
    saved_place = await SavedPlaceRepository(db_session).create(
        user.id, "station", source_location
    )
    ride = await RideRepository(db_session).create_booked(
        uuid4(),
        user.id,
        source_location,
        location("Home", "25.180000", "75.830000"),
        datetime.now(UTC) + timedelta(hours=1),
        provider="mock",
        provider_booking_id="booking-provenance",
        fare_amount=Decimal("200"),
        fare_currency="INR",
    )

    assert saved_place.display_name == "Kota Junction"
    assert saved_place.provider == "map provider a"
    assert saved_place.provider_place_id == "place-123"
    assert ride.pickup_display_name == "Kota Junction"
    assert ride.pickup_provider == "map provider a"
    assert ride.pickup_provider_place_id == "place-123"
