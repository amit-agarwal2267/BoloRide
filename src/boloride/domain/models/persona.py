from dataclasses import dataclass
from enum import StrEnum


class PersonaGender(StrEnum):
    MALE = "male"
    FEMALE = "female"


@dataclass(frozen=True, slots=True)
class AgentPersona:
    persona_id: str
    display_name: str
    gender: PersonaGender
    edge_tts_voice: str

    @property
    def welcome(self) -> str:
        speech = "bol raha" if self.gender is PersonaGender.MALE else "bol rahi"
        return (
            "Namaste, BoloRide mein aapka swagat hai. "
            f"Main {self.display_name} {speech} hoon. "
            "Aap kis shehar se ride book karna chahte hain?"
        )

    @property
    def grammatical_instruction(self) -> str:
        form = "masculine" if self.gender is PersonaGender.MALE else "feminine"
        return (
            "You are the selected BoloRide virtual representative, not a human employee. "
            f"Your name for this session is {self.display_name}. "
            f"Your gender for this session is {self.gender.value}. "
            f"When speaking Hindi or Hinglish in first person, use {form} grammatical "
            "forms consistently. Maintain a formal, respectful, concise, professional tone. "
            "Never change or reintroduce your name, gender, or persona during this session."
        )

    def progress_acknowledgement(self, operation: str) -> str:
        verb = "raha" if self.gender is PersonaGender.MALE else "rahi"
        action = {
            "location": "location check",
            "quote": "fare check",
            "booking": "booking confirm",
        }.get(operation, "check")
        return f"Ji, ek moment, main {action} kar {verb} hoon."
