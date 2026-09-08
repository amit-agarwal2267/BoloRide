from decimal import Decimal

import pytest

from boloride.domain.exceptions import DomainValidationError
from boloride.domain.models.location import ResolvedLocation


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