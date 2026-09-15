from boloride.config import Settings
from boloride.domain.exceptions import DomainValidationError
from boloride.speech.tts.base import TTSProvider
from boloride.speech.tts.local_tts import EdgeTTSProvider
from boloride.speech.tts.sarvam import SarvamTTSProvider


class TTSRouter:
    def __init__(
        self, settings: Settings, *, voice: str | None = None, speaker: str | None = None
    ) -> None:
        if settings.tts_provider == "sarvam":
            self._provider: TTSProvider = SarvamTTSProvider(
                settings, speaker=speaker, edge_voice=voice
            )
        elif settings.tts_provider == "edge":
            self._provider = EdgeTTSProvider(settings, voice=voice)
        else:
            raise DomainValidationError(
                f"unsupported TTS_PROVIDER: {settings.tts_provider}"
            )

    def get_provider(self) -> TTSProvider:
        return self._provider
