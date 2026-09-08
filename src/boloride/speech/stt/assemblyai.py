from livekit.agents import stt
from livekit.plugins import assemblyai

from boloride.config import Settings
from boloride.domain.exceptions import DomainValidationError


class AssemblyAIProvider:
    provider_name = "assemblyai"

    def __init__(self, settings: Settings) -> None:
        key = settings.assemblyai_api_key
        if key is None or not key.get_secret_value().strip():
            raise DomainValidationError("ASSEMBLYAI_API_KEY is required for AssemblyAI STT")
        self._api_key = key.get_secret_value()
        self._model = settings.assemblyai_stt_model
        self._language = settings.stt_language

    def get_livekit_stt(self) -> stt.STT:
        options: dict[str, object] = {
            "api_key": self._api_key,
            "model": self._model,
        }
        if self._language:
            options["language_codes"] = [self._language]
        return assemblyai.STT(**options)
