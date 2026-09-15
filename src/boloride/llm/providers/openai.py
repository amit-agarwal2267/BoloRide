"""OpenAI Chat Completions adapter for the existing provider-neutral LLM contract."""

import json
from time import perf_counter
from typing import Any

import openai

from boloride.llm.base import (
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestError,
    LLMTimeoutError,
)
from boloride.llm.models import (
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    ProviderName,
    TokenUsage,
    unique_tool_call_id,
)


class OpenAILLMProvider:
    def __init__(self, api_key: str, *, timeout_seconds: float, client: Any | None = None) -> None:
        if not api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is required for OpenAI routes")
        self._client = client or openai.AsyncOpenAI(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
        )

    @property
    def name(self) -> ProviderName:
        return "openai"

    async def generate(self, request: LLMRequest, model: str) -> LLMResponse:
        messages: list[dict[str, Any]] = []
        if request.system_prompt is not None:
            messages.append({"role": "system", "content": request.system_prompt})
        for message in request.messages:
            if message.role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content or "",
                })
            elif message.role == "assistant" and message.tool_calls:
                native_call_message = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
                if messages and messages[-1].get("role") == "assistant" and "tool_calls" in messages[-1]:
                    messages[-1]["tool_calls"].extend(native_call_message["tool_calls"])
                else:
                    messages.append(native_call_message)
            else:
                messages.append({"role": message.role, "content": message.content or ""})

        options: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "reasoning_effort": "none",
        }
        if request.max_tokens is not None:
            options["max_completion_tokens"] = request.max_tokens
        if request.tools:
            options["tools"] = request.tools
            options["tool_choice"] = "auto"
        # GPT-5.6 models do not accept temperature with reasoning disabled.
        started = perf_counter()
        try:
            response = await self._client.chat.completions.create(**options)
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError("OpenAI generation timed out") from exc
        except openai.RateLimitError as exc:
            raise LLMRateLimitError("OpenAI rate limit exceeded") from exc
        except openai.APIConnectionError as exc:
            raise LLMProviderError("OpenAI is unavailable", transient=True) from exc
        except openai.APIStatusError as exc:
            _raise_openai_status_error(exc)

        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice is not None else None
        tool_calls: list[LLMToolCall] = []
        seen_ids = {
            call.id for message in request.messages for call in (message.tool_calls or [])
            if call.id.strip()
        }
        if choice and choice.message.tool_calls:
            for call in choice.message.tool_calls:
                try:
                    arguments = json.loads(call.function.arguments)
                except (TypeError, ValueError) as exc:
                    raise LLMProviderError("OpenAI returned malformed tool arguments", transient=True) from exc
                if not isinstance(arguments, dict):
                    raise LLMProviderError("OpenAI returned malformed tool arguments", transient=True)
                tool_calls.append(LLMToolCall(
                    id=unique_tool_call_id(call.id, seen_ids),
                    name=call.function.name,
                    arguments=arguments,
                ))
        if not content and not tool_calls:
            raise LLMProviderError("OpenAI returned empty content and no tool calls", transient=True)

        usage = getattr(response, "usage", None)
        details = getattr(usage, "prompt_tokens_details", None)
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        return LLMResponse(
            content=content,
            provider=self.name,
            model=model,
            latency_ms=(perf_counter() - started) * 1000,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cached_tokens=getattr(details, "cached_tokens", None),
                usage_source="provider" if any(
                    value is not None for value in (input_tokens, output_tokens, total_tokens)
                ) else "unknown",
            ),
            finish_reason=choice.finish_reason if choice else None,
            tool_calls=tool_calls or None,
        )

    async def close(self) -> None:
        await self._client.close()


def _raise_openai_status_error(exc: openai.APIStatusError) -> None:
    if exc.status_code in {408, 504}:
        raise LLMTimeoutError("OpenAI generation timed out") from exc
    if exc.status_code == 429:
        raise LLMRateLimitError("OpenAI rate limit exceeded") from exc
    if exc.status_code >= 500 or exc.status_code == 409:
        raise LLMProviderError("OpenAI is temporarily unavailable", transient=True) from exc
    if exc.status_code in {401, 403, 404}:
        raise LLMConfigurationError("OpenAI credentials or model are invalid") from exc
    raise LLMRequestError("OpenAI rejected the generation request") from exc
