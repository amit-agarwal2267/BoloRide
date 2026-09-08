from decimal import Decimal

from boloride.integrations.rideprovider.base import (
	RideBookingRequest,
	RideBookingResult,
)


class MockRideProvider:
	provider_name = "mock"

	async def create_booking(self, request: RideBookingRequest) -> RideBookingResult:
		return RideBookingResult(
			provider=self.provider_name,
			provider_booking_id=f"mock-{request.request_id}",
			fare_amount=Decimal("245.50"),
			fare_currency="INR",
			driver_name="Amit Kumar",
			vehicle_description="White Maruti Dzire, RJ 20 AB 1234",
		)
