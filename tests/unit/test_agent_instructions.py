from boloride.agents.instructions import (
    RUNTIME_INVARIANTS,
    build_agent_instructions,
)
from boloride.domain.models.persona import (
    AgentPersona,
    PersonaGender,
)
from boloride.prompts.client import ResolvedPrompt
from boloride.prompts.registry import PromptBundle


def resolved_prompt(
    name: str,
    content: str,
    *,
    source: str = "langfuse",
    version: int | None = 1,
) -> ResolvedPrompt:
    return ResolvedPrompt(
        name=name,
        content=content,
        source=source,  # type: ignore[arg-type]
        label="development",
        version=version,
    )


def make_bundle() -> PromptBundle:
    return PromptBundle(
        voice_agent=resolved_prompt(
            "boloride-voice-agent",
            "VOICE_AGENT_CONTENT",
        ),
        location_clarification=resolved_prompt(
            "boloride-location-clarification",
            "LOCATION_CLARIFICATION_CONTENT",
        ),
        booking_confirmation=resolved_prompt(
            "boloride-booking-confirmation",
            "BOOKING_CONFIRMATION_CONTENT",
        ),
        error_recovery=resolved_prompt(
            "boloride-error-recovery",
            "ERROR_RECOVERY_CONTENT",
        ),
        offer_explanation=resolved_prompt(
            "boloride-offer-explanation",
            "OFFER_EXPLANATION_CONTENT",
        ),
    )


def test_build_agent_instructions_contains_all_managed_prompt_sections() -> None:
    bundle = make_bundle()

    instructions = build_agent_instructions(bundle)

    assert "VOICE_AGENT_CONTENT" in instructions

    assert "Location clarification policy:" in instructions
    assert "LOCATION_CLARIFICATION_CONTENT" in instructions

    assert "Booking confirmation policy:" in instructions
    assert "BOOKING_CONFIRMATION_CONTENT" in instructions

    assert "Error recovery policy:" in instructions
    assert "ERROR_RECOVERY_CONTENT" in instructions

    assert "Offer explanation policy:" in instructions
    assert "OFFER_EXPLANATION_CONTENT" in instructions


def test_runtime_invariants_remain_application_owned() -> None:
    instructions = build_agent_instructions(
        make_bundle()
    )

    assert "Non-negotiable runtime constraints:" in instructions
    assert RUNTIME_INVARIANTS.strip() in instructions

    assert (
        "deterministic tools and services are authoritative"
        in instructions
    )
    assert (
        "Never assume a default city or state"
        in instructions
    )
    assert (
        "Missing ride time never authorizes an immediate ride"
        in instructions
    )
    assert (
        "Booking requires the backend's current valid quote "
        "and explicit confirmation"
        in instructions
    )
    assert (
        "reconciliation-pending result is not"
        in instructions
    )
    assert (
        "Every Hindi word in a response intended for speech must use Devanagari"
        in instructions
    )
    assert "Natural mixed language is encouraged" in instructions
    assert "BoloRide, ride," in instructions


def test_selected_persona_instruction_is_appended() -> None:
    persona = AgentPersona(
        persona_id="staff-aditi",
        display_name="Aditi",
        gender=PersonaGender.FEMALE,
        edge_tts_voice="hi-IN-SwaraNeural",
    )

    instructions = build_agent_instructions(
        make_bundle(),
        persona=persona,
    )

    assert persona.grammatical_instruction in instructions
    assert "Your name for this session is Aditi." in instructions
    assert "Your gender for this session is female." in instructions
    assert "use feminine grammatical forms consistently" in instructions


def test_male_persona_uses_masculine_instruction() -> None:
    persona = AgentPersona(
        persona_id="staff-aarav",
        display_name="Aarav",
        gender=PersonaGender.MALE,
        edge_tts_voice="hi-IN-MadhurNeural",
    )

    instructions = build_agent_instructions(
        make_bundle(),
        persona=persona,
    )

    assert "Your name for this session is Aarav." in instructions
    assert "Your gender for this session is male." in instructions
    assert "use masculine grammatical forms consistently" in instructions


def test_persona_is_optional() -> None:
    instructions = build_agent_instructions(
        make_bundle(),
        persona=None,
    )

    assert "VOICE_AGENT_CONTENT" in instructions
    assert "Non-negotiable runtime constraints:" in instructions

    assert "Your name for this session is" not in instructions
    assert "Your gender for this session is" not in instructions


def test_prompt_content_is_not_replaced_by_runtime_invariants() -> None:
    bundle = make_bundle()

    instructions = build_agent_instructions(bundle)

    expected_prompt_contents = (
        bundle.voice_agent.content,
        bundle.location_clarification.content,
        bundle.booking_confirmation.content,
        bundle.error_recovery.content,
        bundle.offer_explanation.content,
    )

    for content in expected_prompt_contents:
        assert instructions.count(content) == 1
