import re
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from boloride.domain.models.scheduling import TimeResolutionResult, TimeResolutionStatus
from boloride.domain.models.scheduling import RideTimingIntent


_CLOCK = re.compile(r"(?<!\d)(1[0-2]|0?\d)(?::([0-5]\d))?\s*(am|pm)?(?!\w)", re.I)
_DAYPARTS = {
    "morning": "am", "subah": "am", "सुबह": "am",
    "afternoon": "pm", "dopahar": "pm", "दोपहर": "pm",
    "evening": "pm", "shaam": "pm", "शाम": "pm",
    "night": "pm", "raat": "pm", "रात": "pm",
}
_HINDI_NUMBER_WORDS = {
    "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5",
    "छह": "6", "सात": "7", "आठ": "8", "नौ": "9", "दस": "10",
    "ग्यारह": "11", "बारह": "12",
}
_RELATIVE_DELAY = re.compile(
    r"(?<!\d)(\d+)\s*(?:ghant(?:a|e)|hours?)\s*(?:baad|later)(?!\w)", re.I
)
_IMMEDIATE_WORDS = re.compile(r"(?:\b(?:abhi|now|immediately|asap)\b|अभी)", re.I)
_TOMORROW_MORNING = re.compile(
    r"(?:कल\s+सुबह|kal\s+subah|(?<!after\s)tomorrow\s+morning(?:\s+at)?)"
    r"\s+(1[0-2]|0?\d)(?::([0-5]\d))?(?:\s*(?:बजे|baje))?",
    re.I,
)
_TOMORROW_EXPLICIT_AM = re.compile(
    r"(?<!after\s)tomorrow\s+at\s+(1[0-2]|0?\d)(?::([0-5]\d))?\s*am\b",
    re.I,
)
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
        text = " ".join(_HINDI_NUMBER_WORDS.get(word, word) for word in text.split())
        logger.info("time_resolution_requested", extra={"event": "time_resolution_requested", "correction": correction})
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("time-resolution clock must be timezone-aware")

        local_now = now.astimezone(self._timezone)
        tomorrow_morning = _TOMORROW_MORNING.search(text)
        tomorrow_am = _TOMORROW_EXPLICIT_AM.search(text)
        explicit_tomorrow = tomorrow_morning or tomorrow_am
        if explicit_tomorrow is not None:
            hour = int(explicit_tomorrow.group(1))
            minute = int(explicit_tomorrow.group(2) or 0)
            if hour == 0 or hour > 12:
                return TimeResolutionResult(
                    TimeResolutionStatus.CLARIFICATION_REQUIRED,
                    clarification_reason="valid_12_hour_time_required",
                )
            date = local_now.date() + timedelta(days=1)
            scheduled_at = datetime(
                date.year,
                date.month,
                date.day,
                hour % 12,
                minute,
                tzinfo=self._timezone,
            )
            return TimeResolutionResult(
                TimeResolutionStatus.RESOLVED,
                scheduled_at.astimezone(UTC),
                resolution_type="relative_tomorrow_morning",
                timing_intent=RideTimingIntent.SCHEDULED,
            )

        if _IMMEDIATE_WORDS.search(text) or "as soon as possible" in text or text == "jaldi cab bhejo":
            return TimeResolutionResult(
                TimeResolutionStatus.RESOLVED,
                now.astimezone(UTC),
                resolution_type="immediate",
                timing_intent=RideTimingIntent.IMMEDIATE,
            )

        relative_delay = _RELATIVE_DELAY.search(text)
        if relative_delay is not None:
            scheduled_at = now + timedelta(hours=int(relative_delay.group(1)))
            return TimeResolutionResult(
                TimeResolutionStatus.RESOLVED,
                scheduled_at.astimezone(UTC),
                resolution_type="relative_delay",
                timing_intent=RideTimingIntent.SCHEDULED,
            )

        if "thodi der" in text:
            return TimeResolutionResult(
                TimeResolutionStatus.CLARIFICATION_REQUIRED,
                clarification_reason="approximate_time_required",
            )
        match = _CLOCK.search(text)
        if match is None:
            logger.info("time_clarification_required", extra={"event": "time_clarification_required", "reason": "specific_clock_time_required"})
            timing_intent = (
                RideTimingIntent.SCHEDULED
                if any(word in text.split() for word in (
                    "schedule", "scheduled", "aaj", "आज", "kal", "कल",
                    "parso", "परसों", "today", "tomorrow", "day",
                ))
                or any(word in text.split() for word in _DAYPARTS)
                else None
            )
            return TimeResolutionResult(
                TimeResolutionStatus.CLARIFICATION_REQUIRED,
                clarification_reason="specific_clock_time_required",
                timing_intent=timing_intent,
            )
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
        if "day after tomorrow" in text or any(
            word in text.split() for word in ("parso", "परसों")
        ):
            date = local_now.date() + timedelta(days=2)
            resolution_type = "relative_day_after_tomorrow"
        elif any(word in text.split() for word in ("tomorrow", "kal", "कल")):
            date = local_now.date() + timedelta(days=1)
            resolution_type = "relative_tomorrow"
        elif any(word in text.split() for word in ("today", "aaj", "आज")):
            date = local_now.date()
            resolution_type = "relative_today"
        elif correction and previous is not None:
            date = previous.astimezone(self._timezone).date()
            resolution_type = "correction"
        else:
            return TimeResolutionResult(TimeResolutionStatus.CLARIFICATION_REQUIRED, clarification_reason="date_required")
        local = datetime(date.year, date.month, date.day, hour, minute, tzinfo=self._timezone)
        return TimeResolutionResult(
            TimeResolutionStatus.RESOLVED,
            local.astimezone(UTC),
            resolution_type=resolution_type,
            timing_intent=RideTimingIntent.SCHEDULED,
        )
