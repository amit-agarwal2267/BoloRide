from decimal import Decimal

import pytest

from boloride.config import Settings
from boloride.domain.exceptions import (
    DomainValidationError,
    LocationConfigurationError,
    LocationNotFoundError,
)
from boloride.domain.models.location import LocationCandidate, LocationSearchContext
from boloride.integrations.maps.google_maps import GoogleMapsProvider
from boloride.integrations.maps.router import MapsRouter
from boloride.services.location_service import LocationService
from boloride.tools.location import search_locations


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(self.payload)


class FakeGeopyLocation:
    address = "Kota Junction, Kota, Rajasthan, India"
    latitude = "25.2138"
    longitude = "75.8648"
    raw = {
        "name": "Kota Junction",
        "display_name": "Kota Junction, Kota, Rajasthan, India",
        "osm_type": "node",
        "osm_id": 123,
        "address": {
            "city": "Kota",
            "state": "Rajasthan",
            "country": "India",
        },
    }





def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://u:p@postgres/db",
        "langfuse_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def google_payload() -> dict[str, object]:
    return {
        "places": [
            {
                "formattedAddress": "Kota Junction, Kota, Rajasthan, India",
                "displayName": {"text": "Kota Junction"},
                "id": "google-place-1",
                "addressComponents": [
                    {"longText": "Kota", "types": ["locality", "political"]},
                    {
                        "longText": "Rajasthan",
                        "types": ["administrative_area_level_1", "political"],
                    },
                    {"longText": "India", "types": ["country", "political"]},
                ],
                "location": {"latitude": 25.2138, "longitude": 75.8648},
            }
        ],
    }


@pytest.mark.asyncio
async def test_google_provider_normalizes_response_and_context() -> None:
    client = FakeClient(google_payload())
    provider = GoogleMapsProvider(
        settings(google_maps_api_key="test-key"), client=client  # type: ignore[arg-type]
    )

    candidates = await provider.search_location(
        "Kota railway station",
        LocationSearchContext(
            country="IN", city="Kota", state="Rajasthan", language="en"
        ),
    )

    assert candidates[0].provider == "google"
    assert candidates[0].provider_place_id == "google-place-1"
    assert candidates[0].city == "Kota"
    assert candidates[0].latitude == Decimal("25.2138")
    assert client.calls[0]["json"] == {
        "textQuery": "Kota railway station, Kota, Rajasthan, in",
        "pageSize": 5,
        "languageCode": "en",
        "regionCode": "IN",
    }





def test_router_does_not_fallback_or_require_unselected_credentials() -> None:
    ola = MapsRouter(settings(maps_provider="ola", ola_maps_api_key="ola-key"))
    assert ola.provider_name == "ola"
    assert ola.get_provider().provider_name == "ola"

    unavailable_settings = settings(maps_provider="ola")
    object.__setattr__(unavailable_settings, "maps_provider", "missing_provider")
    unavailable = MapsRouter(unavailable_settings)
    with pytest.raises(LocationConfigurationError, match="not implemented"):
        unavailable.get_provider()


def test_selected_google_provider_requires_only_google_maps_key() -> None:
    router = MapsRouter(settings(maps_provider="google"))
    with pytest.raises(LocationConfigurationError, match="GOOGLE_MAPS_API_KEY"):
        router.get_provider()


@pytest.mark.asyncio
async def test_location_service_normalizes_limits_and_preserves_candidates() -> None:
    candidates = [
        LocationCandidate(
            display_name=f"Place {index}",
            formatted_address=f"Place {index}, Kota",
            latitude=Decimal("25.18"),
            longitude=Decimal("75.83") + Decimal(index) / Decimal("100"),
            provider="test",
        )
        for index in range(3)
    ]

    class Provider:
        provider_name = "test"

        async def search_location(
            self, query: str, context: LocationSearchContext | None = None
        ) -> list[LocationCandidate]:
            assert query == "Kota station"
            assert context is not None
            assert context.city == "Kota"
            return candidates

        async def enrich_candidate(
            self, candidate: LocationCandidate
        ) -> LocationCandidate:
            return candidate

    class Router:
        def get_provider(self) -> Provider:
            return Provider()

    service = LocationService(Router(), max_candidates=2)  # type: ignore[arg-type]
    result = await service.search_locations("  Kota   station ", city="Kota")

    assert len(result) == 2
    assert result[0].display_name == "Place 0"


@pytest.mark.asyncio
async def test_location_service_raises_for_no_results() -> None:
    class Provider:
        provider_name = "test"

        async def search_location(
            self, query: str, context: LocationSearchContext | None = None
        ) -> list[LocationCandidate]:
            return []

    class Router:
        def get_provider(self) -> Provider:
            return Provider()

    with pytest.raises(LocationNotFoundError):
        await LocationService(Router()).search_locations("unknown place")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_location_tool_delegates_to_service() -> None:
    class Service:
        async def search_locations(self, query: str, **kwargs: object) -> list[str]:
            assert query == "Kota station"
            assert kwargs["city"] == "Kota"
            return ["candidate"]

    assert await search_locations(Service(), "Kota station", city="Kota") == [
        "candidate"
    ]  # type: ignore[arg-type]


def test_candidate_requires_valid_coordinates() -> None:
    with pytest.raises(DomainValidationError):
        LocationCandidate(
            display_name="Invalid",
            formatted_address="Invalid",
            latitude=Decimal("91"),
            longitude=Decimal("75"),
            provider="test",
        )
