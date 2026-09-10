import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from boloride.llm import LLMMessage, LLMRequest, LLMResponse, LLMTimeoutError
from boloride.llm.models import LLMToolCall
from boloride.llm.providers.google import GoogleLLMProvider
from google.genai import types


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


def native_response(*parts) -> SimpleNamespace:
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=4, candidates_token_count=2, total_token_count=6
        ),
        candidates=[SimpleNamespace(
            finish_reason=SimpleNamespace(value="STOP"),
            content=SimpleNamespace(parts=list(parts)),
        )],
    )


@pytest.mark.asyncio
async def test_google_thought_signature_survives_tool_round_trip_exactly() -> None:
    signature = bytes(range(256))
    call_part = types.Part.from_function_call(
        name="record_identity_details", args={"name": "Amit"}
    ).model_copy(update={"thought_signature": signature})
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(
        side_effect=[native_response(call_part), native_response(types.Part.from_text(text="Done"))]
    )))
    provider = GoogleLLMProvider("test-key", timeout_seconds=5, client=client)

    first = await provider.generate(request(), "gemini-test")
    assert first.tool_calls is not None
    assert first.tool_calls[0].provider_metadata == {
        "google": {
            "thought_signature": {
                "encoding": "base64",
                "data": base64.b64encode(signature).decode("ascii"),
            }
        }
    }
    json.dumps(first.tool_calls[0].provider_metadata)

    follow_up = LLMRequest(
        messages=(
            LLMMessage(role="user", content="My name is Amit"),
            LLMMessage(role="assistant", tool_calls=first.tool_calls),
            LLMMessage(
                role="tool",
                content="updated",
                tool_call_id=first.tool_calls[0].id,
                tool_name=first.tool_calls[0].name,
            ),
        )
    )
    await provider.generate(follow_up, "gemini-test")

    sent_contents = client.models.generate_content.await_args_list[1].kwargs["contents"]
    reconstructed = sent_contents[1].parts[0]
    assert reconstructed.thought_signature == signature


@pytest.mark.asyncio
async def test_google_preserves_distinct_signatures_for_sequential_tool_calls() -> None:
    first_signature, second_signature = b"first", b"second"
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(
        return_value=native_response(types.Part.from_text(text="Done"))
    )))
    provider = GoogleLLMProvider("test-key", timeout_seconds=5, client=client)
    sequential_request = LLMRequest(messages=(
        LLMMessage(role="user", content="Start"),
        LLMMessage(role="assistant", tool_calls=[LLMToolCall(
            "call-1", "first_tool", {}, {"google": {"thought_signature": {
                "encoding": "base64",
                "data": base64.b64encode(first_signature).decode("ascii"),
            }}}
        )]),
        LLMMessage(role="tool", content="first result", tool_call_id="call-1", tool_name="first_tool"),
        LLMMessage(role="assistant", tool_calls=[LLMToolCall(
            "call-2", "second_tool", {}, {"google": {"thought_signature": {
                "encoding": "base64",
                "data": base64.b64encode(second_signature).decode("ascii"),
            }}}
        )]),
        LLMMessage(role="tool", content="second result", tool_call_id="call-2", tool_name="second_tool"),
    ))

    await provider.generate(sequential_request, "gemini-test")

    contents = client.models.generate_content.await_args.kwargs["contents"]
    assert contents[1].parts[0].thought_signature == first_signature
    assert contents[3].parts[0].thought_signature == second_signature


@pytest.mark.asyncio
async def test_google_parallel_same_tool_calls_have_unique_ids_and_metadata() -> None:
    first_signature = b"pickup-signature\x00"
    second_signature = b"destination-signature\xff"
    first = types.Part.from_function_call(
        name="search_locations", args={"query": "Home", "role": "pickup"}
    ).model_copy(update={"thought_signature": first_signature})
    second = types.Part.from_function_call(
        name="search_locations", args={"query": "Station", "role": "destination"}
    ).model_copy(update={"thought_signature": second_signature})
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(
        return_value=native_response(first, second)
    )))

    response = await GoogleLLMProvider(
        "test-key", timeout_seconds=5, client=client
    ).generate(request(), "gemini-test")

    assert response.tool_calls is not None
    assert len({call.id for call in response.tool_calls}) == 2
    assert response.tool_calls[0].provider_metadata != response.tool_calls[1].provider_metadata
    assert base64.b64decode(
        response.tool_calls[0].provider_metadata["google"]["thought_signature"]["data"],  # type: ignore[index]
        validate=True,
    ) == first_signature
    assert base64.b64decode(
        response.tool_calls[1].provider_metadata["google"]["thought_signature"]["data"],  # type: ignore[index]
        validate=True,
    ) == second_signature


@pytest.mark.asyncio
async def test_google_reused_provider_call_id_is_repaired_across_turns() -> None:
    prior_call = LLMToolCall("provider-call", "search_locations", {"query": "Home"})
    repeated = types.Part(
        function_call=types.FunctionCall(
            id="provider-call", name="search_locations", args={"query": "Station"}
        )
    )
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(
        return_value=native_response(repeated)
    )))
    history = LLMRequest(
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

    response = await GoogleLLMProvider(
        "test-key", timeout_seconds=5, client=client
    ).generate(history, "gemini-test")

    assert response.tool_calls is not None
    assert response.tool_calls[0].id != prior_call.id


@pytest.mark.asyncio
async def test_google_ignores_malformed_thought_signature_metadata() -> None:
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(
        return_value=native_response(types.Part.from_text(text="Done"))
    )))
    provider = GoogleLLMProvider("test-key", timeout_seconds=5, client=client)
    malformed_request = LLMRequest(messages=(
        LLMMessage(role="assistant", tool_calls=[LLMToolCall(
            "call-1",
            "plain_tool",
            {},
            {"google": {"thought_signature": {
                "encoding": "base64",
                "data": "not valid base64!",
            }}},
        )]),
    ))

    await provider.generate(malformed_request, "gemini-test")

    contents = client.models.generate_content.await_args.kwargs["contents"]
    assert contents[0].parts[0].thought_signature is None


@pytest.mark.asyncio
async def test_google_tool_call_without_signature_remains_supported() -> None:
    call = types.Part.from_function_call(name="plain_tool", args={})
    client = SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(
        return_value=native_response(call)
    )))
    response = await GoogleLLMProvider(
        "test-key", timeout_seconds=5, client=client
    ).generate(request(), "gemini-test")
    assert response.tool_calls is not None
    assert response.tool_calls[0].provider_metadata is None
