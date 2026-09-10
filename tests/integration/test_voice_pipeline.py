import json

from livekit.agents import function_tool, llm

from boloride.agents.session import _to_boloride_request
from boloride.llm.models import LLMToolCall


@function_tool
async def sample_tool(query: str) -> str:
    """Search for a sample value."""
    return query


def test_livekit_context_and_tools_are_normalized_for_existing_llm_router() -> None:
    chat_context = llm.ChatContext.empty()
    chat_context.add_message(role="system", content="System instructions")
    chat_context.add_message(role="user", content="Take me to Kota station")

    request = _to_boloride_request(
        chat_context, [sample_tool], session_id="voice-session-1"
    )

    assert request.session_id == "voice-session-1"
    assert request.system_prompt == "System instructions"
    assert request.messages[0].content == "Take me to Kota station"
    assert request.tools is not None
    assert request.tools[0]["function"]["name"] == "sample_tool"


def test_livekit_function_call_extra_survives_back_into_neutral_history() -> None:
    metadata = {
        "google": {
            "thought_signature": {
                "encoding": "base64",
                "data": "AP+A",
            }
        }
    }
    chat_context = llm.ChatContext.empty()
    chat_context.add_message(role="user", content="My name is Amit")
    chat_context.insert(
        llm.FunctionCall(
            call_id="call-1",
            name="record_identity_details",
            arguments='{"name":"Amit"}',
            extra=metadata,
        )
    )
    chat_context.insert(
        llm.FunctionCallOutput(
            call_id="call-1",
            name="record_identity_details",
            output="updated",
            is_error=False,
        )
    )

    request = _to_boloride_request(chat_context, [sample_tool], "voice-session-1")

    json.dumps(
        llm.FunctionToolCall(
            call_id="call-1",
            name="record_identity_details",
            arguments='{"name":"Amit"}',
            extra=metadata,
        ).model_dump(mode="json")
    )
    json.dumps(
        llm.FunctionCall(
            call_id="call-1",
            name="record_identity_details",
            arguments='{"name":"Amit"}',
            extra=metadata,
        ).model_dump(mode="json")
    )
    assert request.messages[1].tool_calls is not None
    assert request.messages[1].tool_calls[0].provider_metadata == metadata
    assert request.messages[2].tool_call_id == "call-1"


def test_parallel_same_tool_calls_are_distinct_livekit_invocations() -> None:
    calls = [
        LLMToolCall(
            "call-pickup",
            "search_locations",
            {"query": "Home", "role": "pickup"},
            {"google": {"thought_signature": {"encoding": "base64", "data": "AQ=="}}},
        ),
        LLMToolCall(
            "call-destination",
            "search_locations",
            {"query": "Station", "role": "destination"},
            {"google": {"thought_signature": {"encoding": "base64", "data": "Ag=="}}},
        ),
    ]

    adapted = [
        llm.FunctionToolCall(
            call_id=call.id,
            name=call.name,
            arguments=json.dumps(call.arguments),
            extra=call.provider_metadata,
        )
        for call in calls
    ]

    assert adapted[0].name == adapted[1].name == "search_locations"
    assert adapted[0].call_id != adapted[1].call_id
    assert adapted[0].extra != adapted[1].extra
    for call in adapted:
        json.dumps(call.model_dump(mode="json"))
