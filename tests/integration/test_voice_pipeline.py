from livekit.agents import function_tool, llm

from boloride.agents.session import _to_boloride_request


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
