import asyncio
import logging
from contextlib import suppress
from typing import Any

from boloride.agents.context import RideContext
from boloride.domain.models.persona import AgentPersona, PersonaGender


logger = logging.getLogger(__name__)
CALLER_SILENCE_TIMEOUT_SECONDS = 15.0


class SessionLifecycleController:
    """Handle genuine idle caller time without counting agent/tool work."""

    def __init__(
        self,
        session: Any,
        context: RideContext,
        persona: AgentPersona,
        *,
        timeout_seconds: float = CALLER_SILENCE_TIMEOUT_SECONDS,
    ) -> None:
        self._session = session
        self._context = context
        self._persona = persona
        self._timeout_seconds = timeout_seconds
        self._silence_count = 0
        self._timer: asyncio.Task[None] | None = None
        self._started = False

    @property
    def silence_count(self) -> int:
        return self._silence_count

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._session.on("agent_state_changed", self._on_agent_state_changed)
        self._session.on("conversation_item_added", self._on_conversation_item_added)
        self._schedule()

    async def aclose(self) -> None:
        if self._started:
            self._session.off("agent_state_changed", self._on_agent_state_changed)
            self._session.off("conversation_item_added", self._on_conversation_item_added)
        self._started = False
        self._cancel()

    def _on_agent_state_changed(self, event: Any) -> None:
        if event.new_state == "listening":
            self._schedule()
        else:
            self._cancel()

    def _on_conversation_item_added(self, event: Any) -> None:
        item = event.item
        if getattr(item, "role", None) != "user":
            return
        if not (getattr(item, "raw_text_content", None) or "").strip():
            return
        self._silence_count = 0
        self._cancel()
        logger.info(
            "caller_silence_reset",
            extra={
                "event": "caller_silence_reset",
                "session_id": self._context.session_id,
            },
        )

    def _schedule(self) -> None:
        if not self._started or not self._context.session_active:
            return
        self._cancel()
        self._timer = asyncio.create_task(self._wait_for_silence())

    def _cancel(self) -> None:
        task = self._timer
        self._timer = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _wait_for_silence(self) -> None:
        try:
            await asyncio.sleep(self._timeout_seconds)
            self._timer = None
            await self.handle_silence()
        except asyncio.CancelledError:
            return

    async def handle_silence(self) -> None:
        """Speak one recovery level; callable directly for deterministic tests."""
        if not self._context.session_active:
            return
        self._silence_count += 1
        count = self._silence_count
        logger.info(
            "silence_recovery",
            extra={
                "event": "silence_recovery",
                "session_id": self._context.session_id,
                "silence_count": count,
            },
        )
        if count == 1:
            speech = (
                "Ji, main sun raha hoon."
                if self._persona.gender is PersonaGender.MALE
                else "Ji, main sun rahi hoon."
            )
        elif count == 2:
            speech = "Agar aapko thoda waqt chahiye toh bata dijiye."
        else:
            speech = "Shayad connection mein dikkat hai. Aap dobara call kar sakte hain."
        handle = self._session.say(
            speech, allow_interruptions=count < 3, add_to_chat_ctx=True
        )
        with suppress(Exception):
            await handle.wait_for_playout()
        if count >= 3:
            self._context.disconnect()
            logger.info(
                "session_ended_after_silence",
                extra={
                    "event": "session_ended_after_silence",
                    "session_id": self._context.session_id,
                },
            )
            self._session.shutdown(drain=True)
