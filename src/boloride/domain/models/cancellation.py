from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from boloride.domain.enums import RideStatus


class CancellationResultStatus(StrEnum):
    SUCCESS = "success"
    IDEMPOTENT_SUCCESS = "idempotent_success"
    CONFIRMATION_REQUIRED = "confirmation_required"
    NOT_FOUND = "not_found"
    NOT_CANCELLABLE = "not_cancellable"
    RACE_LOST = "race_lost"


class RideReferenceResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    RESOLVED_SET = "resolved_set"


@dataclass(frozen=True, slots=True)
class RideStatusDetails:
    ride_id: UUID
    status: RideStatus
    pickup: str
    destination: str
    requested_ride_at: datetime
    vehicle_type_code: str | None
    estimated_fare: Decimal
    currency: str
    final_customer_cost: Decimal | None
    driver_display_name: str | None = None
    vehicle_registration: str | None = None
    vehicle_display_name: str | None = None


@dataclass(frozen=True, slots=True)
class CancellationResult:
    status: CancellationResultStatus
    ride: RideStatusDetails | None = None


@dataclass(frozen=True, slots=True)
class CancellationSetResult:
    results: tuple[CancellationResult, ...]


@dataclass(frozen=True, slots=True)
class RideReferenceResolution:
    status: RideReferenceResolutionStatus
    ride: RideStatusDetails | None = None
    candidates: tuple[RideStatusDetails, ...] = ()
