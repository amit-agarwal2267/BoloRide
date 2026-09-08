from io import BytesIO
from time import perf_counter
from typing import Any

from groq import AsyncGroq

from boloride.config import Settings
from boloride.domain.exceptions import DomainValidationError
from boloride.speech.stt.base import TranscriptResult


class GroqWhisperProvider:
    provider_name = "groq"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        key = settings.groq_api_key
        if key is None or not key.get_secret_value().strip():
            raise DomainValidationError("GROQ_API_KEY is required for Groq Whisper")
        self._client = client or AsyncGroq(api_key=key.get_secret_value(), max_retries=0)

    async def transcribe(self, audio: bytes, *, model: str = "whisper-large-v3-turbo", language: str | None = None) -> TranscriptResult:
        if not audio:
            raise DomainValidationError("audio must not be empty")
        source = BytesIO(audio)
        source.name = "audio.wav"
        options: dict[str, object] = {"file": source, "model": model, "response_format": "verbose_json"}
        if language:
            options["language"] = language
        started = perf_counter()
        result = await self._client.audio.transcriptions.create(**options)
        del started
        return TranscriptResult(text=result.text.strip(), is_final=True, provider=self.provider_name, language=getattr(result, "language", language))
