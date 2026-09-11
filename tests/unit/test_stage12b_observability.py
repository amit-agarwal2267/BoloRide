from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import json
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import AsyncMock

import pytest

from boloride.llm import LLMMessage, LLMRequest, LLMResponse, LLMTimeoutError
from boloride.llm.models import LLMRoute, TokenUsage
from boloride.llm.router import LLMRouter
from boloride.observability.llm_pricing import ModelPricing, apply_llm_cost
from boloride.observability.session_metrics import SessionMetrics
from boloride.domain.exceptions import LocationProviderError
from boloride.integrations.maps.router import MapsRouter
from boloride.speech.tts.local_tts import EdgeChunkedStream


PRICE = ModelPricing(
    input_per_1m_tokens=Decimal("0.125"),
    output_per_1m_tokens=Decimal("0.375"),
    currency="USD",
    source="test fixture",
    last_verified=date(2026, 1, 1),
)


class Observation:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    def update(self, **values: object) -> None:
        self.updates.append(values)


class Tracer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.observations: list[Observation] = []
        self.metrics = SessionMetrics()

    @contextmanager
    def observe(self, name: str, **values: object) -> Iterator[Observation]:
        self.calls.append({"name": name, **values})
        observation = Observation()
        self.observations.append(observation)
        yield observation


def test_registry_cost_uses_decimal_and_separate_input_output_rates() -> None:
    usage = apply_llm_cost(
        "google",
        "exact-model",
        TokenUsage(1_000_001, 2_000_002, 3_000_003, usage_source="provider"),
        registry={("google", "exact-model"): PRICE},
    )

    assert usage.input_cost == Decimal("0.125000125")
    assert usage.output_cost == Decimal("0.750000750")
    assert usage.total_cost == Decimal("0.875000875")
    assert usage.currency == "USD"
    assert usage.cost_source == "pricing_registry"


def test_registry_requires_exact_model_and_complete_usage() -> None:
    registry = {("google", "exact-model"): PRICE}
    unknown = apply_llm_cost(
        "google", "exact-model-latest", TokenUsage(1, 1, 2), registry=registry
    )
    missing = apply_llm_cost(
        "google", "exact-model", TokenUsage(input_tokens=1), registry=registry
    )

    assert unknown.total_cost is None and unknown.cost_source == "unknown"
    assert missing.total_cost is None and missing.cost_source == "unknown"


def test_provider_reported_cost_has_precedence() -> None:
    reported = TokenUsage(
        10,
        20,
        30,
        usage_source="provider",
        total_cost=Decimal("0.42"),
        currency="USD",
        cost_source="provider_reported",
    )
    assert apply_llm_cost(
        "google", "exact-model", reported, registry={("google", "exact-model"): PRICE}
    ) is reported


@pytest.mark.parametrize(
    "pricing",
    [
        {"input_per_1m_tokens": Decimal("-1"), "output_per_1m_tokens": Decimal("1")},
        {"input_per_1m_tokens": Decimal("1"), "output_per_1m_tokens": Decimal("-1")},
    ],
)
def test_negative_pricing_is_rejected(pricing: dict[str, Decimal]) -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        ModelPricing(**pricing, currency="USD", source="test", last_verified=date.today())


def test_negative_token_usage_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        TokenUsage(input_tokens=-1)


