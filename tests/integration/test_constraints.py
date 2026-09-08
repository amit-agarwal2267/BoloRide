from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.ride import Ride
from boloride.domain.enums import RideStatus
from boloride.domain.models.location import ResolvedLocation
from boloride.repositories.saved_place_repository import SavedPlaceRepository
from boloride.repositories.user_repository import UserRepository


@pytest.mark.asyncio
async def test_duplicate_normalized_phone_is_rejected(db_session: AsyncSession) -> None:
    repository = UserRepository(db_session)
    await repository.create("9876543220")
    with pytest.raises(IntegrityError):
        await repository.create("+919876543220")


@pytest.mark.asyncio
async def test_duplicate_label_for_same_user_is_rejected(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).create("9876543221")
    repository = SavedPlaceRepository(db_session)
    location = ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83"))
    await repository.create(user.id, "Home", location)
    with pytest.raises(IntegrityError):
        await repository.create(user.id, " HOME ", location)


@pytest.mark.asyncio
async def test_same_label_is_allowed_for_different_users(db_session: AsyncSession) -> None:
    users = UserRepository(db_session)
    first = await users.create("9876543222")
    second = await users.create("9876543223")
    places = SavedPlaceRepository(db_session)
    location = ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83"))
    await places.create(first.id, "home", location)
    await places.create(second.id, "home", location)


@pytest.mark.asyncio
async def test_booked_status_requires_booking_fields(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).create("9876543224")
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
