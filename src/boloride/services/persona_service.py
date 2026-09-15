from collections.abc import Callable
from random import SystemRandom

from dataclasses import dataclass

from boloride.domain.models.persona import AgentPersona, PersonaGender


@dataclass(frozen=True, slots=True)
class SarvamVoice:
    display_name: str
    spoken_name: str
    speaker: str
    gender: PersonaGender


_SPOKEN_NAMES = {
    "shubh": "शुभ", "amit": "अमित", "sumit": "सुमित", "manan": "मनन",
    "rahul": "राहुल", "ratan": "रतन", "rohan": "रोहन", "dev": "देव",
    "aditya": "आदित्य", "ashutosh": "आशुतोष", "advait": "अद्वैत",
    "varun": "वरुण", "aayan": "आयान", "kabir": "कबीर", "soham": "सोहम",
    "ritu": "रितु", "pooja": "पूजा", "simran": "सिमरन", "kavya": "काव्या",
    "priya": "प्रिया", "ishita": "इशिता", "shreya": "श्रेया", "roopa": "रूपा",
    "neha": "नेहा", "tanya": "तान्या", "suhani": "सुहानी",
    "kavitha": "कविता", "rupali": "रूपाली",
}


SARVAM_VOICE_CATALOG = (
    *(SarvamVoice(name.title(), _SPOKEN_NAMES[name], name, PersonaGender.MALE) for name in (
        "shubh", "amit", "sumit", "manan", "rahul", "ratan", "rohan", "dev",
        "aditya", "ashutosh", "advait", "varun", "aayan", "kabir", "soham",
    )),
    *(SarvamVoice(name.title(), _SPOKEN_NAMES[name], name, PersonaGender.FEMALE) for name in (
        "ritu", "pooja", "simran", "kavya", "priya", "ishita", "shreya", "roopa",
        "neha", "tanya", "suhani", "kavitha", "rupali",
    )),
)


def _voice(speaker: str, gender: PersonaGender) -> SarvamVoice:
    for voice in SARVAM_VOICE_CATALOG:
        if voice.speaker == speaker and voice.gender is gender:
            return voice
    raise ValueError(f"unsupported {gender.value} Sarvam speaker")


def build_staff_personas(
    male_voice: str,
    female_voice: str,
    male_speaker: str = "amit",
    female_speaker: str = "ritu",
    persona_override: str = "auto",
) -> tuple[AgentPersona, ...]:
    """Build the approved catalogue or one explicit fixed session persona."""
    _voice(male_speaker, PersonaGender.MALE)
    _voice(female_speaker, PersonaGender.FEMALE)
    if persona_override == "auto":
        selected = tuple(
            (voice, male_voice if voice.gender is PersonaGender.MALE else female_voice)
            for voice in SARVAM_VOICE_CATALOG
        )
    else:
        voice = next(
            (item for item in SARVAM_VOICE_CATALOG if item.speaker == persona_override),
            None,
        )
        if voice is None:
            raise ValueError("unsupported TTS persona override")
        selected = ((voice, male_voice if voice.gender is PersonaGender.MALE else female_voice),)
    return tuple(
        AgentPersona(
            f"staff-{voice.speaker}", voice.display_name, voice.gender, edge_voice,
            voice.speaker, voice.spoken_name,
        )
        for voice, edge_voice in selected
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