@pytest.mark.asyncio
async def test_router_records_two_ordered_attempts_without_model_content() -> None:
    google = SimpleNamespace(
        generate=AsyncMock(side_effect=LLMTimeoutError("private provider detail")),
        close=AsyncMock(),
    )
    groq = SimpleNamespace(
        generate=AsyncMock(
            return_value=LLMResponse(
                content="private model response",
                provider="groq",
                model="fallback",
                latency_ms=4,
                usage=TokenUsage(5, 3, 8, usage_source="provider"),
            )
        ),
        close=AsyncMock(),
    )
    tracer = Tracer()
    router = LLMRouter(
        [LLMRoute("google", "primary"), LLMRoute("groq", "fallback")],
        {"google": google, "groq": groq},
        tracer,
        max_retries=0,
    )
    request = LLMRequest(
        messages=(LLMMessage(role="user", content="private user prompt"),),
        session_id="session",
    )

    result = await router.generate(request)

    assert result.fallback_used is True
    assert [call["name"] for call in tracer.calls] == ["voice.llm", "voice.llm"]
    first = tracer.observations[0].updates[0]["metadata"]
    second = tracer.observations[1].updates[0]["metadata"]
    assert first["attempt_order"] == 1
    assert first["failure_category"] == "timeout"
    assert second["attempt_order"] == 2
    assert second["route_role"] == "fallback"
    serialized = json.dumps([first, second])
    assert "private user prompt" not in serialized
    assert "private model response" not in serialized
    assert "private provider detail" not in serialized
    summary = tracer.metrics.summary(outcome="completed_without_booking")
    assert summary["llm_call_count"] == 2
    assert summary["failed_llm_calls"] == 1
    assert summary["llm_fallback_count"] == 1
    assert summary["total_tokens"] == 8


class RecordingContext:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.observations: list[Observation] = []

    @contextmanager
    def observe(self, name: str, **_: object) -> Iterator[Observation]:
        self.names.append(name)
        observation = Observation()
        self.observations.append(observation)
        yield observation


class MapProvider:
    def __init__(self, name: str, result: object) -> None:
        self.provider_name = name
        self.result = result

    async def search_location(self, *_: object) -> list[object]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result  # type: ignore[return-value]

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_maps_records_only_real_provider_attempts_and_fallback() -> None:
    context = RecordingContext()
    router = MapsRouter(SimpleNamespace(maps_provider="ola"), context)  # type: ignore[arg-type]
    router._route_providers = [
        MapProvider("ola", LocationProviderError("private")),
        MapProvider("google", [object()]),
    ]  # type: ignore[assignment]

    candidates, provider, fallback, unavailable = await router.search_location(
        "private address", SimpleNamespace()
    )

    assert len(candidates) == 1
    assert (provider, fallback, unavailable) == ("google", True, False)
    assert context.names == ["provider.ola", "provider.google"]
    first = context.observations[0].updates[0]["metadata"]
    second = context.observations[1].updates[0]["metadata"]
    assert first["failure_category"] == "provider_unavailable"
    assert second["candidate_count"] == 1
    assert "private address" not in json.dumps([first, second])


@pytest.mark.asyncio
async def test_edge_tts_records_full_synthesis_without_text(monkeypatch) -> None:
    context = RecordingContext()
    monkeypatch.setattr(
        "boloride.speech.tts.local_tts.get_observability_context", lambda: context
    )

    class Communication:
        async def stream(self):
            yield {"type": "audio", "data": b"audio"}

    class Container:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def decode(self, **_):
            return []

    class Emitter:
        def initialize(self, **_):
            return None

    monkeypatch.setattr(
        "boloride.speech.tts.local_tts.edge_tts.Communicate",
        lambda *_: Communication(),
    )
    monkeypatch.setattr("boloride.speech.tts.local_tts.av.open", lambda *_: Container())
    stream = object.__new__(EdgeChunkedStream)
    stream._input_text = "private synthesized text"
    stream._voice = "hi-IN-test"

    await stream._run(Emitter())  # type: ignore[arg-type]

    assert context.names == ["voice.tts"]
    metadata = context.observations[0].updates[0]["metadata"]
    assert metadata["success"] is True
    assert metadata["duration_ms"] >= 0
    assert "private synthesized text" not in json.dumps(metadata)


def test_assemblyai_has_no_truthful_utterance_latency_boundary() -> None:
    # The configured LiveKit plugin object owns its websocket and transcript timing;
    # BoloRide receives no paired speech-end/transcript-received timestamps here.
    from boloride.speech.stt.assemblyai import AssemblyAIProvider

    assert not hasattr(AssemblyAIProvider, "transcript_latency_ms")
