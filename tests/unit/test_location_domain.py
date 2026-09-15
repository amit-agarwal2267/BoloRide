from decimal import Decimal

import pytest

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import (
    LocationCandidate,
    ResolvedLocation,
    RouteResult,
    RouteSanityStatus,
    assess_route_sanity,
    customer_location_label,
    deduplicate_location_candidates,
    is_pickup_precise,
)


def test_location_exposes_provider_neutral_formatted_address() -> None:
    location = ResolvedLocation(
        "Kota Junction, Kota",
        Decimal("25.223000"),
        Decimal("75.880000"),
        display_name="Kota Junction",
        provider=" MAPPLS ",
        provider_place_id=" place-123 ",
    )

    assert location.formatted_address == "Kota Junction, Kota"
    assert location.display_name == "Kota Junction"
    assert location.provider == "mappls"
    assert location.provider_place_id == "place-123"


def test_location_rejects_provider_place_id_without_provider() -> None:
    with pytest.raises(DomainValidationError):
        ResolvedLocation(
            "Kota Junction",
            Decimal("25.223000"),
            Decimal("75.880000"),
            provider_place_id="place-123",
        )


def candidate(name, place_id, latitude, *, locality="Railway Colony"):
    return LocationCandidate(
        name,
        f"{name}, {locality}, Kota, Rajasthan",
        Decimal(latitude),
        Decimal("75.880000"),
        "google",
        place_id,
        locality=locality,
        city="Kota",
        state="Rajasthan",
        country="India",
        place_types=("train_station",),
    )


def test_location_candidates_deduplicate_only_with_strong_evidence():
    same_id = [
        candidate("Kota Junction", "place-1", "25.223000"),
        candidate("Kota Jn", "place-1", "25.224000"),
    ]
    close_same_text = [
        candidate("Kota Junction", None, "25.223000"),
        candidate("Kota Junction", None, "25.223100"),
    ]
    distinct = [
        candidate("Kota Junction", "place-1", "25.223000"),
        candidate("Kota Junction Area", "place-2", "25.230000"),
    ]

    assert len(deduplicate_location_candidates(same_id)) == 1
    assert len(deduplicate_location_candidates(close_same_text)) == 1
    assert len(deduplicate_location_candidates(distinct)) == 2
    assert customer_location_label(distinct[0]) == (
        "Kota Junction, train station, Railway Colony, Kota, Rajasthan"
    )


def test_route_sanity_rejects_structured_contradictions_not_distance_alone():
    local_origin = ResolvedLocation(
        "One", Decimal("25.200"), Decimal("75.800"), city="Kota", state="Rajasthan"
    )
    local_destination = ResolvedLocation(
        "Two", Decimal("25.210"), Decimal("75.810"), city="Kota", state="Rajasthan"
    )
    suspicious = assess_route_sanity(
        local_origin, local_destination, RouteResult(100_000, 4_000, "ola")
    )
    normal = assess_route_sanity(
        local_origin, local_destination, RouteResult(2_000, 600, "ola")
    )
    long_origin = ResolvedLocation(
        "Kota", Decimal("25.2"), Decimal("75.8"), city="Kota", state="Rajasthan"
    )
    long_destination = ResolvedLocation(
        "Jaipur", Decimal("26.9"), Decimal("75.8"), city="Jaipur", state="Rajasthan"
    )
    legitimate_long = assess_route_sanity(
        long_origin, long_destination, RouteResult(250_000, 14_000, "ola")
    )

    assert suspicious.status is RouteSanityStatus.FAILED
    assert suspicious.reason == "same_locality_route_detour"
    assert normal.status is RouteSanityStatus.PASSED
    assert legitimate_long.status is RouteSanityStatus.PASSED


@pytest.mark.parametrize(
    "place_types",
    [("street_address",), ("premise",), ("train_station",), ("point_of_interest",)],
)
def test_specific_provider_types_are_precise_pickups(place_types) -> None:
    assert is_pickup_precise(
        ResolvedLocation("Specific", Decimal("25"), Decimal("75"), place_types=place_types)
    )


@pytest.mark.parametrize(
    "place_types", [None, ("locality", "political"), ("sublocality",), ("route",)]
)
def test_broad_or_missing_provider_types_fail_pickup_precision(place_types) -> None:
    assert not is_pickup_precise(
        ResolvedLocation("Broad", Decimal("25"), Decimal("75"), place_types=place_types)
    )
