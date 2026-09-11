from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import StrEnum
import logging
from threading import Lock
from typing import Any, Iterator, Literal, Protocol

from boloride.observability.session_metrics import FunnelMilestone, SessionMetrics


logger = logging.getLogger(__name__)


ObservationType = Literal[
    "span", "generation", "agent", "tool", "chain", "retriever"
]


class SessionOutcome(StrEnum):
    COMPLETED_WITHOUT_BOOKING = "completed_without_booking"
    COMPLETED = "completed_without_booking"
    BOOKED = "booked"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ABANDONED = "abandoned"
    GUARDRAIL_TERMINATED = "guardrail_terminated"


@dataclass(frozen=True, slots=True)
class VoiceSessionMetadata:
    persona_id: str
    persona_gender: str
    interaction_mode: str
    stt_provider: str
    maps_provider: str
    tts_provider: str
    prompt_source: str
    environment: str

    def as_dict(self) -> dict[str, str]:
        return {
            "persona_id": self.persona_id,
            "persona_gender": self.persona_gender,
            "interaction_mode": self.interaction_mode,
            "stt_provider": self.stt_provider,
            "maps_provider": self.maps_provider,
            "tts_provider": self.tts_provider,
            "prompt_source": self.prompt_source,
            "environment": self.environment,
        }


class Observation(Protocol):
    def update(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
    ) -> None: ...

    def end(self) -> None: ...

    @contextmanager
    def observe(
        self,
        name: str,
        *,
        observation_type: ObservationType = "span",
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Observation]: ...


class Tracer(Protocol):
    @contextmanager
    def observe(
        self,
        name: str,
        *,
        observation_type: ObservationType = "span",
        correlation_id: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Observation]: ...

    def start_session_trace(
        self,
        name: str,
        *,
        correlation_id: str,
        metadata: dict[str, Any],
    ) -> tuple[str, Observation]: ...


_current_context: ContextVar[ObservabilityContext | None] = ContextVar(
    "boloride_observability_context", default=None
)


class ObservabilityContext:
    """Application-owned, session-scoped trace and correlation boundary."""

    def __init__(
        self,
        *,
        tracer: Tracer,
        session_id: str,
        trace_id: str,
        root: Observation,
        metadata: VoiceSessionMetadata,
    ) -> None:
        self._tracer = tracer
        self.session_id = session_id
        self.trace_id = trace_id
        self.metadata = metadata
        self._root = root
        self.metrics = SessionMetrics()
        self._outcome: SessionOutcome | None = None
        self._closed = False
        self._lock = Lock()

    @classmethod
    def start_voice_session(
        cls,
        tracer: Tracer,
        *,
        session_id: str,
        metadata: VoiceSessionMetadata,
    ) -> ObservabilityContext:
        trace_id, root = tracer.start_session_trace(
            "boloride.voice_session",
            correlation_id=session_id,
            metadata={"session_id": session_id, **metadata.as_dict()},
        )
        return cls(
            tracer=tracer,
            session_id=session_id,
            trace_id=trace_id,
            root=root,
            metadata=metadata,
        )

    @property
    def outcome(self) -> SessionOutcome | None:
        return self._outcome

    @contextmanager
    def activate(self) -> Iterator[ObservabilityContext]:
        token: Token[ObservabilityContext | None] = _current_context.set(self)
        try:
            yield self
        finally:
            _current_context.reset(token)

    @contextmanager
    def observe(
        self,
        name: str,
        *,
        observation_type: ObservationType = "span",
        correlation_id: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Observation]:
        del correlation_id, input
        with self._root.observe(
            name, observation_type=observation_type, metadata=metadata
        ) as observation:
            yield observation

    def record_event(
        self, name: str, *, metadata: dict[str, Any] | None = None
    ) -> None:
        with self.observe(name, metadata=metadata):
            pass

    def set_outcome(self, outcome: SessionOutcome) -> None:
        priorities = {
            SessionOutcome.COMPLETED_WITHOUT_BOOKING: 1,
            SessionOutcome.ABANDONED: 1,
            SessionOutcome.FAILED: 2,
            SessionOutcome.GUARDRAIL_TERMINATED: 2,
            SessionOutcome.BOOKED: 3,
            SessionOutcome.CANCELLED: 4,
        }
        with self._lock:
            if self._outcome is None or priorities[outcome] >= priorities[self._outcome]:
                self._outcome = outcome

    def finalize(self, default_outcome: SessionOutcome) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            outcome = self._outcome or default_outcome
        summary = self.metrics.summary(outcome=outcome.value)
        self._root.update(metadata=summary)
        self._root.end()
        logger.info(
            "voice_session_summary",
            extra={
                "event": "voice_session_summary",
                "session_id": self.session_id,
                "trace_id": self.trace_id,
                "session_metrics": summary,
            },
        )

    def mark_milestone(self, milestone: FunnelMilestone) -> None:
        self.metrics.mark_milestone(milestone)


def get_observability_context() -> ObservabilityContext | None:
    return _current_context.get()
