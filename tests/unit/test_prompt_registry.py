from pathlib import Path
from unittest.mock import Mock

import pytest

from boloride.prompts.client import PromptUnavailableError, RemotePrompt
from boloride.prompts.registry import PromptKey, PromptRegistry


def test_registry_returns_managed_prompt_and_version() -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = RemotePrompt("managed", 4)
    registry = PromptRegistry(client, label="production")

    prompt = registry.get(PromptKey.VOICE_AGENT)

    assert prompt.content == "managed"
    assert prompt.source == "langfuse"
    assert prompt.version == 4
    client.fetch_text_prompt.assert_called_once_with(
        "boloride-voice-agent", "production"
    )


def test_registry_loads_fallback_when_remote_is_unavailable(tmp_path: Path) -> None:
    (tmp_path / "system_prompt.txt").write_text("local fallback", encoding="utf-8")
    client = Mock()
    client.fetch_text_prompt.return_value = None
    registry = PromptRegistry(
        client, label="development", fallback_directory=tmp_path
    )

    prompt = registry.get(PromptKey.VOICE_AGENT)

    assert prompt.content == "local fallback"
    assert prompt.source == "fallback"
    assert prompt.version is None


def test_registry_raises_when_no_fallback_is_registered() -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = None
    registry = PromptRegistry(client, label="development")
    with pytest.raises(PromptUnavailableError):
        registry.get(PromptKey.ERROR_RECOVERY)


def test_registry_raises_when_fallback_file_is_missing(tmp_path: Path) -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = None
    registry = PromptRegistry(
        client, label="development", fallback_directory=tmp_path
    )
    with pytest.raises(PromptUnavailableError):
        registry.get(PromptKey.VOICE_AGENT)
