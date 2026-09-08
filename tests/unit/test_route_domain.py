from decimal import Decimal

import pytest

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import (
    AirportClassification,
    LocationCandidate,
    RouteResult,
    TollStatus,
)


@pytest.mark.parametrize(
    ("place_types", "expected"),
    [
        (("airport", "point_of_interest"), AirportClassification.AIRPORT),
        (("train_station",), AirportClassification.NOT_AIRPORT),
        (None, AirportClassification.UNKNOWN),
        ((), AirportClassification.UNKNOWN),
    ],
)
def test_airport_classification_uses_only_structured_types(
    place_types: tuple[str, ...] | None, expected: AirportClassification
) -> None:
    candidate = LocationCandidate(
        "Airport in name is not evidence",
        "Airport Road",
        Decimal("25.18"),
        Decimal("75.83"),
        "test",
        place_types=place_types,
    )
    assert candidate.airport_classification is expected


@pytest.mark.parametrize(
    ("distance", "duration"),
    [(-1, 10), (10, -1), ("10", 10), (10, 1.5)],
)
def test_route_metrics_reject_invalid_values(distance: object, duration: object) -> None:
    with pytest.raises(DomainValidationError):
        RouteResult(distance, duration, "test")  # type: ignore[arg-type]


def test_route_retains_provider_backed_toll_estimate() -> None:
    route = RouteResult(
        1000,
        60,
        " GOOGLE ",
        TollStatus.ESTIMATE_AVAILABLE,
        Decimal("125.50"),
        "inr",
    )
    assert route.provider == "google"
    assert route.toll_estimate == Decimal("125.50")
    assert route.toll_currency == "INR"


def test_unknown_toll_is_not_fabricated_as_zero() -> None:
    route = RouteResult(1000, 60, "ola", TollStatus.UNKNOWN)
    assert route.toll_estimate is None
