from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

class BookingAttemptState(StrEnum):
    READY = "ready"
    PROVIDER_CALLING = "provider_calling"
    PROVIDER_CONFIRMED = "provider_confirmed"
    FINALIZED = "finalized"
    DEFINITIVELY_FAILED = "definitively_failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    REQUOTE_REQUIRED = "requote_required"


class BookingResultStatus(StrEnum):
    SUCCESS = "success"
    IDEMPOTENT_SUCCESS = "idempotent_success"
    DEFINITIVE_FAILURE = "definitive_failure"
    OUTCOME_UNKNOWN = "outcome_unknown"
    RECONCILIATION_PENDING = "reconciliation_pending"
    IN_PROGRESS = "in_progress"
    REQUOTE_REQUIRED = "requote_required"
    ACTIVE_RIDE_EXISTS = "active_ride_exists"


@dataclass(frozen=True, slots=True)
class ActiveRideSummary:
    status: str
    pickup: str
    destination: str
    requested_ride_at: datetime
    vehicle_type_code: str | None


@dataclass(frozen=True, slots=True)
class BookingOutcome:
    status: BookingResultStatus
    ride: object | None = None
    provider_result: object | None = None
    accepted_quote: object | None = None
    active_ride: ActiveRideSummary | None = None
