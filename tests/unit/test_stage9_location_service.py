from decimal import Decimal

import pytest

from boloride.domain.models.location import (
    LocationCandidate,
    LocationClarificationReason,
    LocationResolutionStatus,
)
from boloride.services.location_service import LocationService


def candidate(name: str, *, state: str = "Rajasthan", provider: str = "ola") -> LocationCandidate:
    return LocationCandidate(name, f"{name}, India", Decimal("25"), Decimal("75"), provider, f"id-{name}", city="Kota", state=state, country="India")


class Router:
    def __init__(self, values, unavailable=False):
        self.values = values
        self.unavailable = unavailable
        self.context = None

    async def search_location(self, query, context):
        self.context = context
        return self.values, (self.values[0].provider if self.values else None), False, self.unavailable

    def get_search_providers(self):
        return []

    def get_provider(self):
        raise AssertionError("candidate enrichment should not require a provider here")


@pytest.mark.asyncio
async def test_incomplete_address_without_city_requires_city_and_is_not_defaulted():
    router = Router([])
    result = await LocationService(router).resolve_query("A-95, Silicon City", require_city_context=True)
    assert result.status is LocationResolutionStatus.CLARIFICATION_REQUIRED
    assert result.clarification_reason is LocationClarificationReason.MISSING_CITY
    assert router.context is None


@pytest.mark.asyncio
async def test_provider_ambiguity_is_capped_and_cross_state_is_explicit():
    values = [candidate("A"), candidate("B", state="Madhya Pradesh"), candidate("C"), candidate("D")]
    result = await LocationService(Router(values)).resolve_query("station", city="Kota")
    assert result.status is LocationResolutionStatus.CLARIFICATION_REQUIRED
    assert result.clarification_reason is LocationClarificationReason.AMBIGUOUS_STATE
    assert len(result.candidates) == 3


@pytest.mark.asyncio
async def test_no_result_and_provider_unavailable_are_distinct():
    missing = await LocationService(Router([])).resolve_query("missing")
    unavailable = await LocationService(Router([], unavailable=True)).resolve_query("missing")
    assert missing.status is LocationResolutionStatus.NOT_FOUND
    assert unavailable.status is LocationResolutionStatus.PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_context_radius_is_configuration_at_service_boundary():
    router = Router([candidate("A"), candidate("B")])
    await LocationService(router, urban_radius_meters=1234).resolve_query("station", city="Kota")
    assert router.context.radius_meters == 1234


def test_candidate_has_stable_internal_identifier():
    first = candidate("Station")
    second = candidate("Station")
    assert first.stable_candidate_id == second.stable_candidate_id
