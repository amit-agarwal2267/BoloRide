import logging
from enum import StrEnum
from pathlib import Path

from boloride.prompts.client import (
    PromptClient,
    PromptUnavailableError,
    ResolvedPrompt,
)

logger = logging.getLogger(__name__)


class PromptKey(StrEnum):
    VOICE_AGENT = "voice_agent"
    LOCATION_CLARIFICATION = "location_clarification"
    BOOKING_CONFIRMATION = "booking_confirmation"
    ERROR_RECOVERY = "error_recovery"


_PROMPTS: dict[PromptKey, tuple[str, str | None]] = {
    PromptKey.VOICE_AGENT: ("boloride-voice-agent", "system_prompt.txt"),
    PromptKey.LOCATION_CLARIFICATION: (
        "boloride-location-clarification",
        "location_prompt.txt",
    ),
    PromptKey.BOOKING_CONFIRMATION: (
        "boloride-booking-confirmation",
        "booking_prompt.txt",
    ),
    PromptKey.ERROR_RECOVERY: ("boloride-error-recovery", None),
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
        remote = self._client.fetch_text_prompt(name, self._label)
        if remote is not None:
            return ResolvedPrompt(
                name=name,
                content=remote.content,
                source="langfuse",
                label=self._label,
                version=remote.version,
            )

        if not self._fallback_enabled or fallback_filename is None:
            raise PromptUnavailableError(f"prompt '{name}' is unavailable")

        fallback_path = self._fallback_directory / fallback_filename
        try:
            content = fallback_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PromptUnavailableError(f"fallback for prompt '{name}' is unavailable") from exc
        if not content:
            raise PromptUnavailableError(f"fallback for prompt '{name}' is empty")

        logger.warning(
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
