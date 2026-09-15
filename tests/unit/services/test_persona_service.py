from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.services.persona_service import (
    SARVAM_VOICE_CATALOG,
    PersonaSelector,
    build_staff_personas,
)


MALE = AgentPersona(
    "staff-aarav", "Aarav", PersonaGender.MALE, "hi-IN-MadhurNeural"
)
FEMALE = AgentPersona(
    "staff-aditi", "Aditi", PersonaGender.FEMALE, "hi-IN-SwaraNeural"
)


def test_approved_sarvam_catalog_and_selected_runtime_personas():
    personas = build_staff_personas(
        "hi-IN-MadhurNeural", "hi-IN-SwaraNeural"
    )

    assert len(SARVAM_VOICE_CATALOG) == 28
    assert len({voice.speaker for voice in SARVAM_VOICE_CATALOG}) == 28
    assert len(personas) == 2
    assert [persona.display_name for persona in personas] == ["Amit", "Ritu"]
    males = [persona for persona in personas if persona.gender is PersonaGender.MALE]
    females = [
        persona for persona in personas if persona.gender is PersonaGender.FEMALE
    ]
    assert len(males) == len(females) == 1
    assert {persona.edge_tts_voice for persona in males} == {
        "hi-IN-MadhurNeural"
    }
    assert {persona.edge_tts_voice for persona in females} == {
        "hi-IN-SwaraNeural"
    }
    assert males[0].tts_speaker == "amit"
    assert females[0].tts_speaker == "ritu"


def test_persona_speaker_gender_is_validated() -> None:
    with pytest.raises(ValueError, match="unsupported male"):
        build_staff_personas("male-edge", "female-edge", "ritu", "pooja")


def test_selection_is_injectable_and_one_value_is_fixed_by_session_owner():
    calls = 0

    def choose(personas):
        nonlocal calls
        calls += 1
        return personas[1]

    selected = PersonaSelector((MALE, FEMALE), choose).select()
    assert selected is FEMALE
    assert selected.edge_tts_voice == "hi-IN-SwaraNeural"
    assert calls == 1


def test_independent_selectors_may_choose_different_personas():
    assert PersonaSelector((MALE, FEMALE), lambda values: values[0]).select() is MALE
    assert PersonaSelector((MALE, FEMALE), lambda values: values[1]).select() is FEMALE


def test_welcome_and_grammar_match_gender_without_policy_personality_changes():
    assert MALE.welcome == (
        "Hello, मैं Aarav BoloRide से बोल रहा हूँ। "
        "मैं आपकी किस तरह मदद कर सकता हूँ?"
    )
    assert FEMALE.welcome == (
        "Hello, मैं Aditi BoloRide से बोल रही हूँ। "
        "मैं आपकी किस तरह मदद कर सकती हूँ?"
    )
    assert "Aarav" in MALE.grammatical_instruction
    assert "Aditi" in FEMALE.grammatical_instruction
    assert "masculine" in MALE.grammatical_instruction
    assert "feminine" in FEMALE.grammatical_instruction
    assert "virtual representative" in FEMALE.grammatical_instruction


def test_welcome_rejects_unsupported_persona_gender() -> None:
    persona = AgentPersona(
        "staff-invalid",
        "Invalid",
        cast(PersonaGender, "unsupported"),
        "voice",
    )

    with pytest.raises(ValueError, match="Unsupported persona gender"):
        _ = persona.welcome


def test_progress_acknowledgements_match_gender_and_operation():
    assert MALE.progress_acknowledgement("quote") == "जी, एक बार fare देख लेता हूँ।"
    assert FEMALE.progress_acknowledgement("location") == "जी, एक बार location देख लेती हूँ।"
    assert FEMALE.progress_acknowledgement("booking") == "जी, एक बार booking check कर लेती हूँ।"


def test_selected_persona_identity_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        FEMALE.display_name = "Different"  # type: ignore[misc]
