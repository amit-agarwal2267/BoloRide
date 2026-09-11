from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TimeResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    CLARIFICATION_REQUIRED = "clarification_required"


class RideTimingIntent(StrEnum):
    IMMEDIATE = "immediate"
    SCHEDULED = "scheduled"


@dataclass(frozen=True, slots=True)
class TimeResolutionResult:
    status: TimeResolutionStatus
    scheduled_at: datetime | None = None
    clarification_reason: str | None = None
    resolution_type: str | None = None
    timing_intent: RideTimingIntent | None = None
