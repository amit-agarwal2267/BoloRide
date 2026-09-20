from decimal import Decimal

import pytest

from boloride.config import Settings
from boloride.domain.exceptions import (
    DomainValidationError,
    LocationConfigurationError,
    LocationNotFoundError,
)
from boloride.domain.models.location import LocationCandidate, LocationSearchContext
from boloride.domain.models.location import LocationResolutionStatus
from boloride.integrations.maps.google_maps import GoogleMapsProvider, contextual_query
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
        "google_maps_api_key": None,
        "ola_maps_api_key": None,
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


def test_customer_city_is_enriched_without_inventing_state() -> None:
    context = LocationSearchContext(country="IN", city="Indore")

    assert contextual_query("Sarafa Bazaar", context) == "Sarafa Bazaar, Indore, in"
    assert context.state is None


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
        "pageSize": 3,
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
async def test_resolve_query_collapses_strong_duplicate_candidates() -> None:
    duplicate_one = LocationCandidate(
        "Kota Junction",
        "Kota Junction, Railway Colony, Kota",
        Decimal("25.223000"),
        Decimal("75.880000"),
        "google",
        "same-place",
        city="Kota",
        state="Rajasthan",
        country="India",
    )
    duplicate_two = LocationCandidate(
        "Kota Jn",
        "Kota Junction Railway Station, Kota",
        Decimal("25.224000"),
        Decimal("75.881000"),
        "google",
        "same-place",
        city="Kota",
        state="Rajasthan",
        country="India",
    )

    class Router:
        async def search_location(self, query, context):
            return [duplicate_one, duplicate_two], "google", True, False

        def get_search_providers(self):
            return [self.get_provider()]

        def get_provider(self):
            class Provider:
                provider_name = "google"

                async def enrich_candidate(self, candidate):
                    return candidate

            return Provider()

    result = await LocationService(Router()).resolve_query(  # type: ignore[arg-type]
        "Kota Junction", city="Kota", state="Rajasthan"
    )

    assert result.status is LocationResolutionStatus.RESOLVED
    assert result.location is not None
    assert result.location.provider_place_id == "same-place"


@pytest.mark.asyncio
async def test_cross_provider_consensus_auto_resolves_same_place() -> None:
    ola = LocationCandidate(
        "Durgapura Railway Station",
        "Durgapura Railway Station, Jaipur, Rajasthan",
        Decimal("26.8520"),
        Decimal("75.7860"),
        "ola",
        "ola-durgapura",
        city="Jaipur",
        state="Rajasthan",
        country="India",
        place_types=("train_station",),
    )
    google = LocationCandidate(
        "Durgapura",
        "Durgapura Railway Station, Jaipur, Rajasthan, India",
        Decimal("26.8521"),
        Decimal("75.7861"),
        "google",
        "google-durgapura",
        city="Jaipur",
        state="Rajasthan",
        country="India",
        place_types=("train_station",),
    )

    class Provider:
        def __init__(self, name):
            self.provider_name = name

        async def enrich_candidate(self, candidate):
            return candidate

    class Router:
        async def search_location(self, query, context):
            return [ola, google], "ola+google", False, False

        def get_search_providers(self):
            return [Provider("ola"), Provider("google")]

        def get_provider(self):
            return Provider("ola")

    result = await LocationService(Router()).resolve_query(  # type: ignore[arg-type]
        "Durgapura Railway Station", city="Jaipur", state="Rajasthan"
    )

    assert result.status is LocationResolutionStatus.RESOLVED
    assert result.location is not None
    assert result.location.city == "Jaipur"
    assert result.provider == "consensus"


@pytest.mark.asyncio
async def test_partial_provider_matches_require_confirmation_and_expose_at_most_three() -> None:
    names = (
        "Radiant Clinic",
        "Signature Hospital",
        "City Railway Station",
        "Aari Skin Centre",
        "World Trade Park",
        "Sindhi Camp Bus Stand",
    )
    values = [
        LocationCandidate(
            name,
            f"{name}, Jaipur, Rajasthan",
            Decimal("26.80") + Decimal(index) / Decimal("25"),
            Decimal("75.70") + Decimal(index) / Decimal("25"),
            "ola" if index < 3 else "google",
            f"place-{index}",
            city="Jaipur",
            state="Rajasthan",
        )
        for index, name in enumerate(names)
    ]

    class Router:
        async def search_location(self, query, context):
            return values, "ola+google", False, False

        def get_search_providers(self):
            return []

        def get_provider(self):
            raise AssertionError("ambiguous candidates must not be auto-resolved")

    result = await LocationService(Router()).resolve_query(  # type: ignore[arg-type]
        "Jaipur", city="Jaipur", state="Rajasthan"
    )

    assert result.status is LocationResolutionStatus.CLARIFICATION_REQUIRED
    assert 1 <= len(result.candidates) <= 3


@pytest.mark.asyncio
async def test_maps_router_queries_both_search_providers_and_caps_each_to_three() -> None:
    calls = []

    class Provider:
        def __init__(self, name):
            self.provider_name = name

        async def search_location(self, query, context):
            calls.append(self.provider_name)
            return [
                LocationCandidate(
                    f"{self.provider_name}-{index}",
                    f"{self.provider_name}-{index}, Jaipur",
                    Decimal("26.9"),
                    Decimal("75.8") + Decimal(index) / Decimal("100"),
                    self.provider_name,
                    f"{self.provider_name}-{index}",
                    city="Jaipur",
                )
                for index in range(5)
            ]

    router = MapsRouter(settings())
    router._route_providers = [Provider("ola"), Provider("google")]  # type: ignore[assignment]

    candidates, provider, fallback, unavailable = await router.search_location(
        "station", LocationSearchContext(city="Jaipur")
    )

    assert set(calls) == {"ola", "google"}
    assert len([item for item in candidates if item.provider == "ola"]) == 3
    assert len([item for item in candidates if item.provider == "google"]) == 3
    assert provider == "ola+google"
    assert fallback is False
    assert unavailable is False


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


def test_nearby_equivalent_provider_results_collapse_to_one_place() -> None:
    first = LocationCandidate(
        "Central Junction Railway Station",
        "Central Junction, Sample City",
        Decimal("12.97160"),
        Decimal("77.59460"),
        "ola",
        "ola-central",
        city="Sample City",
        state="Sample State",
        place_types=("train_station",),
    )
    second = LocationCandidate(
        "Central Railway Station",
        "Central Junction, Sample City",
        Decimal("12.97175"),
        Decimal("77.59475"),
        "google",
        "google-central",
        city="Sample City",
        state="Sample State",
        place_types=("train_station",),
    )

    collapsed = deduplicate_location_candidates([first, second])

    assert len(collapsed) == 1


def test_nearby_distinct_platforms_are_not_collapsed() -> None:
    first = LocationCandidate(
        "Central Junction Platform 1",
        "Platform 1, Central Junction, Sample City",
        Decimal("12.97160"),
        Decimal("77.59460"),
        "ola",
        "ola-platform-1",
        city="Sample City",
        state="Sample State",
        place_types=("train_station",),
    )
    second = LocationCandidate(
        "Central Junction Platform 4",
        "Platform 4, Central Junction, Sample City",
        Decimal("12.97172"),
        Decimal("77.59472"),
        "google",
        "google-platform-4",
        city="Sample City",
        state="Sample State",
        place_types=("train_station",),
    )

    distinct = deduplicate_location_candidates([first, second])

    assert len(distinct) == 2
