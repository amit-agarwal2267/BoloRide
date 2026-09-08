from contextlib import contextmanager
from typing import Iterator

from boloride.integrations.langfuse.tracing import LangfuseTracer, TraceObservation


@contextmanager
def voice_session_trace(
    tracer: LangfuseTracer, session_id: str
) -> Iterator[TraceObservation]:
    with tracer.observe(
        "voice_session",
        observation_type="agent",
        correlation_id=session_id,
        metadata={"session_id": session_id},
    ) as observation:
        yield observation
