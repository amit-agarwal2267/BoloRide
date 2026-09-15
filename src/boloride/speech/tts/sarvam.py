import base64
import binascii
from io import BytesIO
import logging
from time import monotonic
import wave

import httpx
from livekit.agents import APIConnectOptions, APIConnectionError, tts, utils

from boloride.config import Settings
from boloride.observability.tracing import get_observability_context
from boloride.services.speech_normalizer import normalize_for_speech
from boloride.speech.tts.local_tts import synthesize_edge_pcm


logger = logging.getLogger(__name__)
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"


def _linear16_pcm(encoded: str) -> bytes:
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise APIConnectionError("Sarvam TTS returned malformed audio") from exc
    if audio.startswith(b"RIFF"):
        try:
            with wave.open(BytesIO(audio), "rb") as wav:
                if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 24000:
                    raise APIConnectionError("Sarvam TTS returned an incompatible audio format")
                audio = wav.readframes(wav.getnframes())
        except wave.Error as exc:
            raise APIConnectionError("Sarvam TTS returned malformed WAV audio") from exc
    if not audio or len(audio) % 2:
        raise APIConnectionError("Sarvam TTS returned invalid linear PCM audio")
    return audio


def _failure_category(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 429:
            return "rate_limited"
        if exc.response.status_code in {401, 403}:
            return "authentication_or_billing"
        return "provider_rejected"
    if isinstance(exc, httpx.HTTPError):
        return "network"
    return "malformed_response"


class SarvamTTS(tts.TTS):
    def __init__(
        self, *, api_key: str, model: str, speaker: str, language: str, pace: float,
        edge_voice: str, timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1)
        self.api_key = api_key
        self.model_name = model
        self.speaker = speaker
        self.language = language
        self.pace = pace
        self.edge_voice = edge_voice
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    @property
    def provider(self) -> str:
        return "sarvam"

    @property
    def model(self) -> str:
        return self.model_name

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = APIConnectOptions()) -> tts.ChunkedStream:
        return SarvamChunkedStream(
            tts=self, input_text=normalize_for_speech(text), conn_options=conn_options
        )

    async def _synthesize_pcm(self, text: str) -> bytes:
        response = await self._client.post(
            SARVAM_TTS_URL,
            headers={"api-subscription-key": self.api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "target_language_code": self.language,
                "speaker": self.speaker,
                "model": self.model_name,
                "pace": self.pace,
                "speech_sample_rate": 24000,
                "output_audio_codec": "linear16",
            },
        )
        response.raise_for_status()
        try:
            audios = response.json()["audios"]
            encoded = audios[0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise APIConnectionError("Sarvam TTS returned an invalid response") from exc
        if not isinstance(encoded, str):
            raise APIConnectionError("Sarvam TTS returned an invalid response")
        return _linear16_pcm(encoded)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class SarvamChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        engine: SarvamTTS = self._tts  # type: ignore[assignment]
        started = monotonic()
        fallback_used = False
        failure_category: str | None = None
        try:
            pcm = await engine._synthesize_pcm(self.input_text)
        except Exception as exc:
            fallback_used = True
            failure_category = _failure_category(exc)
            logger.warning(
                "sarvam_tts_fallback",
                extra={"event": "sarvam_tts_fallback", "failure_category": failure_category},
            )
            try:
                pcm = await synthesize_edge_pcm(self.input_text, engine.edge_voice)
            except Exception as fallback_exc:
                raise APIConnectionError("TTS providers were unavailable") from fallback_exc
        duration_ms = (monotonic() - started) * 1000
        output_emitter.initialize(
            request_id=utils.shortuuid(), sample_rate=24000, num_channels=1,
            mime_type="audio/pcm", frame_size_ms=20,
        )
        output_emitter.push(pcm)
        observability = get_observability_context()
        if observability is not None:
            observability.record_event(
                "voice.tts",
                metadata={
                    "tts_provider": "edge" if fallback_used else "sarvam",
                    "tts_model": engine.model_name,
                    "tts_speaker": engine.speaker,
                    "tts_language": engine.language,
                    "text_length": len(self.input_text),
                    "synthesis_duration_ms": duration_ms,
                    "fallback_used": fallback_used,
                    "fallback_provider": "edge" if fallback_used else None,
                    "failure_category": failure_category,
                },
            )


class SarvamTTSProvider:
    provider_name = "sarvam"

    def __init__(self, settings: Settings, *, speaker: str | None, edge_voice: str | None) -> None:
        if settings.sarvam_api_key is None:
            raise ValueError("SARVAM_API_KEY is required when TTS_PROVIDER=sarvam")
        self._tts = SarvamTTS(
            api_key=settings.sarvam_api_key.get_secret_value(),
            model=settings.sarvam_tts_model,
            speaker=speaker or settings.sarvam_tts_female_speaker,
            language=settings.sarvam_tts_language,
            pace=settings.sarvam_tts_pace,
            edge_voice=edge_voice or settings.tts_voice,
            timeout_seconds=settings.sarvam_tts_timeout_seconds,
        )

    def get_livekit_tts(self) -> tts.TTS:
        return self._tts
