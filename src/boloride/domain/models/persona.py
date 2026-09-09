from dataclasses import dataclass
from enum import StrEnum


class PersonaGender(StrEnum):
    MALE = "male"
    FEMALE = "female"


@dataclass(frozen=True, slots=True)
class AgentPersona:
    persona_id: str
    gender: PersonaGender
    edge_tts_voice: str

    @property
    def welcome(self) -> str:
        verb = "sakta" if self.gender is PersonaGender.MALE else "sakti"
        return (
            "Hi, Welcome to BoloRide. BoloRide mein aapka swagat hai. "
            f"Main aapki kis prakaar sahayata kar {verb} hoon?"
        )

    @property
    def grammatical_instruction(self) -> str:
        form = "masculine" if self.gender is PersonaGender.MALE else "feminine"
        return (
            f"The current BoloRide agent uses a {self.gender.value} voice. "
            f"When speaking Hindi or Hinglish in first person, use {form} grammatical "
            "forms consistently. Maintain a formal, respectful, concise, professional tone. "
            "Never change persona during this session."
        )
