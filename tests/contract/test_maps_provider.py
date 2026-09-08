from decimal import Decimal

from boloride.domain.models.location import LocationCandidate


def test_normalized_candidate_has_no_provider_specific_required_identity() -> None:
    candidate = LocationCandidate(
        display_name="Kota railway station",
        formatted_address="Kota railway station, Kota, India",
        latitude=Decimal("25.2138"),
        longitude=Decimal("75.8648"),
        provider="test",
    )

    assert candidate.provider_place_id is None
    assert candidate.to_resolved_location().provider_place_id is None