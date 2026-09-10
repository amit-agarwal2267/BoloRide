from collections.abc import Callable
from random import SystemRandom

from boloride.domain.models.persona import AgentPersona, PersonaGender


STAFF_NAMES = (
    ("staff-aarav", "Aarav", PersonaGender.MALE),
    ("staff-arjun", "Arjun", PersonaGender.MALE),
    ("staff-kabir", "Kabir", PersonaGender.MALE),
    ("staff-rohan", "Rohan", PersonaGender.MALE),
    ("staff-vivaan", "Vivaan", PersonaGender.MALE),
    ("staff-aditi", "Aditi", PersonaGender.FEMALE),
    ("staff-ananya", "Ananya", PersonaGender.FEMALE),
    ("staff-kavya", "Kavya", PersonaGender.FEMALE),
    ("staff-meera", "Meera", PersonaGender.FEMALE),
    ("staff-riya", "Riya", PersonaGender.FEMALE),
)


def build_staff_personas(
    male_voice: str, female_voice: str
) -> tuple[AgentPersona, ...]:
    """Build the fixed virtual-staff catalog using configured gender voices."""
    return tuple(
        AgentPersona(
            persona_id,
            display_name,
            gender,
            male_voice if gender is PersonaGender.MALE else female_voice,
        )
        for persona_id, display_name, gender in STAFF_NAMES
    )


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
