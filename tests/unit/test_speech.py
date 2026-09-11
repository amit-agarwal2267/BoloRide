from unittest.mock import patch

import pytest
from livekit.agents import stt

from boloride.config import Settings
from boloride.speech.stt.assemblyai import AssemblyAIProvider
from boloride.speech.stt.base import normalize_speech_event
from boloride.speech.tts.local_tts import EdgeTTS
from boloride.speech.tts.router import TTSRouter


def settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://u:p@postgres/db",
        "langfuse_enabled": False,
        "assemblyai_api_key": "assembly-key",
        "assemblyai_stt_model": "universal-streaming-multilingual",
        "stt_language": "hi",
    }
    values.update(overrides)
    return Settings(**values)


def test_assemblyai_configuration_reaches_livekit_plugin() -> None:
    with patch("boloride.speech.stt.assemblyai.assemblyai.STT") as constructor:
        AssemblyAIProvider(settings()).get_livekit_stt()
    constructor.assert_called_once_with(
        api_key="assembly-key",
        model="universal-streaming-multilingual",
        language_codes=["hi"],
    )


@pytest.mark.parametrize(
    ("event_type", "is_final"),
    [
        (stt.SpeechEventType.INTERIM_TRANSCRIPT, False),
        (stt.SpeechEventType.FINAL_TRANSCRIPT, True),
    ],
)
def test_transcript_event_is_normalized(event_type, is_final: bool) -> None:
    event = stt.SpeechEvent(
        type=event_type,
        alternatives=[stt.SpeechData(language="hi", text="  नमस्ते  ", confidence=0.8)],
    )
    result = normalize_speech_event(event, "assemblyai")
    assert result is not None
    assert result.text == "नमस्ते"
    assert result.is_final is is_final
    assert result.provider == "assemblyai"
    assert result.confidence == 0.8


def test_tts_router_exposes_livekit_compatible_edge_adapter() -> None:
    adapter = TTSRouter(settings()).get_provider().get_livekit_tts()
    assert isinstance(adapter, EdgeTTS)
    assert adapter.provider == "edge"
    assert adapter.sample_rate == 24000


def test_tts_router_uses_session_persona_voice_override() -> None:
    adapter = TTSRouter(settings(), voice="hi-IN-MadhurNeural").get_provider().get_livekit_tts()
    assert adapter.model == "hi-IN-MadhurNeural"


@pytest.mark.asyncio
async def test_edge_tts_normalizes_only_the_synthesized_copy() -> None:
    adapter = TTSRouter(settings()).get_provider().get_livekit_tts()
    source = "Fare ₹245, vehicle RJ20AB1234"

    stream = adapter.synthesize(source)

    assert stream._input_text == "Fare 245 rupees, vehicle R J 20, A B, 1 2 3 4"
    assert source == "Fare ₹245, vehicle RJ20AB1234"
