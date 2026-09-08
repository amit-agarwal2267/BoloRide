from dataclasses import dataclass
from typing import Protocol

from livekit.agents import stt


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    text: str
    is_final: bool
    provider: str
    language: str | None = None
    confidence: float | None = None


class STTProvider(Protocol):
    provider_name: str

    def get_livekit_stt(self) -> stt.STT: ...


def normalize_speech_event(event: stt.SpeechEvent, provider: str) -> TranscriptResult | None:
    if event.type not in {stt.SpeechEventType.INTERIM_TRANSCRIPT, stt.SpeechEventType.FINAL_TRANSCRIPT}:
        return None
    if not event.alternatives:
        return None
    alternative = event.alternatives[0]
    text = alternative.text.strip()
    if not text:
        return None
    language = str(alternative.language) if alternative.language else None
    return TranscriptResult(text=text, is_final=event.type == stt.SpeechEventType.FINAL_TRANSCRIPT, provider=provider, language=language, confidence=alternative.confidence)
