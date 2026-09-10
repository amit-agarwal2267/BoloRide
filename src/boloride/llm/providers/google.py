import base64
import binascii
from time import perf_counter
from typing import Any

from google import genai
from google.genai import errors, types

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


class GoogleLLMProvider:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise LLMConfigurationError("GOOGLE_API_KEY is required for Google routes")
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ).aio

    @property
    def name(self) -> ProviderName:
        return "google"

    async def generate(self, request: LLMRequest, model: str) -> LLMResponse:
        contents = []
        for message in request.messages:
            if message.role == "tool":
                parts = [types.Part.from_function_response(
                    name=message.tool_name or "tool",
                    response={"result": message.content or ""},
                )]
                contents.append(types.Content(role="user", parts=parts))
            elif message.role == "assistant":
                parts = []
                if message.content:
                    parts.append(types.Part.from_text(text=message.content))
                if message.tool_calls:
                    for call in message.tool_calls:
                        function_part = types.Part.from_function_call(
                            name=call.name,
                            args=call.arguments
                        )
                        signature = _google_thought_signature(call.provider_metadata)
                        if signature is not None:
                            function_part = function_part.model_copy(
                                update={"thought_signature": signature}
                            )
                        parts.append(function_part)
                contents.append(types.Content(role="model", parts=parts))
            else:
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=message.content)],
                ))
        config = types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            temperature=request.temperature,
            max_output_tokens=request.max_tokens,
            tools=_google_tools(request.tools),
        )
        started = perf_counter()
        try:
            response = await self._client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except errors.APIError as exc:
            _raise_google_error(exc)
        except TimeoutError as exc:
            raise LLMTimeoutError("Google generation timed out") from exc

        choice = response.candidates[0] if response.candidates else None
        if not choice:
            raise LLMProviderError("Google returned no candidates")

        content = None
        tool_calls = []
        seen_call_ids = {
            call.id
            for message in request.messages
            for call in (message.tool_calls or [])
            if call.id.strip()
        }
        for part in (choice.content.parts if choice.content else []):
            if part.text:
                content = (content or "") + part.text
            elif getattr(part, "function_call", None):
                provider_metadata = None
                thought_signature = getattr(part, "thought_signature", None)
                if thought_signature is not None:
                    provider_metadata = {
                        "google": {
                            "thought_signature": {
                                "encoding": "base64",
                                "data": base64.b64encode(thought_signature).decode("ascii"),
                            }
                        }
                    }
                tool_calls.append(
                    LLMToolCall(
                        id=unique_tool_call_id(
                            getattr(part.function_call, "id", None), seen_call_ids
                        ),
                        name=part.function_call.name,
                        arguments=dict(part.function_call.args) if part.function_call.args else {},
                        provider_metadata=provider_metadata,
                    )
                )
        
        if not content and not tool_calls:
            raise LLMProviderError("Google returned empty content and no tool calls")
        usage = response.usage_metadata
        finish_reason = getattr(choice.finish_reason, "value", choice.finish_reason)
        return LLMResponse(
            content=content,
            provider=self.name,
            model=model,
            latency_ms=(perf_counter() - started) * 1000,
            usage=TokenUsage(
                input_tokens=getattr(usage, "prompt_token_count", None),
                output_tokens=getattr(usage, "candidates_token_count", None),
                total_tokens=getattr(usage, "total_token_count", None),
            ),
            finish_reason=str(finish_reason) if finish_reason is not None else None,
            tool_calls=tool_calls or None,
        )

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


def _raise_google_error(exc: errors.APIError) -> None:
    code = exc.code or 0
    if code in {408, 504}:
        raise LLMTimeoutError("Google generation timed out") from exc
    if code == 429:
        raise LLMRateLimitError("Google rate limit exceeded") from exc
    if code >= 500 or code == 409:
        raise LLMProviderError("Google is temporarily unavailable", transient=True) from exc
    if code in {401, 403, 404}:
        raise LLMConfigurationError("Google credentials or model are invalid") from exc
    raise LLMRequestError("Google rejected the generation request") from exc


def _google_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    declarations = []
    for tool in tools:
        function = tool.get("function", tool)
        declarations.append({
            "name": function["name"],
            "description": function.get("description", ""),
            "parameters_json_schema": function.get("parameters", {"type": "object"}),
        })
    return [{"function_declarations": declarations}]


def _google_thought_signature(provider_metadata: dict[str, Any] | None) -> bytes | None:
    if not provider_metadata:
        return None
    google_metadata = provider_metadata.get("google")
    if not isinstance(google_metadata, dict):
        return None
    signature = google_metadata.get("thought_signature")
    if not isinstance(signature, dict) or signature.get("encoding") != "base64":
        return None
    encoded = signature.get("data")
    if not isinstance(encoded, str):
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
