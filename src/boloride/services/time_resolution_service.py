import re
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from boloride.domain.models.scheduling import TimeResolutionResult, TimeResolutionStatus


_CLOCK = re.compile(r"(?<!\d)(1[0-2]|0?\d)(?::([0-5]\d))?\s*(am|pm)?(?!\w)", re.I)
_DAYPARTS = {
    "morning": "am", "subah": "am",
    "afternoon": "pm", "evening": "pm", "shaam": "pm", "night": "pm", "raat": "pm",
}
logger = logging.getLogger(__name__)


class TimeResolutionService:
    def __init__(self, clock: Callable[[], datetime], timezone: str = "Asia/Kolkata") -> None:
        self._clock = clock
        self._timezone = ZoneInfo(timezone)

    def resolve(
        self,
        phrase: str,
        *,
        previous: datetime | None = None,
        correction: bool = False,
    ) -> TimeResolutionResult:
        text = " ".join(phrase.casefold().split())
        logger.info("time_resolution_requested", extra={"event": "time_resolution_requested", "correction": correction})
        match = _CLOCK.search(text)
        if match is None:
            logger.info("time_clarification_required", extra={"event": "time_clarification_required", "reason": "specific_clock_time_required"})
            return TimeResolutionResult(TimeResolutionStatus.CLARIFICATION_REQUIRED, clarification_reason="specific_clock_time_required")
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        marker = match.group(3)
        daypart = next((value for word, value in _DAYPARTS.items() if word in text.split()), None)
        marker = marker or daypart
        if marker is None and correction and previous is not None:
            marker = "pm" if previous.astimezone(self._timezone).hour >= 12 else "am"
        if marker is None:
            logger.info("time_clarification_required", extra={"event": "time_clarification_required", "reason": "am_or_pm_required"})
            return TimeResolutionResult(TimeResolutionStatus.CLARIFICATION_REQUIRED, clarification_reason="am_or_pm_required")
        if hour == 0 or hour > 12:
            return TimeResolutionResult(TimeResolutionStatus.CLARIFICATION_REQUIRED, clarification_reason="valid_12_hour_time_required")
        hour = hour % 12 + (12 if marker == "pm" else 0)
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("time-resolution clock must be timezone-aware")
        local_now = now.astimezone(self._timezone)
        if any(word in text.split() for word in ("tomorrow", "kal")):
            date = local_now.date() + timedelta(days=1)
            resolution_type = "relative_tomorrow"
        elif any(word in text.split() for word in ("today", "aaj")):
            date = local_now.date()
            resolution_type = "relative_today"
        elif correction and previous is not None:
            date = previous.astimezone(self._timezone).date()
            resolution_type = "correction"
        else:
            return TimeResolutionResult(TimeResolutionStatus.CLARIFICATION_REQUIRED, clarification_reason="date_required")
        local = datetime(date.year, date.month, date.day, hour, minute, tzinfo=self._timezone)
        return TimeResolutionResult(TimeResolutionStatus.RESOLVED, local.astimezone(UTC), resolution_type=resolution_type)
