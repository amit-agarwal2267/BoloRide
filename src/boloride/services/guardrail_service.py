import re
from dataclasses import dataclass
from enum import StrEnum


class GuardrailCategory(StrEnum):
    PROMPT_DISCLOSURE = "prompt_disclosure"
    INSTRUCTION_OVERRIDE = "instruction_override"
    CONFIRMATION_BYPASS = "confirmation_bypass"
    UNAUTHORIZED_INTERNAL_ACTION = "unauthorized_internal_action"
    IDENTITY_BYPASS = "identity_bypass"


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    blocked: bool
    category: GuardrailCategory | None = None


_PATTERNS: tuple[tuple[GuardrailCategory, re.Pattern[str]], ...] = (
    (
        GuardrailCategory.PROMPT_DISCLOSURE,
        re.compile(
            r"\b(?:reveal|show|print|expose|batao|dikhao)\b.{0,40}"
            r"\b(?:system prompt|hidden (?:prompt|instructions?)|developer instructions?)\b",
            re.I,
        ),
    ),
    (
        GuardrailCategory.INSTRUCTION_OVERRIDE,
        re.compile(
            r"\b(?:ignore|disregard|override|forget)\b.{0,32}"
            r"\b(?:previous|prior|system|developer|hidden)\b.{0,16}"
            r"\b(?:rules?|instructions?|prompt)\b",
            re.I,
        ),
    ),
    (
        GuardrailCategory.CONFIRMATION_BYPASS,
        re.compile(
            r"\b(?:bypass|skip|ignore|without|bina)\b.{0,32}"
            r"\b(?:booking |cancellation |cancel )?confirmation\b",
            re.I,
        ),
    ),
    (
        GuardrailCategory.IDENTITY_BYPASS,
        re.compile(
            r"\b(?:bypass|skip|ignore|disable)\b.{0,32}"
            r"\b(?:identity|verification|security check)\b",
            re.I,
        ),
    ),
    (
        GuardrailCategory.UNAUTHORIZED_INTERNAL_ACTION,
        re.compile(
            r"(?:\b(?:enable|execute|run|use|update|change|set)\b.{0,48}"
            r"\b(?:admin mode|system tool|internal tool|raw sql|database)\b|"
            r"\b(?:admin mode|system tool|internal tool|raw sql|database)\b.{0,48}"
            r"\b(?:enable|execute|run|use|directly|update|change|set|cancel|complete)\b)",
            re.I,
        ),
    ),
)


class GuardrailService:
    """Block only high-confidence meta/security manipulation patterns."""

    def evaluate(self, text: str) -> GuardrailDecision:
        normalized = " ".join(text.split())
        for category, pattern in _PATTERNS:
            if pattern.search(normalized):
                return GuardrailDecision(True, category)
        return GuardrailDecision(False)
