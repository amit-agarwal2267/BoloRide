import re
import unicodedata

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate

from boloride.domain.exceptions import DomainValidationError

_INDIAN_MOBILE = re.compile(r"^[6-9][0-9]{9}$")
MIN_CUSTOMER_AGE = 1
MAX_CUSTOMER_AGE = 120


def normalize_indian_phone_number(value: str) -> str:
    compact = re.sub(r"[\s()-]", "", value)

    if compact.startswith("+91"):
        national_number = compact[3:]
    elif compact.startswith("91") and len(compact) == 12:
        national_number = compact[2:]
    elif compact.startswith("0") and len(compact) == 11:
        national_number = compact[1:]
    else:
        national_number = compact

    if not _INDIAN_MOBILE.fullmatch(national_number):
        raise DomainValidationError("invalid Indian mobile number")
    return f"+91{national_number}"


def normalize_customer_name(value: str) -> str:
    """Return the canonical comparison form for a caller-provided name."""
    normalized = " ".join(value.split()).casefold()
    if not normalized:
        raise DomainValidationError("customer name cannot be blank")
    return normalized


def customer_name_match_strategy(stored_name: str, provided_name: str) -> str:
    """Compare exactly, with a restricted deterministic cross-script fallback."""
    stored = normalize_customer_name(stored_name)
    provided = normalize_customer_name(provided_name)
    if stored == provided:
        return "exact"
    stored_script = _name_script(stored)
    provided_script = _name_script(provided)
    if {stored_script, provided_script} != {"devanagari", "latin"}:
        return "none"
    stored_key = _cross_script_name_key(stored, stored_script)
    provided_key = _cross_script_name_key(provided, provided_script)
    return "transliteration" if stored_key == provided_key else "none"


def customer_names_match(stored_name: str, provided_name: str) -> bool:
    return customer_name_match_strategy(stored_name, provided_name) != "none"


def _name_script(value: str) -> str:
    letters = {character for character in value if character.isalpha()}
    if letters and all("\u0900" <= character <= "\u097f" for character in letters):
        return "devanagari"
    if letters and all("LATIN" in unicodedata.name(character, "") for character in letters):
        return "latin"
    return "other"


def _cross_script_name_key(value: str, script: str) -> tuple[str, ...]:
    romanized = (
        transliterate(value, sanscript.DEVANAGARI, sanscript.ITRANS)
        if script == "devanagari"
        else value
    )
    words = normalize_customer_name(romanized).split()
    return tuple(_phonetic_word_key(word) for word in words)


def _phonetic_word_key(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word)
    ascii_word = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character) and character.isascii()
    ).casefold()
    ascii_word = ascii_word.replace("w", "v")
    # Common Latin renderings use e where deterministic Sanskrit
    # transliteration emits an inherent a (for example, Verma/Varma).
    ascii_word = ascii_word.replace("e", "a")
    if ascii_word.endswith("a"):
        ascii_word = ascii_word[:-1]
    initial_a = ascii_word.startswith("a")
    without_schwa = ascii_word.replace("a", "")
    return ("a" if initial_a else "") + without_schwa


def normalize_customer_age(value: int) -> int:
    """Validate profile data integrity; age does not determine ride eligibility."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainValidationError("customer age must be a whole number")
    if not MIN_CUSTOMER_AGE <= value <= MAX_CUSTOMER_AGE:
        raise DomainValidationError(
            f"customer age must be between {MIN_CUSTOMER_AGE} and {MAX_CUSTOMER_AGE}"
        )
    return value


def normalize_saved_place_label(value: str) -> str:
    normalized = " ".join(value.split()).casefold()
    if not normalized:
        raise DomainValidationError("saved-place label cannot be blank")
    if len(normalized) > 50:
        raise DomainValidationError("saved-place label cannot exceed 50 characters")
    return normalized
