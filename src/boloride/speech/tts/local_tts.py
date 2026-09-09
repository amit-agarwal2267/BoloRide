from io import BytesIO

import av
import edge_tts
from livekit.agents import APIConnectOptions, APIConnectionError, tts, utils

from boloride.config import Settings


class EdgeTTS(tts.TTS):
    def __init__(self, voice: str) -> None:
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False), sample_rate=24000, num_channels=1)
        self._voice = voice

    @property
    def provider(self) -> str:
        return "edge"

    @property
    def model(self) -> str:
        return self._voice

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = APIConnectOptions()) -> tts.ChunkedStream:
        return EdgeChunkedStream(tts=self, input_text=text, conn_options=conn_options, voice=self._voice)

    async def aclose(self) -> None:
        return None


class EdgeChunkedStream(tts.ChunkedStream):
    def __init__(self, *, tts: EdgeTTS, input_text: str, conn_options: APIConnectOptions, voice: str) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._voice = voice

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        try:
            audio = bytearray()
            async for chunk in edge_tts.Communicate(self.input_text, self._voice).stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
            if not audio:
                raise APIConnectionError("Edge TTS returned no audio")
            output_emitter.initialize(request_id=utils.shortuuid(), sample_rate=24000, num_channels=1, mime_type="audio/pcm", frame_size_ms=20)
            with av.open(BytesIO(audio)) as container:
                resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
                for frame in container.decode(audio=0):
                    for converted in resampler.resample(frame):
                        output_emitter.push(converted.to_ndarray().tobytes())
        except APIConnectionError:
            raise
        except Exception as exc:
            raise APIConnectionError("Edge TTS synthesis failed") from exc


class EdgeTTSProvider:
    provider_name = "edge"

    def __init__(self, settings: Settings, *, voice: str | None = None) -> None:
        self._voice = voice or settings.tts_voice

    def get_livekit_tts(self) -> tts.TTS:
        return EdgeTTS(self._voice)
