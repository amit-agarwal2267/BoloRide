import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from boloride.llm import LLMMessage, LLMRequest
from boloride.llm.base import LLMProviderError
from boloride.llm.models import LLMToolCall
from boloride.llm.providers.openai import OpenAILLMProvider


def native_response(*, calls=None, content=None, usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=calls),
            finish_reason="tool_calls" if calls else "stop",
        )],
        usage=usage,
    )


def provider(response):
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )
    return OpenAILLMProvider("ci-placeholder", timeout_seconds=5, client=client), create


@pytest.mark.asyncio
async def test_openai_text_and_usage_without_tools():
    adapter, create = provider(native_response(
        content="Hello",
        usage=SimpleNamespace(prompt_tokens=8, completion_tokens=3, total_tokens=11),
    ))
    result = await adapter.generate(
        LLMRequest(messages=(LLMMessage(role="user", content="Hi"),), system_prompt="Brief"),
        "gpt-5.6-luna",
    )
    assert result.provider == "openai"
    assert result.model == "gpt-5.6-luna"
    assert result.content == "Hello"
    assert result.usage.input_tokens == 8
    assert result.usage.output_tokens == 3
    assert result.usage.usage_source == "provider"
    options = create.await_args.kwargs
    assert options["reasoning_effort"] == "none"
    assert options["messages"][0] == {"role": "system", "content": "Brief"}
    assert "tools" not in options


@pytest.mark.asyncio
async def test_openai_tool_round_trip_and_distinct_ids():
    calls = [SimpleNamespace(
        id="same-id", function=SimpleNamespace(name="search_locations", arguments='{"query":"home"}')
    ), SimpleNamespace(
        id="same-id", function=SimpleNamespace(name="search_locations", arguments='{"query":"station"}')
    )]
    adapter, _ = provider(native_response(calls=calls))
    result = await adapter.generate(LLMRequest(
        messages=(LLMMessage(role="user", content="Find places"),),
        tools=[{"type": "function", "function": {"name": "search_locations", "parameters": {"type": "object"}}}],
    ), "gpt-5.6-luna")
    assert result.tool_calls is not None
    assert result.tool_calls[0].id == "same-id"
    assert result.tool_calls[1].id != "same-id"
    assert len({call.id for call in result.tool_calls}) == 2

    follow_up, create = provider(native_response(content="Found"))
    previous = LLMToolCall("prior-id", "search_locations", {"query": "home"})
    await follow_up.generate(LLMRequest(messages=(
        LLMMessage(role="user", content="Find home"),
        LLMMessage(role="assistant", tool_calls=[previous]),
        LLMMessage(role="tool", content="found", tool_call_id="prior-id", tool_name="search_locations"),
    )), "gpt-5.6-luna")
    history = create.await_args.kwargs["messages"]
    assert json.loads(history[1]["tool_calls"][0]["function"]["arguments"]) == previous.arguments
    assert history[2] == {"role": "tool", "tool_call_id": "prior-id", "content": "found"}

    second = LLMToolCall("second-id", "search_locations", {"query": "station"})
    follow_up, create = provider(native_response(content="Both found"))
    await follow_up.generate(LLMRequest(messages=(
        LLMMessage(role="user", content="Find two places"),
        LLMMessage(role="assistant", tool_calls=[previous]),
        LLMMessage(role="assistant", tool_calls=[second]),
        LLMMessage(role="tool", content="home", tool_call_id=previous.id, tool_name=previous.name),
        LLMMessage(role="tool", content="station", tool_call_id=second.id, tool_name=second.name),
    )), "gpt-5.6-luna")
    history = create.await_args.kwargs["messages"]
    assert [call["id"] for call in history[1]["tool_calls"]] == ["prior-id", "second-id"]
    assert [item["role"] for item in history] == ["user", "assistant", "tool", "tool"]


@pytest.mark.asyncio
async def test_openai_missing_usage_stays_unknown_and_bad_tool_json_fails_safely():
    adapter, _ = provider(native_response(content="Hi"))
    result = await adapter.generate(LLMRequest(messages=(LLMMessage(role="user", content="Hi"),)), "gpt-5.6-luna")
    assert result.usage.usage_source == "unknown"
    assert result.usage.input_tokens is None

    bad_call = SimpleNamespace(id="call", function=SimpleNamespace(name="tool", arguments="not-json"))
    adapter, _ = provider(native_response(calls=[bad_call]))
    with pytest.raises(LLMProviderError, match="malformed tool arguments") as error:
        await adapter.generate(LLMRequest(messages=(LLMMessage(role="user", content="Hi"),)), "gpt-5.6-luna")
    assert error.value.transient is True
