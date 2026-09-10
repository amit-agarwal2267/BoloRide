from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from boloride.llm import LLMMessage, LLMRequest, LLMResponse
from boloride.llm.models import LLMToolCall
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


@pytest.mark.asyncio
async def test_groq_preserves_unique_provider_call_ids_and_repairs_duplicates() -> None:
    tool_calls = [
        SimpleNamespace(
            id="provider-call",
            function=SimpleNamespace(name="search_locations", arguments="{}"),
        ),
        SimpleNamespace(
            id="provider-call",
            function=SimpleNamespace(name="search_locations", arguments="{}"),
        ),
    ]
    native_response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=None, tool_calls=tool_calls),
            finish_reason="tool_calls",
        )],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7),
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=native_response)
    )))

    result = await GroqLLMProvider(
        "test-key", timeout_seconds=5, client=client
    ).generate(LLMRequest(messages=(LLMMessage(role="user", content="Search"),)), "groq-test")

    assert result.tool_calls is not None
    assert result.tool_calls[0].id == "provider-call"
    assert result.tool_calls[1].id != "provider-call"
    assert len({call.id for call in result.tool_calls}) == 2


@pytest.mark.asyncio
async def test_groq_repairs_provider_call_id_reused_from_history() -> None:
    prior_call = LLMToolCall("provider-call", "search_locations", {"query": "Home"})
    request_with_history = LLMRequest(
        messages=(
            LLMMessage(role="user", content="Find home"),
            LLMMessage(role="assistant", tool_calls=[prior_call]),
            LLMMessage(
                role="tool",
                content="found",
                tool_call_id=prior_call.id,
                tool_name=prior_call.name,
            ),
        )
    )
    native_response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(
                content=None,
                tool_calls=[SimpleNamespace(
                    id="provider-call",
                    function=SimpleNamespace(
                        name="search_locations", arguments='{"query":"Station"}'
                    ),
                )],
            ),
            finish_reason="tool_calls",
        )],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=native_response)
    )))

    result = await GroqLLMProvider(
        "test-key", timeout_seconds=5, client=client
    ).generate(request_with_history, "groq-test")

    assert result.tool_calls is not None
    assert result.tool_calls[0].id != prior_call.id
