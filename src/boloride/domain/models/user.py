import re

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
