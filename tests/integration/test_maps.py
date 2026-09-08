from decimal import Decimal

import httpx
import pytest

from boloride.config import Settings
from boloride.domain.exceptions import (
    LocationConfigurationError,
    LocationProviderError,
    LocationProviderTimeoutError,
)
from boloride.domain.models.location import LocationCandidate, LocationSearchContext
from boloride.integrations.maps.ola_maps import OlaMapsProvider


def make_settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://u:p@postgres/db",
        "langfuse_enabled": False,
        "ola_maps_api_key": "test-key",
    }
    values.update(overrides)
    return Settings(**values)


def test_ola_requires_key() -> None:
    with pytest.raises(LocationConfigurationError, match="OLA_MAPS_API_KEY"):
        OlaMapsProvider(make_settings(ola_maps_api_key=None))


@pytest.mark.asyncio
async def test_ola_normalizes_text_search_and_context(httpx_mock) -> None:
    httpx_mock.add_response(
        json={
            "predictions": [
                {
                    "description": "Kota Junction, Rajasthan",
                    "place_id": "ola-1",
                    "geometry": {"location": {"lat": 25.1979, "lng": 75.8741}},
                    "structured_formatting": {"main_text": "Kota Junction"},
                }
            ]
        }
    )
    provider = OlaMapsProvider(make_settings())
    results = await provider.search_location(
        "Kota station",
        LocationSearchContext(city="Kota", state="Rajasthan", country="IN"),
    )

    request = httpx_mock.get_request()
    assert request.url.path == "/places/v1/textsearch"
    assert request.url.params["input"] == "Kota station, Kota, Rajasthan, in"
    assert request.url.params["api_key"] == "test-key"
    assert request.headers["X-Request-Id"]
    assert results[0].provider == "ola"
    assert results[0].latitude == Decimal("25.1979")
    assert results[0].provider_place_id == "ola-1"
    assert not hasattr(results[0], "raw")
    await provider.aclose()


@pytest.mark.asyncio
async def test_ola_normalizes_timeout(httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("late"))
    provider = OlaMapsProvider(make_settings())
    with pytest.raises(LocationProviderTimeoutError):
        await provider.search_location("Kota")
    await provider.aclose()


@pytest.mark.asyncio
async def test_ola_skips_malformed_candidates(httpx_mock) -> None:
    httpx_mock.add_response(json={"predictions": [{"description": "No coordinates"}]})
    provider = OlaMapsProvider(make_settings())
    assert await provider.search_location("Kota") == []
    await provider.aclose()


@pytest.mark.asyncio
async def test_ola_normalizes_http_failure(httpx_mock) -> None:
    httpx_mock.add_response(status_code=503)
    provider = OlaMapsProvider(make_settings())
    with pytest.raises(LocationProviderError, match="status 503"):
        await provider.search_location("Kota")
    await provider.aclose()


@pytest.mark.asyncio
async def test_ola_enriches_missing_structured_types_from_place_details(
    httpx_mock,
) -> None:
    httpx_mock.add_response(
        url="https://api.olamaps.io/places/v1/details?place_id=ola-airport&api_key=test-key",
        json={"result": {"types": ["airport", "point_of_interest"]}},
    )
    provider = OlaMapsProvider(make_settings())
    candidate = LocationCandidate(
        "Airport words are not evidence",
        "Some address",
        Decimal("25.18"),
        Decimal("75.83"),
        "ola",
        "ola-airport",
    )

    enriched = await provider.enrich_candidate(candidate)

    assert enriched.place_types == ("airport", "point_of_interest")
    await provider.aclose()


@pytest.mark.asyncio
async def test_ola_missing_type_evidence_remains_unknown(httpx_mock) -> None:
    httpx_mock.add_response(json={"result": {"name": "Airport in display only"}})
    provider = OlaMapsProvider(make_settings())
    candidate = LocationCandidate(
        "Airport in display only",
        "Airport Road",
        Decimal("25.18"),
        Decimal("75.83"),
        "ola",
        "place-1",
    )

    enriched = await provider.enrich_candidate(candidate)

    assert enriched.place_types is None
    assert enriched.airport_classification.value == "unknown"
    await provider.aclose()
