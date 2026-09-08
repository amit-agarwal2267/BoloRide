from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from boloride.llm import LLMMessage, LLMRequest, LLMResponse
from boloride.llm.providers.groq import GroqLLMProvider


@pytest.mark.asyncio
async def test_groq_adapter_normalizes_response() -> None:
    native_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Aapki madad karunga.", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=5, completion_tokens=4, total_tokens=9
        ),
    )
    create = AsyncMock(return_value=native_response)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    provider = GroqLLMProvider("test-key", timeout_seconds=5, client=client)
    request = LLMRequest(
        messages=(LLMMessage(role="user", content="Help"),),
        system_prompt="Be concise",
    )

    result = await provider.generate(request, "groq-test")

    assert isinstance(result, LLMResponse)
    assert result.content == "Aapki madad karunga."
    assert result.provider == "groq"
    assert result.model == "groq-test"
    assert result.usage.input_tokens == 5
    assert result.usage.output_tokens == 4
    assert result.usage.total_tokens == 9
    assert result.finish_reason == "stop"
    assert native_response is not result
    create.assert_awaited_once()
