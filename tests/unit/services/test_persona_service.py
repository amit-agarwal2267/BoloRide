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
    assert len(personas) == 28
    assert {persona.tts_speaker for persona in personas} == {voice.speaker for voice in SARVAM_VOICE_CATALOG}
    males = [persona for persona in personas if persona.gender is PersonaGender.MALE]
    females = [
        persona for persona in personas if persona.gender is PersonaGender.FEMALE
    ]
    assert len(males) == 15
    assert len(females) == 13
    assert {persona.edge_tts_voice for persona in males} == {
        "hi-IN-MadhurNeural"
    }
    assert {persona.edge_tts_voice for persona in females} == {
        "hi-IN-SwaraNeural"
    }
    assert all(persona.spoken_name for persona in personas)
    assert all(persona.display_name.casefold() == persona.tts_speaker for persona in personas)
    assert "कबीर" in next(p for p in personas if p.tts_speaker == "kabir").welcome
    assert "पूजा" in next(p for p in personas if p.tts_speaker == "pooja").welcome


def test_explicit_persona_override_is_fixed_and_invalid_override_fails():
    assert [p.tts_speaker for p in build_staff_personas("male-edge", "female-edge", persona_override="pooja")] == ["pooja"]
    with pytest.raises(ValueError, match="unsupported TTS persona override"):
        build_staff_personas("male-edge", "female-edge", persona_override="unknown")


def test_every_approved_voice_is_reachable_and_session_value_is_immutable():
    personas = build_staff_personas("male-edge", "female-edge")
    reached = {
        PersonaSelector(personas, lambda values, index=index: values[index]).select().tts_speaker
        for index in range(len(personas))
    }
    assert reached == {voice.speaker for voice in SARVAM_VOICE_CATALOG}
    kabir = PersonaSelector(personas, lambda values: next(p for p in values if p.tts_speaker == "kabir")).select()
    pooja = PersonaSelector(personas, lambda values: next(p for p in values if p.tts_speaker == "pooja")).select()
    assert kabir is not pooja
    assert (kabir.display_name, kabir.spoken_name, kabir.gender, kabir.tts_speaker) == (
        "Kabir", "कबीर", PersonaGender.MALE, "kabir"
    )
    assert (pooja.display_name, pooja.spoken_name, pooja.gender, pooja.tts_speaker) == (
        "Pooja", "पूजा", PersonaGender.FEMALE, "pooja"
    )
    assert "सकता हूँ" in kabir.welcome
    assert "सकती हूँ" in pooja.welcome


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
        "नमस्ते, मैं BoloRide से Aarav हूँ। "
        "मैं आपकी क्या मदद कर सकता हूँ?"
    )
    assert FEMALE.welcome == (
        "नमस्ते, मैं BoloRide से Aditi हूँ। "
        "मैं आपकी क्या मदद कर सकती हूँ?"
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
