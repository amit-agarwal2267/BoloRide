import pytest
from pydantic import ValidationError

from boloride.config import Settings


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_url_requires_asyncpg() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://user:password@postgres/database",
        )


def test_typed_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@postgres/db")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "2.5")

    settings = Settings(_env_file=None)

    assert settings.debug is True
    assert settings.database_connect_timeout_seconds == 2.5


def test_enabled_langfuse_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://u:p@postgres/db",
            langfuse_enabled=True,
        )


def test_disabled_langfuse_does_not_require_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@postgres/db",
        langfuse_enabled=False,
    )
    assert settings.langfuse_public_key is None


def test_telephony_provider_defaults_to_console_and_accepts_twilio() -> None:
    defaults = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@postgres/db",
    )
    twilio = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@postgres/db",
        telephony_provider="twilio",
        livekit_sip_trunk_id="trunk-1",
    )

    assert defaults.telephony_provider == "console"
    assert twilio.telephony_provider == "twilio"


@pytest.mark.parametrize("provider", ["twilio", "exotel"])
def test_sip_provider_requires_trunk_id(provider: str) -> None:
    with pytest.raises(ValidationError, match="LIVEKIT_SIP_TRUNK_ID"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://u:p@postgres/db",
            telephony_provider=provider,
        )


def test_browser_provider_requires_server_owned_demo_phone() -> None:
    with pytest.raises(ValidationError, match="BROWSER_DEMO_CALLER_PHONE"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://u:p@postgres/db",
            telephony_provider="browser",
        )
