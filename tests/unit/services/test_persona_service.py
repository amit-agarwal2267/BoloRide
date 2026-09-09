from boloride.domain.models.persona import AgentPersona, PersonaGender
from boloride.services.persona_service import PersonaSelector


MALE = AgentPersona("formal-male", PersonaGender.MALE, "hi-IN-MadhurNeural")
FEMALE = AgentPersona("formal-female", PersonaGender.FEMALE, "hi-IN-SwaraNeural")


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
    assert "sakta hoon" in MALE.welcome
    assert "sakti hoon" in FEMALE.welcome
    assert "masculine" in MALE.grammatical_instruction
    assert "feminine" in FEMALE.grammatical_instruction
