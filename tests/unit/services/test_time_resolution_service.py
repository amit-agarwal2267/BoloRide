from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from boloride.domain.models.scheduling import RideTimingIntent, TimeResolutionStatus
from boloride.services.time_resolution_service import TimeResolutionService


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def service() -> TimeResolutionService:
    return TimeResolutionService(lambda: NOW)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("tomorrow 6:30 AM", datetime(2026, 9, 10, 1, 0, tzinfo=UTC)),
        ("kal subah 6:30", datetime(2026, 9, 10, 1, 0, tzinfo=UTC)),
        ("aaj 7:15 PM", datetime(2026, 9, 9, 13, 45, tzinfo=UTC)),
    ],
)
def test_resolves_bounded_phrases_to_aware_utc(service, phrase, expected):
    result = service.resolve(phrase)
    assert result.status is TimeResolutionStatus.RESOLVED
    assert result.scheduled_at == expected
    assert result.scheduled_at.tzinfo is UTC


@pytest.mark.parametrize("phrase", ["kal 6 baje", "raat ko", "thodi der mein"])
def test_ambiguous_or_vague_time_requires_clarification(service, phrase):
    assert service.resolve(phrase).status is TimeResolutionStatus.CLARIFICATION_REQUIRED


def test_correction_preserves_deterministic_date_and_daypart(service):
    first = service.resolve("tomorrow 7 PM").scheduled_at
    result = service.resolve("6:30", previous=first, correction=True)
    assert result.scheduled_at == datetime(2026, 9, 10, 13, 0, tzinfo=UTC)


def test_naive_clock_is_rejected():
    service = TimeResolutionService(lambda: datetime(2026, 9, 9, 12))
    with pytest.raises(ValueError, match="timezone-aware"):
        service.resolve("tomorrow 6 AM")


@pytest.mark.parametrize(
    "phrase", ["abhi", "abhi chahiye", "now", "immediately", "ASAP"]
)
def test_clear_immediate_phrases_use_authoritative_clock(service, phrase):
    result = service.resolve(phrase)
    assert result.status is TimeResolutionStatus.RESOLVED
    assert result.timing_intent is RideTimingIntent.IMMEDIATE
    assert result.scheduled_at == NOW


def test_relative_hour_is_scheduled_from_authoritative_clock(service):
    result = service.resolve("1 ghante baad")
    assert result.status is TimeResolutionStatus.RESOLVED
    assert result.timing_intent is RideTimingIntent.SCHEDULED
    assert result.scheduled_at == datetime(2026, 9, 9, 13, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("phrase", "reason", "intent"),
    [
        ("thodi der mein", "approximate_time_required", None),
        ("aaj shaam", "specific_clock_time_required", RideTimingIntent.SCHEDULED),
        ("schedule karni hai", "specific_clock_time_required", RideTimingIntent.SCHEDULED),
    ],
)
def test_incomplete_timing_intent_requires_specificity(service, phrase, reason, intent):
    result = service.resolve(phrase)
    assert result.status is TimeResolutionStatus.CLARIFICATION_REQUIRED
    assert result.clarification_reason == reason
    assert result.timing_intent is intent


def test_explicit_clock_time_is_scheduled(service):
    result = service.resolve("tomorrow 6:30 AM")
    assert result.timing_intent is RideTimingIntent.SCHEDULED


IST = ZoneInfo("Asia/Kolkata")
DEMO_NOW = datetime(2026, 9, 16, 14, 0, tzinfo=IST)


@pytest.mark.parametrize(
    ("phrase", "expected_local"),
    [
        ("कल सुबह 8 बजे", datetime(2026, 9, 17, 8, 0, tzinfo=IST)),
        ("कल सुबह आठ बजे", datetime(2026, 9, 17, 8, 0, tzinfo=IST)),
        ("kal subah 8 baje", datetime(2026, 9, 17, 8, 0, tzinfo=IST)),
        ("tomorrow at 8 AM", datetime(2026, 9, 17, 8, 0, tzinfo=IST)),
        ("कल शाम 6 बजे", datetime(2026, 9, 17, 18, 0, tzinfo=IST)),
        ("आज शाम 6 बजे", datetime(2026, 9, 16, 18, 0, tzinfo=IST)),
        ("परसों दोपहर 2 बजे", datetime(2026, 9, 18, 14, 0, tzinfo=IST)),
        ("day after tomorrow at 8 AM", datetime(2026, 9, 18, 8, 0, tzinfo=IST)),
    ],
)
def test_demo_relative_day_and_daypart_phrases(phrase, expected_local):
    result = TimeResolutionService(lambda: DEMO_NOW).resolve(phrase)
    assert result.status is TimeResolutionStatus.RESOLVED
    assert result.scheduled_at.astimezone(IST) == expected_local


@pytest.mark.parametrize("phrase", ["अभी", "abhi", "now", "अभी जाना है", "I need a cab now"])
def test_demo_immediate_phrases_use_trusted_ist_clock(phrase):
    result = TimeResolutionService(lambda: DEMO_NOW).resolve(phrase)
    assert result.status is TimeResolutionStatus.RESOLVED
    assert result.timing_intent is RideTimingIntent.IMMEDIATE
    assert result.scheduled_at == DEMO_NOW.astimezone(UTC)


def test_time_only_correction_preserves_previously_resolved_date_and_daypart():
    service = TimeResolutionService(lambda: DEMO_NOW)
    initial = service.resolve("कल सुबह 8 बजे")
    corrected = service.resolve("8:30 कर दो", previous=initial.scheduled_at, correction=True)
    assert corrected.status is TimeResolutionStatus.RESOLVED
    assert corrected.scheduled_at.astimezone(IST) == datetime(2026, 9, 17, 8, 30, tzinfo=IST)


def test_tomorrow_rolls_over_to_next_year():
    year_end = datetime(2026, 12, 31, 14, 0, tzinfo=IST)
    result = TimeResolutionService(lambda: year_end).resolve("कल सुबह 8 बजे")
    assert result.scheduled_at.astimezone(IST) == datetime(2027, 1, 1, 8, 0, tzinfo=IST)
