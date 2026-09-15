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

    llm_primary_provider: Literal["google", "groq", "openai"] = "google"
    llm_primary_model: str | None = None
    llm_fallback_1_provider: Literal["google", "groq", "openai"] | None = "google"
    llm_fallback_1_model: str | None = None
    llm_fallback_2_provider: Literal["google", "groq", "openai"] | None = "groq"
    llm_fallback_2_model: str | None = None
    llm_timeout_seconds: float = Field(default=15.0, gt=0)
    llm_max_retries: int = Field(default=1, ge=0, le=2)
    google_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    maps_provider: Literal["google", "ola"] = "ola"
    google_maps_api_key: SecretStr | None = None
    ola_maps_api_key: SecretStr | None = None
    maps_timeout_seconds: float = Field(default=10.0, gt=0)
    maps_max_candidates: int = Field(default=5, ge=1, le=40)
    maps_urban_context_radius_meters: int = Field(default=1000, gt=0)
    maps_rural_context_radius_meters: int = Field(default=20000, gt=0)
    default_country: str = "IN"
    default_language: str = "en"
    default_timezone: str = "Asia/Kolkata"

    # LiveKit
    livekit_url: str | None = None
    livekit_api_key: SecretStr | None = None
    livekit_api_secret: SecretStr | None = None
    livekit_agent_name: str = "boloride-dev"
    development_caller_phone: str | None = None
    telephony_provider: Literal["console", "browser", "twilio", "exotel"] = "console"
    livekit_sip_trunk_id: str | None = None
    browser_demo_caller_phone: str | None = None

    # STT
    stt_provider: Literal["assemblyai", "groq"] = "assemblyai"
    assemblyai_api_key: SecretStr | None = None
    assemblyai_stt_model: str = "universal-streaming-multilingual"
    stt_language: str | None = None

    # TTS
    tts_provider: Literal["sarvam", "edge"] = "sarvam"
    tts_voice: str = "hi-IN-SwaraNeural"
    tts_male_voice: str = "hi-IN-MadhurNeural"
    tts_female_voice: str = "hi-IN-SwaraNeural"
    sarvam_api_key: SecretStr | None = None
    sarvam_tts_model: Literal["bulbul:v3"] = "bulbul:v3"
    sarvam_tts_language: str = "hi-IN"
    sarvam_tts_pace: float = Field(default=1.0, ge=0.5, le=2.0)
    sarvam_tts_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    sarvam_tts_male_speaker: str = "amit"
    sarvam_tts_female_speaker: str = "ritu"
    tts_persona: str = "auto"

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
        if self.telephony_provider in {"twilio", "exotel"} and not self.livekit_sip_trunk_id:
            raise ValueError(
                "LIVEKIT_SIP_TRUNK_ID is required for SIP telephony providers"
            )
        if self.telephony_provider == "browser" and not self.browser_demo_caller_phone:
            raise ValueError(
                "BROWSER_DEMO_CALLER_PHONE is required for browser demo mode"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
