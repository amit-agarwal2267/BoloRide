import logging
from typing import Any

import httpx
from langfuse import Langfuse
from langfuse.api.commons.errors import NotFoundError
from langfuse.api.core.api_error import ApiError

from boloride.config import Settings
from boloride.prompts.client import PromptFetchResult, PromptFetchStatus, RemotePrompt

logger = logging.getLogger(__name__)


class LangfuseClient:
    """The only application boundary that constructs the official SDK client."""

    def __init__(self, settings: Settings, sdk_client: Any | None = None) -> None:
        self._settings = settings
        if not settings.langfuse_enabled:
            self._client = None
        elif sdk_client is not None:
            self._client = sdk_client
        else:
            assert settings.langfuse_public_key is not None
            assert settings.langfuse_secret_key is not None
            self._client = Langfuse(
                public_key=settings.langfuse_public_key.get_secret_value(),
                secret_key=settings.langfuse_secret_key.get_secret_value(),
                base_url=settings.langfuse_host,
                timeout=settings.langfuse_timeout_seconds,
                environment=settings.app_env,
                tracing_enabled=True,
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def fetch_text_prompt(self, name: str, label: str) -> PromptFetchResult:
        if self._client is None:
            _safe_log(
                "info",
                "langfuse_prompt_fetch_skipped",
                extra={"event": "langfuse_prompt_fetch_skipped", "prompt_name": name, "prompt_label": label, "reason": "not_configured"},
            )
            return PromptFetchResult(PromptFetchStatus.NOT_CONFIGURED)
        try:
            prompt = self._client.get_prompt(
                name,
                label=label,
                type="text",
                cache_ttl_seconds=self._settings.langfuse_prompt_cache_ttl_seconds,
                fetch_timeout_seconds=self._settings.langfuse_timeout_seconds,
            )
        except NotFoundError:
            _safe_log(
                "warning",
                "langfuse_prompt_not_found",
                extra={"event": "langfuse_prompt_not_found", "prompt_name": name, "prompt_label": label},
            )
            return PromptFetchResult(PromptFetchStatus.NOT_FOUND)
        except (ApiError, httpx.HTTPError, ConnectionError, TimeoutError) as exc:
            _safe_log(
                "warning",
                "langfuse_prompt_fetch_failed",
                extra={
                    "event": "langfuse_prompt_fetch_failed",
                    "prompt_name": name,
                    "prompt_label": label,
                    "error_type": type(exc).__name__,
                },
            )
            return PromptFetchResult(PromptFetchStatus.UNAVAILABLE)
        content = getattr(prompt, "prompt", None)
        version = getattr(prompt, "version", None)
        if not isinstance(content, str) or not content.strip() or not isinstance(version, int):
            _safe_log(
                "warning",
                "langfuse_prompt_invalid",
                extra={"event": "langfuse_prompt_invalid", "prompt_name": name, "prompt_label": label},
            )
            return PromptFetchResult(PromptFetchStatus.INVALID)
        return PromptFetchResult(
            PromptFetchStatus.AVAILABLE,
            RemotePrompt(content=content, version=version),
        )

    def is_available(self) -> bool:
        if self._client is None:
            return False
        try:
            return bool(self._client.auth_check())
        except Exception as exc:
            logger.warning(
                "langfuse_auth_check_failed",
                extra={
                    "event": "langfuse_auth_check_failed",
                    "error_type": type(exc).__name__,
                },
            )
            return False

    def shutdown(self) -> None:
        if self._client is None:
            return
        try:
            self._client.shutdown()
        except Exception as exc:
            logger.warning(
                "langfuse_shutdown_failed",
                extra={
                    "event": "langfuse_shutdown_failed",
                    "error_type": type(exc).__name__,
                },
            )


def _safe_log(level: str, message: str, *, extra: dict[str, object]) -> None:
    try:
        getattr(logger, level)(message, extra=extra)
    except Exception:
        pass
