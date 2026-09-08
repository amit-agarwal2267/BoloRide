from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.ride import Ride
from boloride.domain.enums import RideStatus
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation
from boloride.domain.models.ride import validate_ride_transition


class RideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_booked(
        self,
        ride_id: UUID,
        user_id: UUID,
        pickup: ResolvedLocation,
        destination: ResolvedLocation,
        requested_ride_at: datetime,
        *,
        provider: str,
        provider_booking_id: str,
        fare_amount: Decimal,
        fare_currency: str,
    ) -> Ride:
        if pickup.latitude == destination.latitude and pickup.longitude == destination.longitude:
            raise DomainValidationError("pickup and destination must differ")
        if requested_ride_at.tzinfo is None:
            raise DomainValidationError("requested ride time must be timezone-aware")

        normalized_provider = provider.strip().casefold()
        normalized_booking_id = provider_booking_id.strip()
        normalized_currency = fare_currency.strip().upper()
        if not normalized_provider or not normalized_booking_id:
            raise DomainValidationError("provider booking details cannot be blank")
        if fare_amount <= 0:
            raise DomainValidationError("fare amount must be positive")
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise DomainValidationError("fare currency must be a three-letter code")

        now = datetime.now(UTC)
        ride = Ride(
            id=ride_id,
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
            status=RideStatus.BOOKED,
            confirmed_at=now,
            provider=normalized_provider,
            provider_booking_id=normalized_booking_id,
            booked_at=now,
            fare_amount=fare_amount,
            fare_currency=normalized_currency,
        )
        self._session.add(ride)
        await self._session.flush()
        return ride

    async def get_by_id_internal(
        self, ride_id: UUID, *, for_update: bool = False
    ) -> Ride | None:
        """Internal lookup; caller-facing services must use customer-scoped APIs."""
        statement = select(Ride).where(Ride.id == ride_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_for_customer(self, customer_id: UUID, ride_id: UUID) -> Ride | None:
        return await self._session.scalar(
            select(Ride).where(Ride.id == ride_id, Ride.user_id == customer_id)
        )

    async def list_for_customer(
        self, customer_id: UUID, *, limit: int = 5
    ) -> list[Ride]:
        result = await self._session.scalars(
            select(Ride)
            .where(Ride.user_id == customer_id)
            .order_by(Ride.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def transition_internal(
        self,
        ride_id: UUID,
        *,
        expected_status: RideStatus,
        requested_status: RideStatus,
    ) -> Ride | None:
        return await self._transition(
            ride_id,
            expected_status=expected_status,
            requested_status=requested_status,
        )

    async def transition_for_customer(
        self,
        customer_id: UUID,
        ride_id: UUID,
        *,
        expected_status: RideStatus,
        requested_status: RideStatus,
    ) -> Ride | None:
        return await self._transition(
            ride_id,
            customer_id=customer_id,
            expected_status=expected_status,
            requested_status=requested_status,
        )

    async def _transition(
        self,
        ride_id: UUID,
        *,
        expected_status: RideStatus,
        requested_status: RideStatus,
        customer_id: UUID | None = None,
    ) -> Ride | None:
        validate_ride_transition(expected_status, requested_status)
        conditions = [Ride.id == ride_id, Ride.status == expected_status]
        if customer_id is not None:
            conditions.append(Ride.user_id == customer_id)
        result = await self._session.execute(
            update(Ride)
            .where(*conditions)
            .values(status=requested_status)
            .returning(Ride)
        )
        return result.scalar_one_or_none()
