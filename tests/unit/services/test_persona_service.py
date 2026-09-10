from dataclasses import FrozenInstanceError

import pytest

from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.services.persona_service import PersonaSelector, build_staff_personas


MALE = AgentPersona(
    "staff-aarav", "Aarav", PersonaGender.MALE, "hi-IN-MadhurNeural"
)
FEMALE = AgentPersona(
    "staff-aditi", "Aditi", PersonaGender.FEMALE, "hi-IN-SwaraNeural"
)


def test_fixed_staff_catalog_has_ten_unique_gender_correct_personas():
    personas = build_staff_personas(
        "hi-IN-MadhurNeural", "hi-IN-SwaraNeural"
    )

    assert len(personas) == 10
    assert len({persona.persona_id for persona in personas}) == 10
    assert [persona.display_name for persona in personas] == [
        "Aarav",
        "Arjun",
        "Kabir",
        "Rohan",
        "Vivaan",
        "Aditi",
        "Ananya",
        "Kavya",
        "Meera",
        "Riya",
    ]
    males = [persona for persona in personas if persona.gender is PersonaGender.MALE]
    females = [
        persona for persona in personas if persona.gender is PersonaGender.FEMALE
    ]
    assert len(males) == len(females) == 5
    assert {persona.edge_tts_voice for persona in males} == {
        "hi-IN-MadhurNeural"
    }
    assert {persona.edge_tts_voice for persona in females} == {
        "hi-IN-SwaraNeural"
    }


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
    assert "Main Aarav bol raha hoon" in MALE.welcome
    assert "Main Aditi bol rahi hoon" in FEMALE.welcome
    assert "kis shehar se ride book" in MALE.welcome
    assert "Aarav" in MALE.grammatical_instruction
    assert "Aditi" in FEMALE.grammatical_instruction
    assert "masculine" in MALE.grammatical_instruction
    assert "feminine" in FEMALE.grammatical_instruction
    assert "virtual representative" in FEMALE.grammatical_instruction


def test_progress_acknowledgements_match_gender_and_operation():
    assert "fare check kar raha hoon" in MALE.progress_acknowledgement("quote")
    assert "location check kar rahi hoon" in FEMALE.progress_acknowledgement(
        "location"
    )
    assert "booking confirm kar rahi hoon" in FEMALE.progress_acknowledgement(
        "booking"
    )


def test_selected_persona_identity_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        FEMALE.display_name = "Different"  # type: ignore[misc]
