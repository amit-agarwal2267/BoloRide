from pathlib import Path
from unittest.mock import Mock

import pytest

from boloride.prompts.client import PromptFetchResult, PromptFetchStatus, PromptUnavailableError, RemotePrompt
from boloride.prompts.registry import PromptKey, PromptRegistry


def test_registry_returns_managed_prompt_and_version() -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(PromptFetchStatus.AVAILABLE, RemotePrompt("managed", 4))
    registry = PromptRegistry(client, label="production")

    prompt = registry.get(PromptKey.VOICE_AGENT)

    assert prompt.content == "managed"
    assert prompt.source == "langfuse"
    assert prompt.version == 4
    client.fetch_text_prompt.assert_called_once_with(
        "boloride-voice-agent", "production"
    )


def test_registry_loads_fallback_when_remote_is_unavailable(tmp_path: Path) -> None:
    (tmp_path / "voice_agent.md").write_text("local fallback", encoding="utf-8")
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(PromptFetchStatus.UNAVAILABLE)
    registry = PromptRegistry(
        client, label="development", fallback_directory=tmp_path
    )

    prompt = registry.get(PromptKey.VOICE_AGENT)

    assert prompt.content == "local fallback"
    assert prompt.source == "fallback"
    assert prompt.version is None


def test_all_prompt_set_v1_fallbacks_are_registered_and_nonempty() -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(PromptFetchStatus.NOT_CONFIGURED)
    registry = PromptRegistry(client, label="development")
    for key in PromptKey:
        prompt = registry.get(key)
        assert prompt.source == "fallback"
        assert prompt.content.strip()


def test_registry_raises_when_fallback_file_is_missing(tmp_path: Path) -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(PromptFetchStatus.UNAVAILABLE)
    registry = PromptRegistry(
        client, label="development", fallback_directory=tmp_path
    )
    with pytest.raises(PromptUnavailableError):
        registry.get(PromptKey.VOICE_AGENT)


def test_registry_rejects_whitespace_only_fallback(tmp_path: Path) -> None:
    (tmp_path / "voice_agent.md").write_text("  \n", encoding="utf-8")
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(PromptFetchStatus.UNAVAILABLE)
    registry = PromptRegistry(client, label="development", fallback_directory=tmp_path)
    with pytest.raises(PromptUnavailableError, match="fallback: empty"):
        registry.get(PromptKey.VOICE_AGENT)


def test_logging_failure_does_not_break_valid_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(PromptFetchStatus.NOT_CONFIGURED)
    monkeypatch.setattr("boloride.prompts.registry.logger.warning", Mock(side_effect=RuntimeError("logging failed")))
    assert PromptRegistry(client, label="development").get(PromptKey.VOICE_AGENT).source == "fallback"
