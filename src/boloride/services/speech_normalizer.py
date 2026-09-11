import re


_CURRENCY = re.compile(r"₹\s*(\d+(?:\.\d{1,2})?)")
_REGISTRATION = re.compile(
    r"\b([A-Z]{2})\s*[- ]?\s*(\d{1,2})\s*[- ]?\s*([A-Z]{1,3})\s*[- ]?\s*(\d{4})\b",
    re.I,
)
_TIME = re.compile(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(AM|PM)\b", re.I)
_DISTANCE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:km|kms|kilometres?)\b", re.I)
_LONG_DIGITS = re.compile(r"(?<!\w)(\d{7,})(?!\w)")
_MARKDOWN_PREFIX = re.compile(r"(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)")


def normalize_for_speech(text: str) -> str:
    """Make structured display text easier to speak without changing source data."""
    normalized = _MARKDOWN_PREFIX.sub("", text)
    normalized = normalized.replace("**", "").replace("__", "").replace("`", "")
    normalized = _CURRENCY.sub(_spoken_currency, normalized)
    normalized = _REGISTRATION.sub(_spoken_registration, normalized)
    normalized = _TIME.sub(_spoken_time, normalized)
    normalized = _DISTANCE.sub(lambda match: f"{match.group(1)} kilometers", normalized)
    normalized = _LONG_DIGITS.sub(
        lambda match: " ".join(match.group(1)), normalized
    )
    return normalized


def _spoken_currency(match: re.Match[str]) -> str:
    amount = match.group(1)
    if "." not in amount:
        return f"{amount} rupees"
    rupees, paise = amount.split(".", 1)
    paise = paise.ljust(2, "0")
    if int(paise) == 0:
        return f"{rupees} rupees"
    return f"{rupees} rupees and {paise} paise"


def _spoken_registration(match: re.Match[str]) -> str:
    state, district, letters, digits = match.groups()
    return (
        f"{' '.join(state.upper())} {district}, "
        f"{' '.join(letters.upper())}, {' '.join(digits)}"
    )


def _spoken_time(match: re.Match[str]) -> str:
    clock = match.group(1)
    if match.group(2) is not None:
        clock = f"{clock}:{match.group(2)}"
    period = "in the morning" if match.group(3).casefold() == "am" else "in the evening"
    return f"{clock} {period}"
