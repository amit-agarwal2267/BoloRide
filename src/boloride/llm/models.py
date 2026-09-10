from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

ProviderName = Literal["google", "groq"]
MessageRole = Literal["user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments: dict
    provider_metadata: dict[str, Any] | None = None


def unique_tool_call_id(candidate: object, seen: set[str]) -> str:
    """Preserve a usable provider ID, otherwise create one per invocation."""
    call_id = candidate.strip() if isinstance(candidate, str) else ""
    if not call_id or call_id in seen:
        call_id = f"call_{uuid4().hex}"
    seen.add(call_id)
    return call_id


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: MessageRole
    content: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_calls: list[LLMToolCall] | None = None

    def __post_init__(self) -> None:
        if self.role != "tool" and self.tool_calls is None and (not self.content or not self.content.strip()):
            raise ValueError("LLM message content must not be empty")


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: tuple[LLMMessage, ...]
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    session_id: str | None = None
    prompt_name: str | None = None
    prompt_version: int | None = None
    prompt_label: str | None = None
    prompt_source: Literal["langfuse", "fallback"] | None = None
    tools: list[dict] | None = None

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("LLM request must contain at least one message")
        if self.system_prompt is not None and not self.system_prompt.strip():
            raise ValueError("system prompt must not be empty")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str | None
    provider: ProviderName
    model: str
    latency_ms: float
    usage: TokenUsage = field(default_factory=TokenUsage)
    fallback_used: bool = False
    finish_reason: str | None = None
    tool_calls: list[LLMToolCall] | None = None


@dataclass(frozen=True, slots=True)
class LLMRoute:
    provider: ProviderName
    model: str

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("LLM route model must not be empty")
