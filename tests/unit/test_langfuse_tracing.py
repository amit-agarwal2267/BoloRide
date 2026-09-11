from contextlib import nullcontext
from unittest.mock import Mock

from boloride.config import Settings
from boloride.integrations.langfuse.client import LangfuseClient
from boloride.integrations.langfuse.tracing import LangfuseTracer, TraceObservation


def settings(*, enabled: bool) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@postgres/db",
        langfuse_enabled=enabled,
        langfuse_public_key="public" if enabled else None,
        langfuse_secret_key="secret" if enabled else None,
    )


def test_tracer_wraps_sdk_without_exposing_its_observation() -> None:
    native_observation = Mock()
    sdk = Mock()
    sdk.start_as_current_observation.return_value = nullcontext(native_observation)
    tracer = LangfuseTracer(
        LangfuseClient(settings(enabled=True), sdk_client=sdk)
    )

    with tracer.observe(
        "voice_session", correlation_id="session-123", metadata={"channel": "test"}
    ) as observation:
        assert isinstance(observation, TraceObservation)
        observation.update(output={"status": "complete"})

    sdk.start_as_current_observation.assert_called_once_with(
        name="voice_session",
        as_type="span",
        input=None,
        metadata={"channel": "test"},
    )
    native_observation.update.assert_called_once_with(
        output={"status": "complete"}, metadata=None
    )


def test_disabled_tracer_is_a_safe_noop() -> None:
    tracer = LangfuseTracer(LangfuseClient(settings(enabled=False)))
    with tracer.observe("voice_session", correlation_id="session-123") as observation:
        observation.update(output="ignored")


def test_tracing_setup_failure_does_not_break_wrapped_operation() -> None:
    sdk = Mock()
    sdk.start_as_current_observation.side_effect = RuntimeError("unavailable")
    tracer = LangfuseTracer(
        LangfuseClient(settings(enabled=True), sdk_client=sdk)
    )
    with tracer.observe("voice_session") as observation:
        observation.update(output="still running")


def test_session_root_and_child_use_explicit_sdk_hierarchy() -> None:
    child = Mock()
    root = Mock()
    root.start_observation.return_value = child
    sdk = Mock()
    sdk.create_trace_id.return_value = "a" * 32
    sdk.start_observation.return_value = root
    tracer = LangfuseTracer(
        LangfuseClient(settings(enabled=True), sdk_client=sdk)
    )

    trace_id, observation = tracer.start_session_trace(
        "boloride.voice_session",
        correlation_id="session-123",
        metadata={"interaction_mode": "text"},
    )
    with observation.observe(
        "tool.location_search",
        observation_type="tool",
        metadata={"provider": "ola"},
    ):
        pass
    observation.end()
    observation.end()

    assert trace_id == "a" * 32
    sdk.create_trace_id.assert_called_once_with(seed="session-123")
    sdk.start_observation.assert_called_once_with(
        trace_context={"trace_id": "a" * 32},
        name="boloride.voice_session",
        as_type="agent",
        metadata={"interaction_mode": "text"},
    )
    root.start_observation.assert_called_once_with(
        name="tool.location_search",
        as_type="tool",
        metadata={"provider": "ola"},
    )
    child.end.assert_called_once_with()
    root.end.assert_called_once_with()
