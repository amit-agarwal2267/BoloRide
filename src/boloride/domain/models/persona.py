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
    tts_speaker: str | None = None
    spoken_name: str | None = None

    @property
    def welcome(self) -> str:
        name = self.spoken_name or self.display_name
        if self.gender is PersonaGender.MALE:
            return (
                f"नमस्ते, मैं BoloRide से {name} हूँ। "
                "मैं आपकी क्या मदद कर सकता हूँ?"
            )
        if self.gender is PersonaGender.FEMALE:
            return (
                f"नमस्ते, मैं BoloRide से {name} हूँ। "
                "मैं आपकी क्या मदद कर सकती हूँ?"
            )
        raise ValueError(f"Unsupported persona gender: {self.gender!r}")

    @property
    def grammatical_instruction(self) -> str:
        form = "masculine" if self.gender is PersonaGender.MALE else "feminine"
        return (
            "You are the selected BoloRide virtual representative, not a human employee. "
            f"Your name for this session is {self.display_name}. "
            f"Your gender for this session is {self.gender.value}. "
            f"When speaking Hindi or Hinglish in first person, use {form} grammatical "
            "forms consistently. Stay calm, patient, polite, and professionally warm. "
            "Never yell, sound aggressive, scold, argue with, rush, or talk down to the caller, "
            "including when they repeat themselves or seem confused. Keep clarification questions "
            "short and easy to answer. Never change or reintroduce your name, gender, or persona "
            "during this session."
        )

    def progress_acknowledgement(self, operation: str) -> str:
        ending = "लेता हूँ" if self.gender is PersonaGender.MALE else "लेती हूँ"
        action = {
            "location": "location देख",
            "quote": "fare देख",
            "booking": "booking check कर",
        }.get(operation, "देख")
        return f"जी, एक बार {action} {ending}।"
