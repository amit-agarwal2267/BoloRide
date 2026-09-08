from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from boloride.llm import LLMMessage, LLMRequest, LLMResponse, LLMTimeoutError
from boloride.llm.providers.google import GoogleLLMProvider


def request() -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(role="user", content="Namaste"),),
        system_prompt="Be concise",
        temperature=0.2,
        max_tokens=100,
    )


@pytest.mark.asyncio
async def test_google_adapter_normalizes_response() -> None:
    native_response = SimpleNamespace(
        text="Namaste!",
        usage_metadata=SimpleNamespace(
            prompt_token_count=4, candidates_token_count=2, total_token_count=6
        ),
        candidates=[SimpleNamespace(
            finish_reason=SimpleNamespace(value="STOP"),
            content=SimpleNamespace(parts=[SimpleNamespace(text="Namaste!", function_call=None)])
        )],
    )
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=AsyncMock(return_value=native_response))
    )
    provider = GoogleLLMProvider("test-key", timeout_seconds=5, client=client)

    result = await provider.generate(request(), "gemini-test")

    assert isinstance(result, LLMResponse)
    assert result.content == "Namaste!"
    assert result.provider == "google"
    assert result.model == "gemini-test"
    assert result.usage.input_tokens == 4
    assert result.usage.output_tokens == 2
    assert result.usage.total_tokens == 6
    assert result.finish_reason == "STOP"
    assert native_response is not result


@pytest.mark.asyncio
async def test_google_adapter_normalizes_timeout() -> None:
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=AsyncMock(side_effect=TimeoutError))
    )
    provider = GoogleLLMProvider("test-key", timeout_seconds=5, client=client)

    with pytest.raises(LLMTimeoutError):
        await provider.generate(request(), "gemini-test")
