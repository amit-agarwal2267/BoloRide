from boloride.config import Settings
from boloride.domain.exceptions import DomainValidationError
from boloride.speech.stt.assemblyai import AssemblyAIProvider
from boloride.speech.stt.base import STTProvider


class STTRouter:
    def __init__(self, settings: Settings) -> None:
        if settings.stt_provider == "assemblyai":
            self._provider: STTProvider = AssemblyAIProvider(settings)
        else:
            raise DomainValidationError(
                "Groq Whisper is batch-only and cannot drive a LiveKit realtime session"
            )

    def get_provider(self) -> STTProvider:
        return self._provider
