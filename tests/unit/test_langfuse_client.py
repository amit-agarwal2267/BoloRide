from types import SimpleNamespace
from unittest.mock import Mock

from boloride.config import Settings
from boloride.integrations.langfuse.client import LangfuseClient


def enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@postgres/db",
        langfuse_enabled=True,
        langfuse_public_key="public",
        langfuse_secret_key="secret",
        langfuse_prompt_label="development",
        langfuse_prompt_cache_ttl_seconds=123,
    )


def test_fetch_text_prompt_respects_label_and_sdk_cache() -> None:
    sdk = Mock()
    sdk.get_prompt.return_value = SimpleNamespace(prompt="managed prompt", version=7)
    client = LangfuseClient(enabled_settings(), sdk_client=sdk)

    prompt = client.fetch_text_prompt("boloride-voice-agent", "development")

    assert prompt.content == "managed prompt"
    assert prompt.version == 7
    sdk.get_prompt.assert_called_once_with(
        "boloride-voice-agent",
        label="development",
        type="text",
        cache_ttl_seconds=123,
        fetch_timeout_seconds=5,
    )


def test_fetch_failure_is_translated_to_unavailable() -> None:
    sdk = Mock()
    sdk.get_prompt.side_effect = ConnectionError("unavailable")
    client = LangfuseClient(enabled_settings(), sdk_client=sdk)
    assert client.fetch_text_prompt("prompt", "development") is None


def test_disabled_client_never_calls_sdk() -> None:
    settings = enabled_settings().model_copy(update={"langfuse_enabled": False})
    sdk = Mock()
    client = LangfuseClient(settings, sdk_client=sdk)
    assert client.fetch_text_prompt("prompt", "development") is None
    assert client.is_available() is False
    sdk.assert_not_called()
