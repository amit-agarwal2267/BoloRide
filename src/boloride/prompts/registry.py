import logging
from enum import StrEnum
from pathlib import Path

from boloride.prompts.client import (
    PromptClient,
    PromptFetchStatus,
    PromptUnavailableError,
    ResolvedPrompt,
)

logger = logging.getLogger(__name__)


class PromptKey(StrEnum):
    VOICE_AGENT = "voice_agent"
    LOCATION_CLARIFICATION = "location_clarification"
    BOOKING_CONFIRMATION = "booking_confirmation"
    ERROR_RECOVERY = "error_recovery"
    OFFER_EXPLANATION = "offer_explanation"


_PROMPTS: dict[PromptKey, tuple[str, str]] = {
    PromptKey.VOICE_AGENT: ("boloride-voice-agent", "voice_agent.md"),
    PromptKey.LOCATION_CLARIFICATION: (
        "boloride-location-clarification",
        "location_clarification.md",
    ),
    PromptKey.BOOKING_CONFIRMATION: (
        "boloride-booking-confirmation",
        "booking_confirmation.md",
    ),
    PromptKey.ERROR_RECOVERY: ("boloride-error-recovery", "error_recovery.md"),
    PromptKey.OFFER_EXPLANATION: (
        "boloride-offer-explanation",
        "offer_explanation.md",
    ),
}


class PromptRegistry:
    def __init__(
        self,
        client: PromptClient,
        *,
        label: str,
        fallback_enabled: bool = True,
        fallback_directory: Path | None = None,
    ) -> None:
        self._client = client
        self._label = label
        self._fallback_enabled = fallback_enabled
        self._fallback_directory = fallback_directory or Path(__file__).parent / "fallback"

    def get(self, key: PromptKey) -> ResolvedPrompt:
        name, fallback_filename = _PROMPTS[key]
        fetch = self._client.fetch_text_prompt(name, self._label)
        if fetch.status is PromptFetchStatus.AVAILABLE:
            assert fetch.prompt is not None
            return ResolvedPrompt(
                name=name,
                content=fetch.prompt.content,
                source="langfuse",
                label=self._label,
                version=fetch.prompt.version,
            )

        if not self._fallback_enabled:
            raise PromptUnavailableError(
                f"prompt '{name}' is unavailable (remote: {fetch.status.value}; fallback: disabled)"
            )

        fallback_path = self._fallback_directory / fallback_filename
        try:
            content = fallback_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PromptUnavailableError(
                f"prompt '{name}' is unavailable (remote: {fetch.status.value}; fallback: missing)"
            ) from exc
        if not content:
            raise PromptUnavailableError(
                f"prompt '{name}' is unavailable (remote: {fetch.status.value}; fallback: empty)"
            )

        _safe_log(
            "warning",
            "prompt_fallback_used",
            extra={
                "event": "prompt_fallback_used",
                "prompt_name": name,
                "prompt_label": self._label,
                "prompt_source": "fallback",
            },
        )
        return ResolvedPrompt(
            name=name,
            content=content,
            source="fallback",
            label=self._label,
        )


def _safe_log(level: str, message: str, *, extra: dict[str, object]) -> None:
    try:
        getattr(logger, level)(message, extra=extra)
    except Exception:
        pass
