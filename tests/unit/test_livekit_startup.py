from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.integrations.telephony.livekit import _caller_phone, play_deterministic_welcome


class Session:
    def __init__(self, *, fail=False):
        self.input = SimpleNamespace(set_audio_enabled=Mock())
        self.say = Mock()
        self.generate_reply = Mock()
        handle = SimpleNamespace(wait_for_playout=self._wait)
        self.say.return_value = handle
        self.fail = fail

    async def _wait(self):
        if self.fail:
            raise RuntimeError("tts failed")


@pytest.mark.asyncio
async def test_welcome_uses_direct_session_say_once_then_enables_listening():
    persona = AgentPersona("formal-female", PersonaGender.FEMALE, "female-voice")
    session = Session()
    assert await play_deterministic_welcome(session, persona, "session") is True
    session.say.assert_called_once_with(persona.welcome, allow_interruptions=False, add_to_chat_ctx=True)
    session.input.set_audio_enabled.assert_called_once_with(True)
    session.generate_reply.assert_not_called()
    assert "sakti hoon" in session.say.call_args.args[0]


@pytest.mark.asyncio
async def test_welcome_failure_restores_listening_without_identity_mutation():
    persona = AgentPersona("formal-male", PersonaGender.MALE, "male-voice")
    session = Session(fail=True)
    assert await play_deterministic_welcome(session, persona, "session") is False
    session.input.set_audio_enabled.assert_called_once_with(True)


def test_caller_phone_prefers_adapter_metadata_then_development_fallback():
    ctx = SimpleNamespace(job=SimpleNamespace(metadata='{"phone_number":"+919876543210"}'), room=SimpleNamespace(remote_participants={}))
    assert _caller_phone(ctx, "+919999999999") == "+919876543210"
    ctx.job.metadata = ""
    assert _caller_phone(ctx, "+919999999999") == "+919999999999"
    assert _caller_phone(ctx, None) is None
