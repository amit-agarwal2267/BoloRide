from boloride.config import Settings
from boloride.domain.exceptions import DomainValidationError
from boloride.speech.tts.base import TTSProvider
from boloride.speech.tts.local_tts import EdgeTTSProvider


class TTSRouter:
    def __init__(self, settings: Settings, *, voice: str | None = None) -> None:
        if settings.tts_provider != "edge":
            raise DomainValidationError(f"unsupported TTS_PROVIDER: {settings.tts_provider}")
        self._provider: TTSProvider = EdgeTTSProvider(settings, voice=voice)

    def get_provider(self) -> TTSProvider:
        return self._provider
