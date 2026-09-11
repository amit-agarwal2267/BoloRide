import re

from boloride.domain.exceptions import DomainValidationError


MAX_PICKUP_INSTRUCTION_LENGTH = 500
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_pickup_instruction(value: str) -> str:
    """Normalize a bounded driver note without interpreting it as geography."""
    normalized = " ".join(value.split())
    if not normalized:
        raise DomainValidationError("pickup instruction cannot be blank")
    if len(normalized) > MAX_PICKUP_INSTRUCTION_LENGTH:
        raise DomainValidationError(
            f"pickup instruction cannot exceed {MAX_PICKUP_INSTRUCTION_LENGTH} characters"
        )
    if _CONTROL_CHARACTERS.search(normalized):
        raise DomainValidationError("pickup instruction contains unsupported characters")
    return normalized
