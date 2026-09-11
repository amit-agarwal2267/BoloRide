from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
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
	pickup_instructions: str | None = None


@dataclass(frozen=True, slots=True)
class RideBookingResult:
	provider: str
	provider_booking_id: str
	driver_name: str
	vehicle_description: str


class ProviderCreateStatus(StrEnum):
	CONFIRMED = "confirmed"
	REJECTED = "rejected"
	UNKNOWN = "unknown"


class ProviderReconciliationStatus(StrEnum):
	CONFIRMED = "confirmed"
	DEFINITIVELY_ABSENT = "definitively_absent"
	UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProviderCreateOutcome:
	status: ProviderCreateStatus
	booking: RideBookingResult | None = None
	failure_category: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderReconciliationOutcome:
	status: ProviderReconciliationStatus
	booking: RideBookingResult | None = None
	failure_category: str | None = None


class RideProvider(Protocol):
	provider_name: str
	supports_safe_retry_after_definitive_absence: bool

	async def create_booking(
		self, request: RideBookingRequest, *, idempotency_key: str
	) -> ProviderCreateOutcome: ...

	async def reconcile_booking(
		self, idempotency_key: str
	) -> ProviderReconciliationOutcome: ...
