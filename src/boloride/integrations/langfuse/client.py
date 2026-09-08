import logging
from typing import Any

from langfuse import Langfuse

from boloride.config import Settings
from boloride.prompts.client import RemotePrompt

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

    def fetch_text_prompt(self, name: str, label: str) -> RemotePrompt | None:
        if self._client is None:
            return None
        try:
            prompt = self._client.get_prompt(
                name,
                label=label,
                type="text",
                cache_ttl_seconds=self._settings.langfuse_prompt_cache_ttl_seconds,
                fetch_timeout_seconds=self._settings.langfuse_timeout_seconds,
            )
            return RemotePrompt(content=prompt.prompt, version=prompt.version)
        except Exception as exc:
            logger.warning(
                "langfuse_prompt_fetch_failed",
                extra={
                    "event": "langfuse_prompt_fetch_failed",
                    "prompt_name": name,
                    "prompt_label": label,
                    "error_type": type(exc).__name__,
                },
            )
            return None

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
