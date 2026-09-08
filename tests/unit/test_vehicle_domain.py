import pytest

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.vehicle import validate_passenger_count


@pytest.mark.parametrize("passenger_count", [0, -1])
def test_nonpositive_passenger_count_is_rejected(passenger_count: int) -> None:
    with pytest.raises(DomainValidationError, match="positive"):
        validate_passenger_count(passenger_count)


@pytest.mark.parametrize("passenger_count", [True, 1.5])
def test_non_whole_passenger_count_is_rejected(passenger_count: object) -> None:
    with pytest.raises(DomainValidationError, match="whole number"):
        validate_passenger_count(passenger_count)  # type: ignore[arg-type]


def test_positive_count_beyond_catalog_capacity_is_structurally_valid() -> None:
    assert validate_passenger_count(7) == 7
