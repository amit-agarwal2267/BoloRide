import json
import logging
from typing import Any

from livekit.agents import APIConnectOptions, llm
from livekit.agents.llm import utils as llm_utils
from livekit.agents.llm.tool_context import FunctionTool, RawFunctionTool

from boloride.llm.models import LLMMessage, LLMRequest, LLMToolCall
from boloride.llm.router import LLMRouter

logger = logging.getLogger(__name__)


class BoloRideLiveKitLLM(llm.LLM):
    """Small LiveKit transport adapter around BoloRide's existing LLM router."""

    def __init__(self, router: LLMRouter, *, session_id: str) -> None:
        super().__init__()
        self._router = router
        self._session_id = session_id

    @property
    def provider(self) -> str:
        return "boloride-router"

    def chat(self, *, chat_ctx: llm.ChatContext, tools: list[llm.Tool] | None = None, conn_options: APIConnectOptions = APIConnectOptions(), parallel_tool_calls: Any = None, tool_choice: Any = None, extra_kwargs: Any = None) -> llm.LLMStream:
        return BoloRideLLMStream(self, router=self._router, session_id=self._session_id, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class BoloRideLLMStream(llm.LLMStream):
    def __init__(self, llm_instance: BoloRideLiveKitLLM, *, router: LLMRouter, session_id: str, chat_ctx: llm.ChatContext, tools: list[llm.Tool], conn_options: APIConnectOptions) -> None:
        self._router = router
        self._session_id = session_id
        super().__init__(llm_instance, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)

    async def _run(self) -> None:
        request = _to_boloride_request(self._chat_ctx, self._tools, self._session_id)
        response = await self._router.generate(request)
        tool_calls = [llm.FunctionToolCall(name=call.name, arguments=json.dumps(call.arguments), call_id=call.id, extra=call.provider_metadata) for call in response.tool_calls or []]
        for call in tool_calls:
            logger.info(
                "llm_tool_invocation_created",
                extra={
                    "event": "llm_tool_invocation_created",
                    "session_id": self._session_id,
                    "tool_name": call.name,
                    "tool_call_id": call.call_id,
                },
            )
        self._event_ch.send_nowait(llm.ChatChunk(id=f"{response.provider}:{response.model}", delta=llm.ChoiceDelta(role="assistant", content=response.content, tool_calls=tool_calls)))
        if response.usage.total_tokens is not None:
            self._event_ch.send_nowait(llm.ChatChunk(id=f"{response.provider}:{response.model}:usage", usage=llm.CompletionUsage(prompt_tokens=response.usage.input_tokens or 0, completion_tokens=response.usage.output_tokens or 0, total_tokens=response.usage.total_tokens)))


def _to_boloride_request(chat_ctx: llm.ChatContext, tools: list[llm.Tool], session_id: str) -> LLMRequest:
    messages: list[LLMMessage] = []
    system_parts: list[str] = []
    pending_calls: list[LLMToolCall] = []
    for item in chat_ctx.items:
        if isinstance(item, llm.ChatMessage):
            text = item.raw_text_content or ""
            if item.role in {"system", "developer"}:
                if text:
                    system_parts.append(text)
            elif item.role in {"user", "assistant"} and text:
                messages.append(LLMMessage(role=item.role, content=text))
        elif isinstance(item, llm.FunctionCall):
            try:
                arguments = json.loads(item.arguments)
            except (TypeError, json.JSONDecodeError):
                arguments = {}
            pending_calls.append(
                LLMToolCall(
                    item.call_id,
                    item.name,
                    arguments,
                    provider_metadata=item.extra or None,
                )
            )
            messages.append(LLMMessage(role="assistant", tool_calls=[pending_calls[-1]]))
        elif isinstance(item, llm.FunctionCallOutput):
            messages.append(LLMMessage(role="tool", content=item.output, tool_call_id=item.call_id, tool_name=item.name))
    if not messages:
        raise ValueError("LiveKit chat context contains no model messages")
    schemas = []
    for tool in tools:
        if isinstance(tool, FunctionTool):
            schemas.append(llm_utils.build_legacy_openai_schema(tool))
        elif isinstance(tool, RawFunctionTool):
            schemas.append({"type": "function", "function": tool.info.raw_schema})
    return LLMRequest(messages=tuple(messages), system_prompt="\n\n".join(system_parts) or None, session_id=session_id, tools=schemas or None)
