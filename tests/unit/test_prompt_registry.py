from pathlib import Path
from unittest.mock import Mock

import pytest

from boloride.prompts.client import (
    PromptFetchResult,
    PromptFetchStatus,
    PromptUnavailableError,
    RemotePrompt,
)
from boloride.prompts.registry import PromptKey, PromptRegistry


def test_selected_voice_agent_fallback_matches_candidate_4_exactly() -> None:
    prompt_directory = Path(__file__).parents[2] / "src" / "boloride" / "prompts"
    candidate = prompt_directory / "candidates" / "voice_agent_v5.md"
    fallback = prompt_directory / "fallback" / "voice_agent.md"

    assert candidate.read_bytes() == fallback.read_bytes()


def test_registry_returns_managed_prompt_and_version() -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(
        PromptFetchStatus.AVAILABLE,
        RemotePrompt("managed", 4),
    )
    registry = PromptRegistry(client, label="production")

    prompt = registry.get(PromptKey.VOICE_AGENT)

    assert prompt.content == "managed"
    assert prompt.source == "langfuse"
    assert prompt.version == 4
    assert prompt.label == "production"

    client.fetch_text_prompt.assert_called_once_with(
        "boloride-voice-agent",
        "production",
    )


def test_registry_loads_fallback_when_remote_is_unavailable(
    tmp_path: Path,
) -> None:
    (tmp_path / "voice_agent.md").write_text(
        "local fallback",
        encoding="utf-8",
    )

    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(
        PromptFetchStatus.UNAVAILABLE
    )

    registry = PromptRegistry(
        client,
        label="development",
        fallback_directory=tmp_path,
    )

    prompt = registry.get(PromptKey.VOICE_AGENT)

    assert prompt.content == "local fallback"
    assert prompt.source == "fallback"
    assert prompt.version is None
    assert prompt.label == "development"


def test_all_prompt_set_v1_fallbacks_are_registered_and_nonempty() -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(
        PromptFetchStatus.NOT_CONFIGURED
    )

    registry = PromptRegistry(
        client,
        label="development",
    )

    resolved = {
        key: registry.get(key)
        for key in PromptKey
    }

    assert set(resolved) == set(PromptKey)

    for prompt in resolved.values():
        assert prompt.source == "fallback"
        assert prompt.content.strip()
        assert prompt.version is None


def test_registry_raises_when_fallback_file_is_missing(
    tmp_path: Path,
) -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(
        PromptFetchStatus.UNAVAILABLE
    )

    registry = PromptRegistry(
        client,
        label="development",
        fallback_directory=tmp_path,
    )

    with pytest.raises(
        PromptUnavailableError,
        match="fallback: missing",
    ):
        registry.get(PromptKey.VOICE_AGENT)


def test_registry_rejects_whitespace_only_fallback(
    tmp_path: Path,
) -> None:
    (tmp_path / "voice_agent.md").write_text(
        "  \n",
        encoding="utf-8",
    )

    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(
        PromptFetchStatus.UNAVAILABLE
    )

    registry = PromptRegistry(
        client,
        label="development",
        fallback_directory=tmp_path,
    )

    with pytest.raises(
        PromptUnavailableError,
        match="fallback: empty",
    ):
        registry.get(PromptKey.VOICE_AGENT)


def test_registry_raises_when_fallback_is_disabled() -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(
        PromptFetchStatus.UNAVAILABLE
    )

    registry = PromptRegistry(
        client,
        label="production",
        fallback_enabled=False,
    )

    with pytest.raises(
        PromptUnavailableError,
        match="fallback: disabled",
    ):
        registry.get(PromptKey.VOICE_AGENT)


def test_logging_failure_does_not_break_valid_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(
        PromptFetchStatus.NOT_CONFIGURED
    )

    monkeypatch.setattr(
        "boloride.prompts.registry.logger.warning",
        Mock(side_effect=RuntimeError("logging failed")),
    )

    prompt = PromptRegistry(
        client,
        label="development",
    ).get(PromptKey.VOICE_AGENT)

    assert prompt.source == "fallback"
    assert prompt.content.strip()


