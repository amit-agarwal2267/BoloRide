from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from boloride.domain.models.location import ResolvedLocation


@dataclass(frozen=True, slots=True)
class RideBookingRequest:
	request_id: UUID
	pickup: ResolvedLocation
	destination: ResolvedLocation
	requested_ride_at: datetime
	passenger_count: int
	vehicle_type_code: str


@dataclass(frozen=True, slots=True)
class RideBookingResult:
	provider: str
	provider_booking_id: str
	driver_name: str
	vehicle_description: str


class RideProvider(Protocol):
	async def create_booking(self, request: RideBookingRequest) -> RideBookingResult:
		...
