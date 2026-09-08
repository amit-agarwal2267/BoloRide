from dataclasses import dataclass
from typing import Literal, Protocol


class PromptUnavailableError(RuntimeError):
    """Neither the managed prompt nor an allowed local fallback is available."""


@dataclass(frozen=True, slots=True)
class RemotePrompt:
    content: str
    version: int


@dataclass(frozen=True, slots=True)
class ResolvedPrompt:
    name: str
    content: str
    source: Literal["langfuse", "fallback"]
    label: str
    version: int | None = None


class PromptClient(Protocol):
    def fetch_text_prompt(self, name: str, label: str) -> RemotePrompt | None: ...
