from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "BoloRide"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json"] = "json"

    database_url: str
    database_connect_timeout_seconds: float = Field(default=3.0, gt=0)
    provider_call_lease_seconds: int = Field(default=30, gt=0, le=300)

    langfuse_enabled: bool = False
    langfuse_host: str = "http://langfuse-web:3000"
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_prompt_label: str = "development"
    langfuse_prompt_cache_ttl_seconds: int = Field(default=300, ge=0)
    langfuse_timeout_seconds: int = Field(default=5, gt=0)
    prompt_fallback_enabled: bool = True

    llm_primary_provider: Literal["google", "groq"] = "google"
    llm_primary_model: str | None = None
    llm_fallback_1_provider: Literal["google", "groq"] | None = "google"
    llm_fallback_1_model: str | None = None
    llm_fallback_2_provider: Literal["google", "groq"] | None = "groq"
    llm_fallback_2_model: str | None = None
    llm_timeout_seconds: float = Field(default=15.0, gt=0)
    llm_max_retries: int = Field(default=1, ge=0, le=2)
    google_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None

    maps_provider: Literal["google", "ola"] = "ola"
    google_maps_api_key: SecretStr | None = None
    ola_maps_api_key: SecretStr | None = None
    maps_timeout_seconds: float = Field(default=10.0, gt=0)
    maps_max_candidates: int = Field(default=5, ge=1, le=40)
    maps_urban_context_radius_meters: int = Field(default=1000, gt=0)
    maps_rural_context_radius_meters: int = Field(default=20000, gt=0)
    default_city: str | None = None
    default_state: str | None = None
    default_country: str = "IN"
    default_language: str = "en"
    default_timezone: str = "Asia/Kolkata"

    # LiveKit
    livekit_url: str | None = None
    livekit_api_key: SecretStr | None = None
    livekit_api_secret: SecretStr | None = None
    livekit_agent_name: str = "boloride-dev"
    development_caller_phone: str | None = None

    # STT
    stt_provider: Literal["assemblyai", "groq"] = "assemblyai"
    assemblyai_api_key: SecretStr | None = None
    assemblyai_stt_model: str = "universal-streaming-multilingual"
    stt_language: str | None = None

    # TTS
    tts_provider: Literal["edge"] = "edge"
    tts_voice: str = "hi-IN-SwaraNeural"
    local_tts_model: str = "hi-IN-SwaraNeural"
    local_tts_device: str = "cpu"

    @field_validator("database_url")
    @classmethod
    def require_async_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg")
        return value

    @model_validator(mode="after")
    def require_langfuse_credentials_when_enabled(self) -> "Settings":
        if self.langfuse_enabled and (
            self.langfuse_public_key is None or self.langfuse_secret_key is None
        ):
            raise ValueError(
                "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required when Langfuse is enabled"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
