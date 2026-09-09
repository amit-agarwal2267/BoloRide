from uuid import UUID

from boloride.db.models.ride import Ride
from boloride.domain.enums import RideStatus
from boloride.repositories.ride_repository import RideRepository
from boloride.services.offer_service import OfferService


class RideService:
    """Customer-owned ride retrieval and deterministic lifecycle operations."""

    def __init__(self, rides: RideRepository, offers: OfferService | None = None) -> None:
        self._rides = rides
        self._offers = offers

    async def get_customer_ride(
        self, customer_id: UUID, ride_id: UUID
    ) -> Ride | None:
        return await self._rides.get_for_customer(customer_id, ride_id)

    async def list_customer_rides(
        self, customer_id: UUID, *, limit: int = 5
    ) -> list[Ride]:
        return await self._rides.list_for_customer(customer_id, limit=limit)

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
