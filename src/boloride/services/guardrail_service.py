import re
from dataclasses import dataclass
from enum import StrEnum


class GuardrailCategory(StrEnum):
    PROMPT_DISCLOSURE = "prompt_disclosure"
    INSTRUCTION_OVERRIDE = "instruction_override"
    CONFIRMATION_BYPASS = "confirmation_bypass"
    UNAUTHORIZED_INTERNAL_ACTION = "unauthorized_internal_action"
    IDENTITY_BYPASS = "identity_bypass"
    OUT_OF_SCOPE = "out_of_scope"
    DRIVER_GENDER_PREFERENCE = "driver_gender_preference"


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    blocked: bool
    category: GuardrailCategory | None = None


_PATTERNS: tuple[tuple[GuardrailCategory, re.Pattern[str]], ...] = (
    (
        GuardrailCategory.DRIVER_GENDER_PREFERENCE,
        re.compile(
            r"(?:\b(?:want|need|prefer|get|assign|select)\b.{0,36}"
            r"\b(?:female|male|lady|woman)\s+driver\b|"
            r"\b(?:female|male|lady|woman)\s+driver\b.{0,36}"
            r"\b(?:want|need|prefer|chahiye|assign|select)\b|"
            r"(?:महिला|पुरुष|female|male|lady)\s+driver.{0,24}(?:चाहिए|करो|कीजिए|assign|select))",
            re.I,
        ),
    ),
    (
        GuardrailCategory.OUT_OF_SCOPE,
        re.compile(
            r"\b(?:write|generate)\b.{0,20}\b(?:python|code|essay)\b|"
            r"\b(?:explain|teach)\b.{0,24}\b(?:recursion|docker|coding|programming)\b|"
            r"\b(?:solve|help me solve)\b.{0,24}\b(?:coding|programming)\b|"
            r"\b(?:prime minister|capital of france|tell me a joke)\b",
            re.I,
        ),
    ),
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
    """Block high-confidence security, unsupported, and unrelated requests."""

    def evaluate(self, text: str) -> GuardrailDecision:
        normalized = " ".join(text.split())
        for category, pattern in _PATTERNS:
            if pattern.search(normalized):
                return GuardrailDecision(True, category)
        return GuardrailDecision(False)
