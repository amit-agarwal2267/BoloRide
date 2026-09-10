from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.ride import Ride
from boloride.db.models.user import User
from boloride.domain.enums import RideStatus
from boloride.domain.models.location import ResolvedLocation
from boloride.repositories.saved_place_repository import SavedPlaceRepository
from boloride.repositories.user_repository import UserRepository


@pytest.mark.asyncio
async def test_duplicate_normalized_phone_is_rejected(db_session: AsyncSession) -> None:
    repository = UserRepository(db_session)
    await repository.create("9876543220", "First User", 30)
    with pytest.raises(IntegrityError):
        await repository.create("+919876543220", "Second User", 31)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "normalized_name", "age"),
    [
        ("\t", "valid name", 30),
        ("Valid Name", "", 30),
        ("Valid Name", "valid name", 0),
        ("Valid Name", "valid name", 121),
    ],
)
async def test_complete_customer_profile_constraints(
    db_session: AsyncSession, name: str, normalized_name: str, age: int
) -> None:
    db_session.add(
        User(
            phone_number="+919876543225",
            name=name,
            normalized_name=normalized_name,
            age=age,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_duplicate_label_for_same_user_is_rejected(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).create("9876543221", "First User", 30)
    repository = SavedPlaceRepository(db_session)
    location = ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83"))
    await repository.create(user.id, "Home", location)
    with pytest.raises(IntegrityError):
        await repository.create(user.id, " HOME ", location)


@pytest.mark.asyncio
async def test_same_label_is_allowed_for_different_users(db_session: AsyncSession) -> None:
    users = UserRepository(db_session)
    first = await users.create("9876543222", "First User", 30)
    second = await users.create("9876543223", "Second User", 31)
    places = SavedPlaceRepository(db_session)
    location = ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83"))
    await places.create(first.id, "home", location)
    await places.create(second.id, "home", location)


@pytest.mark.asyncio
async def test_booked_status_requires_booking_fields(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).create("9876543224", "First User", 30)
    invalid_ride = Ride(
        user_id=user.id,
        pickup_address="Home",
        pickup_latitude=Decimal("25.18"),
        pickup_longitude=Decimal("75.83"),
        destination_address="Station",
        destination_latitude=Decimal("25.22"),
        destination_longitude=Decimal("75.88"),
        requested_ride_at=datetime.now(UTC) + timedelta(hours=1),
        status=RideStatus.BOOKED,
    )
    db_session.add(invalid_ride)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_invalid_ride_status_cannot_be_persisted(
    db_session: AsyncSession,
) -> None:
    user = await UserRepository(db_session).create("9876543225", "First User", 30)
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO rides "
                "(user_id, pickup_address, pickup_latitude, pickup_longitude, "
                "destination_address, destination_latitude, destination_longitude, "
                "requested_ride_at, status, confirmed_at, provider, "
                "provider_booking_id, booked_at, fare_amount, fare_currency) VALUES "
                "(:user_id, 'Home', 25.18, 75.83, 'Station', 25.22, 75.88, "
                "now(), 'unknown', now(), 'mock', 'invalid-status', now(), 100, 'INR')"
            ),
            {"user_id": user.id},
        )


@pytest.mark.asyncio
async def test_database_prevents_two_active_rides_for_one_customer(
    db_session: AsyncSession,
) -> None:
    user = await UserRepository(db_session).create(
        "9876543226", "Single Active Rider", 30
    )

    def active_ride(provider_booking_id: str) -> Ride:
        now = datetime.now(UTC)
        return Ride(
            user_id=user.id,
            pickup_address="Home",
            pickup_latitude=Decimal("25.18"),
            pickup_longitude=Decimal("75.83"),
            destination_address="Station",
            destination_latitude=Decimal("25.22"),
            destination_longitude=Decimal("75.88"),
            requested_ride_at=now + timedelta(hours=1),
            status=RideStatus.BOOKED,
            confirmed_at=now,
            provider="mock",
            provider_booking_id=provider_booking_id,
            booked_at=now,
            fare_amount=Decimal("100.00"),
            fare_currency="INR",
        )

    db_session.add(active_ride("single-active-one"))
    await db_session.flush()
    db_session.add(active_ride("single-active-two"))

    with pytest.raises(IntegrityError):
        await db_session.flush()
