from collections.abc import Callable
from random import SystemRandom

from boloride.domain.models.persona import AgentPersona


class PersonaSelector:
    def __init__(
        self,
        personas: tuple[AgentPersona, ...],
        chooser: Callable[[tuple[AgentPersona, ...]], AgentPersona] | None = None,
    ) -> None:
        if not personas:
            raise ValueError("at least one agent persona is required")
        self._personas = personas
        self._chooser = chooser or SystemRandom().choice

    def select(self) -> AgentPersona:
        return self._chooser(self._personas)
