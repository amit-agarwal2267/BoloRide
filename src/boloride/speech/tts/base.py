from typing import Protocol

from livekit.agents import tts


class TTSProvider(Protocol):
    provider_name: str

    def get_livekit_tts(self) -> tts.TTS: ...
