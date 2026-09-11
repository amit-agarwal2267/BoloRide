import logging
from contextlib import ExitStack, contextmanager
from threading import Lock
from typing import Any, Iterator

from langfuse import propagate_attributes

from boloride.integrations.langfuse.client import LangfuseClient
from boloride.observability.correlation import get_request_id
from boloride.observability.tracing import ObservationType

logger = logging.getLogger(__name__)


class TraceObservation:
    """Provider-neutral handle exposed to instrumented application code."""

    def __init__(self, native_observation: Any | None = None) -> None:
        self._native_observation = native_observation
        self._ended = False
        self._lock = Lock()

    def update(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
    ) -> None:
        if self._native_observation is None:
            return
        try:
            values: dict[str, Any] = {"output": output, "metadata": metadata}
            if model is not None:
                values["model"] = model
            if usage_details is not None:
                values["usage_details"] = usage_details
            if cost_details is not None:
                values["cost_details"] = cost_details
            self._native_observation.update(**values)
        except Exception as exc:
            logger.warning(
                "langfuse_observation_update_failed",
                extra={
                    "event": "langfuse_observation_update_failed",
                    "error_type": type(exc).__name__,
                },
            )

    def end(self) -> None:
        with self._lock:
            if self._ended:
                return
            self._ended = True
        if self._native_observation is None:
            return
        try:
            self._native_observation.end()
        except Exception as exc:
            logger.warning(
                "langfuse_observation_close_failed",
                extra={
                    "event": "langfuse_observation_close_failed",
                    "error_type": type(exc).__name__,
                },
            )

    @contextmanager
    def observe(
        self,
        name: str,
        *,
        observation_type: ObservationType = "span",
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[TraceObservation]:
        if self._native_observation is None:
            yield TraceObservation()
            return
        try:
            child = TraceObservation(
                self._native_observation.start_observation(
                    name=name,
                    as_type=observation_type,
                    metadata=metadata,
                )
            )
        except Exception as exc:
            logger.warning(
                "langfuse_observation_start_failed",
                extra={
                    "event": "langfuse_observation_start_failed",
                    "error_type": type(exc).__name__,
                },
            )
            yield TraceObservation()
            return
        try:
            yield child
        finally:
            child.end()


class LangfuseTracer:
    def __init__(self, client: LangfuseClient) -> None:
        self._client = client

    def start_session_trace(
        self,
        name: str,
        *,
        correlation_id: str,
        metadata: dict[str, Any],
    ) -> tuple[str, TraceObservation]:
        native_client = self._client._client
        if native_client is None:
            return correlation_id, TraceObservation()
        try:
            trace_id = native_client.create_trace_id(seed=correlation_id)
            with propagate_attributes(
                session_id=correlation_id,
                trace_name=name,
                metadata=metadata,
            ):
                native = native_client.start_observation(
                    trace_context={"trace_id": trace_id},
                    name=name,
                    as_type="agent",
                    metadata=metadata,
                )
            return trace_id, TraceObservation(native)
        except Exception as exc:
            logger.warning(
                "langfuse_session_trace_start_failed",
                extra={
                    "event": "langfuse_session_trace_start_failed",
                    "session_id": correlation_id,
                    "error_type": type(exc).__name__,
                },
            )
            return correlation_id, TraceObservation()

    @contextmanager
    def observe(
        self,
        name: str,
        *,
        observation_type: ObservationType = "span",
        correlation_id: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[TraceObservation]:
        native_client = self._client._client
        if native_client is None:
            yield TraceObservation()
            return

        request_id = get_request_id()
        session_id = correlation_id or request_id
        propagated_metadata = dict(metadata or {})
        if request_id is not None:
            propagated_metadata.setdefault("request_id", request_id)

        stack = ExitStack()
        try:
            native_observation = stack.enter_context(
                native_client.start_as_current_observation(
                    name=name,
                    as_type=observation_type,
                    input=input,
                    metadata=metadata,
                )
            )
            if session_id is not None:
                stack.enter_context(
                    propagate_attributes(
                        session_id=session_id,
                        trace_name=name,
                        metadata=propagated_metadata or None,
                    )
                )
        except Exception as exc:
            stack.close()
            logger.warning(
                "langfuse_observation_start_failed",
                extra={
                    "event": "langfuse_observation_start_failed",
                    "session_id": session_id,
                    "error_type": type(exc).__name__,
                },
            )
            yield TraceObservation()
            return

        try:
            yield TraceObservation(native_observation)
        finally:
            try:
                stack.close()
            except Exception as exc:
                logger.warning(
                    "langfuse_observation_close_failed",
                    extra={
                        "event": "langfuse_observation_close_failed",
                        "session_id": session_id,
                        "error_type": type(exc).__name__,
                    },
                )
