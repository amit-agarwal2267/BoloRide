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
