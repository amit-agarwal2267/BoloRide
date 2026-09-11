import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from boloride.agents.context import RideContext
from boloride.agents.session_lifecycle import SessionLifecycleController
from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.observability.session_metrics import SessionMetrics


class FakeHandle:
    async def wait_for_playout(self):
        return None


class FakeSession:
    def __init__(self):
        self.listeners = {}
        self.spoken = []
        self.shutdown = Mock()

    def on(self, event, callback):
        self.listeners[event] = callback

    def off(self, event, callback):
        if self.listeners.get(event) is callback:
            del self.listeners[event]

    def say(self, text, **kwargs):
        self.spoken.append((text, kwargs))
        return FakeHandle()


def controller(gender=PersonaGender.FEMALE):
    session = FakeSession()
    context = RideContext(session_id="silence-test", caller_id=None)
    persona = AgentPersona("staff-test", "Test", gender, "voice")
    return SessionLifecycleController(
        session, context, persona, timeout_seconds=3600
    ), session, context


@pytest.mark.asyncio
async def test_three_consecutive_silences_recover_then_end_session():
    lifecycle, session, context = controller()
    await lifecycle.handle_silence()
    await lifecycle.handle_silence()
    await lifecycle.handle_silence()

    assert len(session.spoken) == 3
    assert "sun rahi" in session.spoken[0][0]
    assert context.session_active is False
    session.shutdown.assert_called_once_with(drain=True)


@pytest.mark.asyncio
async def test_genuine_user_message_resets_silence_counter():
    lifecycle, session, _ = controller(PersonaGender.MALE)
    lifecycle.start()
    await lifecycle.handle_silence()
    assert lifecycle.silence_count == 1

    session.listeners["conversation_item_added"](
        SimpleNamespace(item=SimpleNamespace(role="user", raw_text_content="hello"))
    )
    assert lifecycle.silence_count == 0
    await lifecycle.aclose()


@pytest.mark.asyncio
async def test_agent_work_cancels_silence_timer_until_listening_again():
    lifecycle, session, _ = controller()
    lifecycle.start()
    active_timer = lifecycle._timer
    session.listeners["agent_state_changed"](
        SimpleNamespace(new_state="thinking")
    )
    await asyncio.sleep(0)
    assert active_timer.cancelled()
    assert lifecycle.silence_count == 0

    session.listeners["agent_state_changed"](
        SimpleNamespace(new_state="listening")
    )
    assert lifecycle._timer is not None
    await lifecycle.aclose()


@pytest.mark.asyncio
async def test_only_accepted_customer_messages_count_as_turns():
    lifecycle, session, context = controller()
    observability = SimpleNamespace(metrics=SessionMetrics())
    lifecycle = SessionLifecycleController(
        session, context, lifecycle._persona, timeout_seconds=3600,
        observability=observability,
    )
    lifecycle.start()

    callback = session.listeners["conversation_item_added"]
    callback(SimpleNamespace(item=SimpleNamespace(role="assistant", raw_text_content="welcome")))
    callback(SimpleNamespace(item=SimpleNamespace(role="tool", raw_text_content="technical")))
    callback(SimpleNamespace(item=SimpleNamespace(role="user", raw_text_content="  ")))
    callback(SimpleNamespace(item=SimpleNamespace(role="user", raw_text_content="book ride")))

    assert observability.metrics.customer_turn_count == 1
    await lifecycle.aclose()