def test_bundle_reports_langfuse_when_all_prompts_are_remote() -> None:
    client = Mock()

    versions = {
        "boloride-voice-agent": 1,
        "boloride-location-clarification": 2,
        "boloride-booking-confirmation": 3,
        "boloride-error-recovery": 4,
        "boloride-offer-explanation": 5,
    }

    def fetch_prompt(
        name: str,
        label: str,
    ) -> PromptFetchResult:
        assert label == "production"

        return PromptFetchResult(
            PromptFetchStatus.AVAILABLE,
            RemotePrompt(
                content=f"managed:{name}",
                version=versions[name],
            ),
        )

    client.fetch_text_prompt.side_effect = fetch_prompt

    bundle = PromptRegistry(
        client,
        label="production",
    ).get_bundle()

    assert bundle.source == "langfuse"

    assert bundle.voice_agent.source == "langfuse"
    assert bundle.location_clarification.source == "langfuse"
    assert bundle.booking_confirmation.source == "langfuse"
    assert bundle.error_recovery.source == "langfuse"
    assert bundle.offer_explanation.source == "langfuse"

    assert bundle.voice_agent.version == 1
    assert bundle.location_clarification.version == 2
    assert bundle.booking_confirmation.version == 3
    assert bundle.error_recovery.version == 4
    assert bundle.offer_explanation.version == 5

    assert client.fetch_text_prompt.call_count == 5


def test_bundle_reports_fallback_when_all_remote_prompts_are_unavailable() -> None:
    client = Mock()
    client.fetch_text_prompt.return_value = PromptFetchResult(
        PromptFetchStatus.NOT_CONFIGURED
    )

    bundle = PromptRegistry(
        client,
        label="development",
    ).get_bundle()

    assert bundle.source == "fallback"

    assert bundle.voice_agent.source == "fallback"
    assert bundle.location_clarification.source == "fallback"
    assert bundle.booking_confirmation.source == "fallback"
    assert bundle.error_recovery.source == "fallback"
    assert bundle.offer_explanation.source == "fallback"

    assert bundle.voice_agent.content.strip()
    assert bundle.location_clarification.content.strip()
    assert bundle.booking_confirmation.content.strip()
    assert bundle.error_recovery.content.strip()
    assert bundle.offer_explanation.content.strip()

    assert client.fetch_text_prompt.call_count == 5


def test_bundle_reports_mixed_when_only_some_prompts_use_fallback(
    tmp_path: Path,
) -> None:
    fallback_content = "fallback location policy"

    (tmp_path / "location_clarification.md").write_text(
        fallback_content,
        encoding="utf-8",
    )

    client = Mock()

    def fetch_prompt(
        name: str,
        label: str,
    ) -> PromptFetchResult:
        assert label == "production"

        if name == "boloride-location-clarification":
            return PromptFetchResult(
                PromptFetchStatus.UNAVAILABLE
            )

        return PromptFetchResult(
            PromptFetchStatus.AVAILABLE,
            RemotePrompt(
                content=f"managed:{name}",
                version=7,
            ),
        )

    client.fetch_text_prompt.side_effect = fetch_prompt

    bundle = PromptRegistry(
        client,
        label="production",
        fallback_directory=tmp_path,
    ).get_bundle()

    assert bundle.source == "mixed"

    assert bundle.voice_agent.source == "langfuse"
    assert bundle.location_clarification.source == "fallback"
    assert bundle.booking_confirmation.source == "langfuse"
    assert bundle.error_recovery.source == "langfuse"
    assert bundle.offer_explanation.source == "langfuse"

    assert bundle.location_clarification.content == fallback_content


def test_bundle_contains_all_five_prompt_roles() -> None:
    client = Mock()

    def fetch_prompt(
        name: str,
        label: str,
    ) -> PromptFetchResult:
        return PromptFetchResult(
            PromptFetchStatus.AVAILABLE,
            RemotePrompt(
                content=f"content-for:{name}",
                version=1,
            ),
        )

    client.fetch_text_prompt.side_effect = fetch_prompt

    bundle = PromptRegistry(
        client,
        label="development",
    ).get_bundle()

    assert bundle.voice_agent.name == "boloride-voice-agent"
    assert (
        bundle.location_clarification.name
        == "boloride-location-clarification"
    )
    assert (
        bundle.booking_confirmation.name
        == "boloride-booking-confirmation"
    )
    assert bundle.error_recovery.name == "boloride-error-recovery"
    assert bundle.offer_explanation.name == "boloride-offer-explanation"

    assert bundle.voice_agent.content == (
        "content-for:boloride-voice-agent"
    )
    assert bundle.location_clarification.content == (
        "content-for:boloride-location-clarification"
    )
    assert bundle.booking_confirmation.content == (
        "content-for:boloride-booking-confirmation"
    )
    assert bundle.error_recovery.content == (
        "content-for:boloride-error-recovery"
    )
    assert bundle.offer_explanation.content == (
        "content-for:boloride-offer-explanation"
    )
