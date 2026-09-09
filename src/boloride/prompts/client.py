from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol


class PromptUnavailableError(RuntimeError):
    """Neither the managed prompt nor an allowed local fallback is available."""


@dataclass(frozen=True, slots=True)
class RemotePrompt:
    content: str
    version: int


class PromptFetchStatus(StrEnum):
    AVAILABLE = "available"
    NOT_CONFIGURED = "not_configured"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class PromptFetchResult:
    status: PromptFetchStatus
    prompt: RemotePrompt | None = None

    def __post_init__(self) -> None:
        if (self.status is PromptFetchStatus.AVAILABLE) != (self.prompt is not None):
            raise ValueError("an available prompt fetch must contain exactly one prompt")


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    name: str
    content: str
    source: Literal["langfuse", "fallback"]
    label: str
    version: int | None = None


class PromptClient(Protocol):
    def fetch_text_prompt(self, name: str, label: str) -> PromptFetchResult: ...
