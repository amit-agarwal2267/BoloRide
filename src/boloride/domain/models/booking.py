from dataclasses import dataclass
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
    IN_PROGRESS = "in_progress"
    REQUOTE_REQUIRED = "requote_required"


@dataclass(frozen=True, slots=True)
class BookingOutcome:
    status: BookingResultStatus
    ride: object | None = None
    provider_result: object | None = None
    accepted_quote: object | None = None
