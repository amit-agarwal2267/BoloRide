from decimal import Decimal

import pytest

from boloride.config import Settings
from boloride.domain.exceptions import LocationProviderError
from boloride.domain.models.location import (
    LocationCandidate,
    LocationClarificationReason,
    LocationResolutionStatus,
)
from boloride.services.location_service import LocationService
from boloride.integrations.maps.router import MapsRouter


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
async def test_unknown_geography_searches_provider_without_city_or_state_bias():
    value = LocationCandidate(
        "Sarafa Bazaar",
        "Sarafa Bazaar, Indore, India",
        Decimal("22.72"),
        Decimal("75.86"),
        "ola",
        "sarafa-indore",
        city="Indore",
        state="Madhya Pradesh",
        country="India",
    )
    router = Router([value])

    result = await LocationService(router).resolve_query("Sarafa Bazaar")

    assert result.status is LocationResolutionStatus.LIKELY_MATCH_CONFIRMATION_REQUIRED
    assert result.location is None
    assert result.candidates == (value,)
    assert router.context.city is None
    assert router.context.state is None


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


@pytest.mark.asyncio
async def test_provider_fallback_preserves_explicit_geography_context():
    contexts = []

    class Provider:
        def __init__(self, name, fail=False):
            self.provider_name = name
            self.fail = fail

        async def search_location(self, query, context):
            contexts.append(context)
            if self.fail:
                raise LocationProviderError("unavailable")
            return [candidate("A", provider=self.provider_name)]

        async def enrich_candidate(self, value):
            return value

    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@postgres/db",
        langfuse_enabled=False,
        ola_maps_api_key="ola-test",
        google_maps_api_key="google-test",
    )
    router = MapsRouter(settings)
    router._route_providers = [  # type: ignore[assignment]
        Provider("ola", fail=True),
        Provider("google"),
    ]

    result = await LocationService(router).resolve_query(
        "Indore Junction", city="Indore", state="Madhya Pradesh"
    )

    assert result.status is LocationResolutionStatus.RESOLVED
    assert [(item.city, item.state) for item in contexts] == [
        ("Indore", "Madhya Pradesh"),
        ("Indore", "Madhya Pradesh"),
    ]


@pytest.mark.asyncio
async def test_provider_fallback_preserves_unknown_geography_without_bias():
    contexts = []

    class Provider:
        def __init__(self, name, fail=False):
            self.provider_name = name
            self.fail = fail

        async def search_location(self, query, context):
            contexts.append(context)
            if self.fail:
                raise LocationProviderError("unavailable")
            return [candidate("Phoenix Citadel", provider=self.provider_name)]

        async def enrich_candidate(self, value):
            return value

    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@postgres/db",
        langfuse_enabled=False,
        ola_maps_api_key="ola-test",
        google_maps_api_key="google-test",
    )
    router = MapsRouter(settings)
    router._route_providers = [  # type: ignore[assignment]
        Provider("ola", fail=True),
        Provider("google"),
    ]

    result = await LocationService(router).resolve_query("Phoenix Mall")

    assert result.status is LocationResolutionStatus.LIKELY_MATCH_CONFIRMATION_REQUIRED
    assert [(item.city, item.state) for item in contexts] == [
        (None, None),
        (None, None),
    ]
