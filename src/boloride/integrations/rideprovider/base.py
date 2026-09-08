from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from boloride.domain.models.location import ResolvedLocation


@dataclass(frozen=True, slots=True)
class RideBookingRequest:
	request_id: UUID
	pickup: ResolvedLocation
	destination: ResolvedLocation
	requested_ride_at: datetime
	ride_type: str = "standard"


@dataclass(frozen=True, slots=True)
class RideBookingResult:
	provider: str
	provider_booking_id: str
	fare_amount: Decimal
	fare_currency: str
	driver_name: str
	vehicle_description: str


class RideProvider(Protocol):
	async def create_booking(self, request: RideBookingRequest) -> RideBookingResult:
		...
