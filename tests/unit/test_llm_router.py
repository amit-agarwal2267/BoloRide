from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from unittest.mock import AsyncMock

import pytest

from boloride.llm import (
    AllProvidersFailedError,
    LLMConfigurationError,
    LLMMessage,
    LLMProviderError,
    LLMRequest,
    LLMRequestError,
    LLMResponse,
    LLMTimeoutError,
)
from boloride.llm.models import LLMRoute, ProviderName
from boloride.llm.router import LLMRouter, create_llm_router


class Observation:
    def __init__(self) -> None:
        self.updates: list[dict[str, object] | None] = []

    def update(self, *, output: object = None, metadata: dict[str, object] | None = None, **kwargs: object) -> None:
        self.updates.append(metadata)


class Tracer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.observations: list[Observation] = []

    @contextmanager
    def observe(self, name: str, **kwargs: object) -> Iterator[Observation]:
        self.calls.append({"name": name, **kwargs})
        observation = Observation()
        self.observations.append(observation)
        yield observation


@dataclass
class Provider:
    name: ProviderName
    generate: AsyncMock

    async def close(self) -> None:
        return None


def request() -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(role="user", content="Book a ride"),),
        session_id="session-123",
        prompt_name="boloride-voice-agent",
        prompt_version=7,
        prompt_label="development",
        prompt_source="langfuse",
    )


def response(provider: ProviderName, model: str) -> LLMResponse:
    return LLMResponse(
        content="Where would you like to go?",
        provider=provider,
        model=model,
        latency_ms=12.5,
    )


@pytest.mark.asyncio
async def test_primary_success_and_tracing_metadata() -> None:
    google = Provider("google", AsyncMock(return_value=response("google", "primary")))
    tracer = Tracer()
    router = LLMRouter(
        [LLMRoute("google", "primary")], {"google": google}, tracer, max_retries=0
    )

    result = await router.generate(request())

    assert result.provider == "google"
    assert result.model == "primary"
    assert result.fallback_used is False
    assert tracer.calls[0]["observation_type"] == "generation"
    assert tracer.calls[0]["correlation_id"] == "session-123"
    metadata = tracer.observations[0].updates[0]
    assert metadata is not None
    assert metadata["success"] is True
    assert metadata["prompt_version"] == 7


@pytest.mark.asyncio
async def test_transient_failure_uses_first_fallback() -> None:
    google = Provider(
        "google",
        AsyncMock(
            side_effect=[LLMTimeoutError("timeout"), response("google", "fallback")]
        ),
    )
    router = LLMRouter(
        [LLMRoute("google", "primary"), LLMRoute("google", "fallback")],
        {"google": google},
        Tracer(),
        max_retries=0,
    )

    result = await router.generate(request())

    assert result.model == "fallback"
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_second_provider_fallback() -> None:
    google = Provider("google", AsyncMock(side_effect=LLMTimeoutError("timeout")))
    groq = Provider("groq", AsyncMock(return_value=response("groq", "last")))
    router = LLMRouter(
        [LLMRoute("google", "primary"), LLMRoute("groq", "last")],
        {"google": google, "groq": groq},
        Tracer(),
        max_retries=0,
    )

    result = await router.generate(request())

    assert result.provider == "groq"
    assert result.model == "last"
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_non_transient_error_does_not_fallback() -> None:
    google = Provider(
        "google", AsyncMock(side_effect=LLMProviderError("bad response"))
    )
    groq = Provider("groq", AsyncMock(return_value=response("groq", "last")))
    router = LLMRouter(
        [LLMRoute("google", "primary"), LLMRoute("groq", "last")],
        {"google": google, "groq": groq},
        Tracer(),
        max_retries=0,
    )

    with pytest.raises(LLMProviderError):
        await router.generate(request())
    groq.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_error_does_not_fallback() -> None:
    google = Provider("google", AsyncMock(side_effect=LLMRequestError("invalid")))
    groq = Provider("groq", AsyncMock(return_value=response("groq", "last")))
    router = LLMRouter(
        [LLMRoute("google", "primary"), LLMRoute("groq", "last")],
        {"google": google, "groq": groq},
        Tracer(),
        max_retries=0,
    )

    with pytest.raises(LLMRequestError):
        await router.generate(request())
    groq.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unexpected_error_is_traced_and_does_not_fallback() -> None:
    google = Provider("google", AsyncMock(side_effect=TypeError("coding error")))
    groq = Provider("groq", AsyncMock(return_value=response("groq", "last")))
    tracer = Tracer()
    router = LLMRouter(
        [LLMRoute("google", "primary"), LLMRoute("groq", "last")],
        {"google": google, "groq": groq},
        tracer,
        max_retries=0,
    )

    with pytest.raises(TypeError):
        await router.generate(request())
    assert tracer.observations[0].updates[0]["failure_category"] == "unknown"
    groq.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_providers_failed() -> None:
    google = Provider("google", AsyncMock(side_effect=LLMTimeoutError("timeout")))
    groq = Provider(
        "groq", AsyncMock(side_effect=LLMProviderError("down", transient=True))
    )
    router = LLMRouter(
        [LLMRoute("google", "primary"), LLMRoute("groq", "last")],
        {"google": google, "groq": groq},
        Tracer(),
        max_retries=0,
    )

    with pytest.raises(AllProvidersFailedError):
        await router.generate(request())


@pytest.mark.asyncio
async def test_bounded_retry_before_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("boloride.llm.router.asyncio.sleep", sleep)
    google = Provider("google", AsyncMock(side_effect=LLMTimeoutError("timeout")))
    groq = Provider("groq", AsyncMock(return_value=response("groq", "last")))
    router = LLMRouter(
        [LLMRoute("google", "primary"), LLMRoute("groq", "last")],
        {"google": google, "groq": groq},
        Tracer(),
        max_retries=1,
    )

    result = await router.generate(request())

    assert google.generate.await_count == 2
    sleep.assert_awaited_once_with(0.25)
    assert result.provider == "groq"


def test_missing_provider_configuration_fails_clearly(settings) -> None:
    settings.google_api_key = None
    with pytest.raises(LLMConfigurationError, match="GOOGLE_API_KEY"):
        create_llm_router(settings, Tracer())


def test_duplicate_routes_are_rejected() -> None:
    google = Provider("google", AsyncMock())
    with pytest.raises(LLMConfigurationError, match="duplicate"):
        LLMRouter(
            [LLMRoute("google", "same"), LLMRoute("google", "same")],
            {"google": google},
            Tracer(),
        )
