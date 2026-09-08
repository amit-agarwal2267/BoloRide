import logging
from contextlib import ExitStack, contextmanager
from typing import Any, Iterator, Literal

from langfuse import propagate_attributes

from boloride.integrations.langfuse.client import LangfuseClient
from boloride.observability.correlation import get_request_id

logger = logging.getLogger(__name__)
ObservationType = Literal["span", "generation", "agent", "tool", "chain", "retriever"]


class TraceObservation:
    """Provider-neutral handle exposed to instrumented application code."""

    def __init__(self, native_observation: Any | None = None) -> None:
        self._native_observation = native_observation

    def update(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._native_observation is None:
            return
        try:
            self._native_observation.update(output=output, metadata=metadata)
        except Exception as exc:
            logger.warning(
                "langfuse_observation_update_failed",
                extra={
                    "event": "langfuse_observation_update_failed",
                    "error_type": type(exc).__name__,
                },
            )


class LangfuseTracer:
    def __init__(self, client: LangfuseClient) -> None:
        self._client = client

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
