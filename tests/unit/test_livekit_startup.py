import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from boloride.domain.exceptions import DomainValidationError
from boloride.domain.policies import CustomerIdentityState
from boloride.services.user_service import UserService

from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.integrations.telephony.livekit import (
    _caller_phone,
    _client_input_mode,
    _deferred_text_input_callback,
    _session_stt,
    play_deterministic_welcome,
)
from livekit import rtc


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
    assert "मैं Aditi BoloRide से बोल रही हूँ" in session.say.call_args.args[0]
    assert "मदद कर सकती हूँ?" in session.say.call_args.args[0]


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


def test_twilio_mode_trusts_only_sip_caller_number() -> None:
    sip_participant = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        attributes={
            "sip.phoneNumber": "+919876543210",
            "sip.trunkPhoneNumber": "+911234567890",
            "phone_number": "+919999999999",
        },
    )
    ctx = SimpleNamespace(
        job=SimpleNamespace(metadata='{"phone_number":"+918888888888"}'),
        room=SimpleNamespace(remote_participants={"sip": sip_participant}),
    )

    assert _caller_phone(ctx, "+917777777777", "twilio", "trunk-1") is None
    sip_participant.attributes["sip.trunkID"] = "trunk-1"
    assert _caller_phone(ctx, "+917777777777", "twilio", "trunk-1") == "+919876543210"


def test_twilio_mode_rejects_untrusted_or_missing_caller_metadata() -> None:
    standard = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
        attributes={"sip.phoneNumber": "+919876543210"},
    )
    sip_without_caller = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        attributes={"sip.trunkPhoneNumber": "+911234567890"},
    )
    ctx = SimpleNamespace(
        job=SimpleNamespace(metadata='{"caller_phone":"+918888888888"}'),
        room=SimpleNamespace(
            remote_participants={"standard": standard, "sip": sip_without_caller}
        ),
    )

    assert _caller_phone(ctx, "+917777777777", "twilio", "trunk-1") is None


@pytest.mark.asyncio
async def test_twilio_caller_reaches_existing_identity_normalization() -> None:
    sip_participant = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        attributes={"sip.phoneNumber": "98765 43210", "sip.trunkID": "trunk-1"},
    )
    ctx = SimpleNamespace(
        job=SimpleNamespace(metadata=""),
        room=SimpleNamespace(remote_participants={"sip": sip_participant}),
    )

    detected = _caller_phone(ctx, None, "twilio", "trunk-1")
    assert detected == "98765 43210"
    repository = AsyncMock()
    repository.get_by_phone.return_value = None
    result = await UserService(repository).begin_identity(detected)

    repository.get_by_phone.assert_awaited_once_with("+919876543210")
    assert result.state is CustomerIdentityState.NEW_CUSTOMER_ONBOARDING_REQUIRED

    sip_participant.attributes["sip.phoneNumber"] = "not-a-phone"
    malformed = _caller_phone(ctx, None, "twilio", "trunk-1")
    with pytest.raises(DomainValidationError, match="invalid Indian mobile number"):
        await UserService(repository).begin_identity(malformed)


def test_twilio_mode_cannot_be_switched_to_text_by_job_metadata() -> None:
    ctx = SimpleNamespace(job=SimpleNamespace(metadata='{"mode":"text"}'))

    assert _client_input_mode(ctx, "twilio") == "telephony"


def test_exotel_reuses_sip_trust_boundary_and_rejects_provider_mismatch() -> None:
    participant = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        attributes={"sip.phoneNumber": "+919876543210", "sip.trunkID": "exotel"},
    )
    ctx = SimpleNamespace(
        job=SimpleNamespace(metadata='{"caller_phone":"+918888888888"}'),
        room=SimpleNamespace(remote_participants={"sip": participant}),
    )

    assert _caller_phone(ctx, None, "exotel", "exotel") == "+919876543210"
    assert _caller_phone(ctx, None, "exotel", "twilio") is None
    assert _client_input_mode(ctx, "exotel") == "telephony"


def test_browser_mode_uses_only_server_owned_demo_identity() -> None:
    ctx = SimpleNamespace(
        job=SimpleNamespace(metadata='{"caller_phone":"+919999999999"}'),
        room=SimpleNamespace(remote_participants={}),
    )

    assert _caller_phone(ctx, "+918888888888", "browser", None, "+917777777777") == "+917777777777"
    assert _caller_phone(ctx, "+918888888888", "browser") is None


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
