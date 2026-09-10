import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.integrations.telephony.livekit import (
    _caller_phone,
    _client_input_mode,
    _deferred_text_input_callback,
    _session_stt,
    play_deterministic_welcome,
)


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
    persona = AgentPersona(
        "staff-aditi", "Aditi", PersonaGender.FEMALE, "female-voice"
    )
    session = Session()
    assert await play_deterministic_welcome(session, persona, "session") is True
    session.say.assert_called_once_with(persona.welcome, allow_interruptions=False, add_to_chat_ctx=True)
    session.input.set_audio_enabled.assert_called_once_with(True)
    session.generate_reply.assert_not_called()
    assert "Main Aditi bol rahi hoon" in session.say.call_args.args[0]


@pytest.mark.asyncio
async def test_welcome_failure_restores_listening_without_identity_mutation():
    persona = AgentPersona(
        "staff-aarav", "Aarav", PersonaGender.MALE, "male-voice"
    )
    session = Session(fail=True)
    assert await play_deterministic_welcome(session, persona, "session") is False
    session.input.set_audio_enabled.assert_called_once_with(True)


def test_caller_phone_prefers_adapter_metadata_then_development_fallback():
    ctx = SimpleNamespace(job=SimpleNamespace(metadata='{"phone_number":"+919876543210"}'), room=SimpleNamespace(remote_participants={}))
    assert _caller_phone(ctx, "+919999999999") == "+919876543210"
    ctx.job.metadata = ""
    assert _caller_phone(ctx, "+919999999999") == "+919999999999"
    assert _caller_phone(ctx, None) is None


class TextSession:
    def __init__(self) -> None:
        self.interrupt = AsyncMock()
        self.generate_reply = Mock()
        self.generated_reply_played = False
        self.generate_reply.return_value = SimpleNamespace(
            wait_for_playout=self._wait_for_generated_reply
        )
        self.claimed_turns = 0

    async def _wait_for_generated_reply(self) -> None:
        self.generated_reply_played = True

    @asynccontextmanager
    async def _claim_user_turn(self):
        self.claimed_turns += 1
        yield


@pytest.mark.asyncio
async def test_text_input_during_welcome_is_deferred_then_processed() -> None:
    welcome_completed = asyncio.Event()
    session = TextSession()
    callback = _deferred_text_input_callback(welcome_completed, "session")

    pending = asyncio.create_task(
        callback(session, SimpleNamespace(text="Book a ride"))
    )
    await asyncio.sleep(0)

    assert not pending.done()
    session.interrupt.assert_not_called()
    session.generate_reply.assert_not_called()

    welcome_completed.set()
    await pending

    session.interrupt.assert_called_once_with()
    session.generate_reply.assert_called_once_with(user_input="Book a ride")
    assert session.generated_reply_played is True
    assert session.claimed_turns == 1


@pytest.mark.asyncio
async def test_post_welcome_text_keeps_normal_interrupt_behavior() -> None:
    welcome_completed = asyncio.Event()
    welcome_completed.set()
    session = TextSession()
    callback = _deferred_text_input_callback(welcome_completed, "session")

    await callback(session, SimpleNamespace(text="Change destination"))

    session.interrupt.assert_called_once_with()
    session.generate_reply.assert_called_once_with(user_input="Change destination")
    assert session.generated_reply_played is False


def test_explicit_text_mode_disables_stt_but_defaults_keep_microphone_stt() -> None:
    ctx = SimpleNamespace(job=SimpleNamespace(metadata='{"mode":"text"}'))
    with patch(
        "boloride.integrations.telephony.livekit.STTRouter"
    ) as router_constructor:
        assert _client_input_mode(ctx) == "text"
        assert _session_stt("text") is None
        router_constructor.assert_not_called()

        expected_stt = object()
        router_constructor.return_value.get_provider.return_value.get_livekit_stt.return_value = expected_stt
        assert _session_stt("microphone") is expected_stt
        router_constructor.assert_called_once()

    for metadata in ("", "not-json", '{"mode":"unexpected"}'):
        ctx.job.metadata = metadata
        assert _client_input_mode(ctx) == "microphone"
