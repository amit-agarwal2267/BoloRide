import asyncio
import json
import logging
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import Mock

from boloride.config import Settings
from boloride.integrations.langfuse.client import LangfuseClient
from boloride.integrations.langfuse.tracing import LangfuseTracer
from boloride.observability.logger import JsonFormatter
from boloride.observability.tracing import (
    ObservabilityContext,
    SessionOutcome,
    VoiceSessionMetadata,
    get_observability_context,
)


class FakeObservation:
    def __init__(self) -> None:
        self.children: list[tuple[str, str, dict | None]] = []
        self.updates: list[dict | None] = []
        self.end_count = 0

    def update(self, *, output=None, metadata=None) -> None:
        self.updates.append(metadata)

    def end(self) -> None:
        self.end_count += 1

    @contextmanager
    def observe(
        self, name: str, *, observation_type: str = "span", metadata=None
    ) -> Iterator["FakeObservation"]:
        self.children.append((name, observation_type, metadata))
        child = FakeObservation()
        yield child
        child.end()


class FakeTracer:
    def __init__(self) -> None:
        self.root = FakeObservation()
        self.starts: list[tuple[str, str, dict]] = []

    def start_session_trace(self, name, *, correlation_id, metadata):
        self.starts.append((name, correlation_id, metadata))
        return f"trace-{correlation_id}", self.root

    @contextmanager
    def observe(self, *args, **kwargs):
        yield FakeObservation()


def metadata() -> VoiceSessionMetadata:
    return VoiceSessionMetadata(
        persona_id="staff-aditi",
        persona_gender="female",
        interaction_mode="text",
        stt_provider="disabled",
        maps_provider="ola",
        tts_provider="edge",
        prompt_source="fallback",
        environment="test",
    )


def test_one_session_starts_one_root_and_finalizes_exactly_once() -> None:
    tracer = FakeTracer()
    context = ObservabilityContext.start_voice_session(
        tracer, session_id="session-one", metadata=metadata()
    )

    context.set_outcome(SessionOutcome.BOOKED)
    context.finalize(SessionOutcome.ABANDONED)
    context.finalize(SessionOutcome.FAILED)

    assert len(tracer.starts) == 1
    assert tracer.starts[0][0] == "boloride.voice_session"
    assert len(tracer.root.updates) == 1
    assert tracer.root.updates[0]["session_outcome"] == "booked"
    assert tracer.root.updates[0]["funnel_highest_stage"] == "SESSION_STARTED"
    assert tracer.root.end_count == 1


def test_booked_then_cancelled_keeps_booking_funnel_and_cancelled_outcome() -> None:
    tracer = FakeTracer()
    context = ObservabilityContext.start_voice_session(
        tracer, session_id="session-cancelled", metadata=metadata()
    )
    from boloride.observability.session_metrics import FunnelMilestone

    context.mark_milestone(FunnelMilestone.BOOKED)
    context.mark_milestone(FunnelMilestone.CANCELLED)
    context.set_outcome(SessionOutcome.BOOKED)
    context.set_outcome(SessionOutcome.CANCELLED)
    context.finalize(SessionOutcome.ABANDONED)

    summary = tracer.root.updates[0]
    assert summary["session_outcome"] == "cancelled"
    assert summary["funnel_highest_stage"] == "BOOKED"
    assert "CANCELLED" in summary["funnel_milestones"]


def test_child_span_is_bound_to_its_session_root() -> None:
    tracer = FakeTracer()
    context = ObservabilityContext.start_voice_session(
        tracer, session_id="session-child", metadata=metadata()
    )

    with context.observe(
        "tool.location_search",
        observation_type="tool",
        metadata={"provider": "ola"},
    ):
        pass

    assert tracer.root.children == [
        ("tool.location_search", "tool", {"provider": "ola"})
    ]


def test_session_metadata_has_a_closed_non_pii_shape() -> None:
    tracer = FakeTracer()
    ObservabilityContext.start_voice_session(
        tracer, session_id="session-private", metadata=metadata()
    )

    root_metadata = tracer.starts[0][2]
    assert set(root_metadata) == {
        "session_id",
        "persona_id",
        "persona_gender",
        "interaction_mode",
        "stt_provider",
        "maps_provider",
        "tts_provider",
        "prompt_source",
        "environment",
    }
    assert not {"phone", "name", "address", "transcript", "pickup_instructions"}.intersection(root_metadata)


def test_concurrent_sessions_keep_context_isolated() -> None:
    async def observe(session_id: str) -> tuple[str, str]:
        context = ObservabilityContext.start_voice_session(
            FakeTracer(), session_id=session_id, metadata=metadata()
        )
        with context.activate():
            await asyncio.sleep(0)
            current = get_observability_context()
            assert current is not None
            return current.session_id, current.trace_id

    async def run_both() -> list[tuple[str, str]]:
        return list(
            await asyncio.gather(observe("session-a"), observe("session-b"))
        )

    results = asyncio.run(run_both())
    assert results == [
        ("session-a", "trace-session-a"),
        ("session-b", "trace-session-b"),
    ]
    assert get_observability_context() is None


def test_disabled_and_failed_langfuse_are_safe_noops() -> None:
    disabled = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@postgres/db",
        langfuse_enabled=False,
    )
    context = ObservabilityContext.start_voice_session(
        LangfuseTracer(LangfuseClient(disabled)),
        session_id="disabled",
        metadata=metadata(),
    )
    with context.observe("tool.booking"):
        pass
    context.finalize(SessionOutcome.COMPLETED)

    enabled = disabled.model_copy(
        update={
            "langfuse_enabled": True,
            "langfuse_public_key": "public",
            "langfuse_secret_key": "secret",
        }
    )
    sdk = Mock()
    sdk.create_trace_id.side_effect = ConnectionError("offline")
    failed = ObservabilityContext.start_voice_session(
        LangfuseTracer(LangfuseClient(enabled, sdk_client=sdk)),
        session_id="unavailable",
        metadata=metadata(),
    )
    failed.finalize(SessionOutcome.ABANDONED)


def test_structured_log_keeps_trace_and_session_correlation() -> None:
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "voice_session_started", (), None
    )
    record.event = "voice_session_started"
    record.session_id = "session-log"
    record.trace_id = "trace-log"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["session_id"] == "session-log"
    assert payload["trace_id"] == "trace-log"
