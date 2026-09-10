from time import perf_counter
from typing import Any

import groq

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


class GroqLLMProvider:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise LLMConfigurationError("GROQ_API_KEY is required for Groq routes")
        self._client = client or groq.AsyncGroq(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
        )

    @property
    def name(self) -> ProviderName:
        return "groq"

    async def generate(self, request: LLMRequest, model: str) -> LLMResponse:
        messages: list[dict[str, Any]] = []
        if request.system_prompt is not None:
            messages.append({"role": "system", "content": request.system_prompt})
        for message in request.messages:
            msg: dict[str, Any] = {"role": message.role, "content": message.content or ""}
            if message.role == "assistant" and message.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": str(call.arguments).replace("'", '"')},
                    }
                    for call in message.tool_calls
                ]
            if message.role == "tool" and message.tool_call_id:
                msg["tool_call_id"] = message.tool_call_id
                # The API expects role 'tool' for function outputs in groq
                msg["role"] = "tool"
            messages.append(msg)

        started = perf_counter()
        generation_options: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if request.temperature is not None:
            generation_options["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation_options["max_tokens"] = request.max_tokens
        if request.tools:
            generation_options["tools"] = request.tools
            generation_options["tool_choice"] = "auto"
        try:
            response = await self._client.chat.completions.create(**generation_options)
        except groq.APITimeoutError as exc:
            raise LLMTimeoutError("Groq generation timed out") from exc
        except groq.RateLimitError as exc:
            raise LLMRateLimitError("Groq rate limit exceeded") from exc
        except groq.APIConnectionError as exc:
            raise LLMProviderError("Groq is unavailable", transient=True) from exc
        except groq.APIStatusError as exc:
            _raise_groq_status_error(exc)

        choice = response.choices[0] if response.choices else None
        content = choice.message.content if choice is not None else None
        tool_calls = []
        seen_call_ids = {
            call.id
            for message in request.messages
            for call in (message.tool_calls or [])
            if call.id.strip()
        }
        import json
        if choice and choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                tool_calls.append(
                    LLMToolCall(
                        id=unique_tool_call_id(tc.id, seen_call_ids),
                        name=tc.function.name,
                        arguments=args
                    )
                )

        if not content and not tool_calls:
            raise LLMProviderError("Groq returned empty content and no tool calls")
        usage = response.usage
        return LLMResponse(
            content=content,
            provider=self.name,
            model=model,
            latency_ms=(perf_counter() - started) * 1000,
            usage=TokenUsage(
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
            ),
            finish_reason=choice.finish_reason,
            tool_calls=tool_calls if tool_calls else None
        )

    async def close(self) -> None:
        await self._client.close()


def _raise_groq_status_error(exc: groq.APIStatusError) -> None:
    if exc.status_code in {408, 504}:
        raise LLMTimeoutError("Groq generation timed out") from exc
    if exc.status_code == 429:
        raise LLMRateLimitError("Groq rate limit exceeded") from exc
    if exc.status_code >= 500 or exc.status_code == 409:
        raise LLMProviderError("Groq is temporarily unavailable", transient=True) from exc
    if exc.status_code in {401, 403, 404}:
        raise LLMConfigurationError("Groq credentials or model are invalid") from exc
    raise LLMRequestError("Groq rejected the generation request") from exc
