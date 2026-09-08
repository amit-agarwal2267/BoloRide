import pytest

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.user import (
    normalize_customer_age,
    normalize_customer_name,
    normalize_indian_phone_number,
    normalize_saved_place_label,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9876543210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("+91 98765-43210", "+919876543210"),
    ],
)
def test_normalize_indian_phone_number(raw: str, expected: str) -> None:
    assert normalize_indian_phone_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "123", "5876543210", "+14155552671"])
def test_reject_invalid_indian_phone_number(raw: str) -> None:
    with pytest.raises(DomainValidationError):
        normalize_indian_phone_number(raw)


def test_normalize_saved_place_label() -> None:
    assert normalize_saved_place_label("  My   HOME ") == "my home"


def test_normalize_customer_name() -> None:
    assert normalize_customer_name("  Amit   AGARWAL ") == "amit agarwal"


@pytest.mark.parametrize("age", [1, 120])
def test_customer_age_accepts_data_integrity_bounds(age: int) -> None:
    assert normalize_customer_age(age) == age
