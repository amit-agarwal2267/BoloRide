from typing import Protocol

from boloride.llm.models import LLMRequest, LLMResponse, ProviderName


class LLMError(RuntimeError):
    """Base error for the provider-neutral LLM layer."""


class LLMRequestError(LLMError):
    """The normalized request is invalid for generation."""


class LLMConfigurationError(LLMError):
    """An LLM route or provider is not configured correctly."""


class LLMProviderError(LLMError):
    """A provider call failed, optionally due to a transient condition."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class LLMTimeoutError(LLMProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, transient=True)


class LLMRateLimitError(LLMProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, transient=True)


class AllProvidersFailedError(LLMError):
    """Every configured route exhausted its transient attempts."""


class LLMProvider(Protocol):
    @property
    def name(self) -> ProviderName: ...

    async def generate(self, request: LLMRequest, model: str) -> LLMResponse: ...

    async def close(self) -> None: ...
