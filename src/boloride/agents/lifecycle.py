from contextlib import contextmanager
from typing import Iterator

from boloride.observability.tracing import ObservabilityContext


@contextmanager
def voice_session_trace(
    observability: ObservabilityContext,
) -> Iterator[ObservabilityContext]:
    """Compatibility wrapper for the application-owned session context."""
    yield observability
