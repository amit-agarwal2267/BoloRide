from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.ride import Ride
from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation
from boloride.domain.models.ride import validate_ride_transition


class RideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        user_id: UUID,
        pickup: ResolvedLocation,
        destination: ResolvedLocation,
        requested_ride_at: datetime,
    ) -> Ride:
        if pickup.latitude == destination.latitude and pickup.longitude == destination.longitude:
            raise DomainValidationError("pickup and destination must differ")
        if requested_ride_at.tzinfo is None:
            raise DomainValidationError("requested ride time must be timezone-aware")

        ride = Ride(
            user_id=user_id,
            pickup_address=pickup.address,
            pickup_display_name=pickup.display_name,
            pickup_latitude=pickup.latitude,
            pickup_longitude=pickup.longitude,
            pickup_provider=pickup.provider,
            pickup_provider_place_id=pickup.provider_place_id,
            destination_address=destination.address,
            destination_display_name=destination.display_name,
            destination_latitude=destination.latitude,
            destination_longitude=destination.longitude,
            destination_provider=destination.provider,
            destination_provider_place_id=destination.provider_place_id,
            requested_ride_at=requested_ride_at,
            status=RideStatus.REQUESTED,
        )
        self._session.add(ride)
        await self._session.flush()
        return ride

    async def get_by_id(self, ride_id: UUID, *, for_update: bool = False) -> Ride | None:
        statement = select(Ride).where(Ride.id == ride_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def list_for_user(self, user_id: UUID, *, limit: int = 5) -> list[Ride]:
        result = await self._session.scalars(
            select(Ride)
            .where(Ride.user_id == user_id)
            .order_by(Ride.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def confirm(self, ride_id: UUID) -> Ride | None:
        ride = await self.get_by_id(ride_id, for_update=True)
        if ride is None:
            return None
        validate_ride_transition(ride.status, RideStatus.CONFIRMED)
        ride.status = RideStatus.CONFIRMED
        ride.confirmed_at = datetime.now(UTC)
        await self._session.flush()
        return ride

    async def mark_booked(
        self,
        ride_id: UUID,
        *,
        provider: str,
        provider_booking_id: str,
        fare_amount: Decimal,
        fare_currency: str,
    ) -> Ride | None:
        ride = await self.get_by_id(ride_id, for_update=True)
        if ride is None:
            return None
        validate_ride_transition(ride.status, RideStatus.BOOKED)

        normalized_provider = provider.strip().casefold()
        normalized_booking_id = provider_booking_id.strip()
        normalized_currency = fare_currency.strip().upper()
        if not normalized_provider or not normalized_booking_id:
            raise DomainValidationError("provider booking details cannot be blank")
        if fare_amount <= 0:
            raise DomainValidationError("fare amount must be positive")
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise DomainValidationError("fare currency must be a three-letter code")

        ride.status = RideStatus.BOOKED
        ride.provider = normalized_provider
        ride.provider_booking_id = normalized_booking_id
        ride.booked_at = datetime.now(UTC)
        ride.fare_amount = fare_amount
        ride.fare_currency = normalized_currency
        await self._session.flush()
        return ride
