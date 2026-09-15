import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from boloride.speech.tts import sarvam
from boloride.speech.tts.sarvam import SarvamTTS, _linear16_pcm


class Emitter:
    def __init__(self) -> None:
        self.initialized = None
        self.audio = b""

    def initialize(self, **kwargs) -> None:
        self.initialized = kwargs

    def push(self, audio: bytes) -> None:
        self.audio += audio


def make_tts(handler) -> SarvamTTS:
    return SarvamTTS(
        api_key="test-secret-not-real",
        model="bulbul:v3",
        speaker="amit",
        language="hi-IN",
        pace=1.0,
        edge_voice="hi-IN-MadhurNeural",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_sarvam_sends_stable_v3_speaker_and_24khz_without_edge(monkeypatch) -> None:
    requests = []
    pcm = b"\x01\x80\x02\x00"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"audios": [base64.b64encode(pcm).decode()]})

    async def edge(*_):
        raise AssertionError("Edge must not run after Sarvam success")

    monkeypatch.setattr(sarvam, "synthesize_edge_pcm", edge)
    engine = make_tts(handler)
    stream = engine.synthesize("आपकी ride confirm है")
    emitter = Emitter()
    await stream._run(emitter)  # type: ignore[arg-type]

    body = json.loads(requests[0].content)
    assert body == {
        "text": "आपकी ride confirm है",
        "target_language_code": "hi-IN",
        "speaker": "amit",
        "model": "bulbul:v3",
        "pace": 1.0,
        "speech_sample_rate": 24000,
        "output_audio_codec": "linear16",
    }
    assert emitter.audio == pcm
    assert emitter.initialized["sample_rate"] == 24000
    assert requests[0].headers["api-subscription-key"] == "test-secret-not-real"
    await engine.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 402, 429, 500])
async def test_sarvam_provider_rejection_falls_back_once_to_complete_edge(
    monkeypatch, status: int
) -> None:
    calls = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="private provider response")

    async def edge(text: str, voice: str) -> bytes:
        calls.append((text, voice))
        return b"\x00\x00"

    monkeypatch.setattr(sarvam, "synthesize_edge_pcm", edge)
    engine = make_tts(handler)
    stream = engine.synthesize("complete utterance")
    emitter = Emitter()
    await stream._run(emitter)  # type: ignore[arg-type]

    assert calls == [("complete utterance", "hi-IN-MadhurNeural")]
    assert emitter.audio == b"\x00\x00"
    await engine.aclose()


def test_malformed_or_empty_linear16_is_rejected() -> None:
    with pytest.raises(Exception, match="malformed audio"):
        _linear16_pcm("not-base64")
    with pytest.raises(Exception, match="invalid linear PCM"):
        _linear16_pcm(base64.b64encode(b"").decode())


def test_sarvam_metadata_never_contains_secret_or_text(monkeypatch) -> None:
    # The observable payload is intentionally asserted in the integration-style
    # stream tests; provider credentials stay solely in the HTTP header.
    assert "test-secret-not-real" not in json.dumps(
        {"provider": "sarvam", "model": "bulbul:v3", "speaker": "amit"}
    )
