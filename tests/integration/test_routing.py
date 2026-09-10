from decimal import Decimal

import httpx
import pytest

from boloride.config import Settings
from boloride.domain.exceptions import RouteProviderError, RouteSanityError
from boloride.domain.models.location import ResolvedLocation, RouteResult, TollStatus
from boloride.integrations.maps.google_maps import GoogleMapsProvider
from boloride.integrations.maps.ola_maps import OlaMapsProvider
from boloride.integrations.maps.router import MapsRouter
from boloride.services.location_service import LocationService


def settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://u:p@postgres/db",
        "langfuse_enabled": False,
        "ola_maps_api_key": "ola-key",
        "google_maps_api_key": "google-key",
    }
    values.update(overrides)
    return Settings(**values)


def locations() -> tuple[ResolvedLocation, ResolvedLocation]:
    return (
        ResolvedLocation("Home", Decimal("25.18"), Decimal("75.83")),
        ResolvedLocation("Station", Decimal("25.22"), Decimal("75.88")),
    )


@pytest.mark.asyncio
async def test_ola_normalizes_route_distance_and_duration(httpx_mock) -> None:
    httpx_mock.add_response(
        json={"routes": [{"legs": [{"distance": 4321, "duration": 765}]}]}
    )
    provider = OlaMapsProvider(settings())

    route = await provider.get_route(*locations())

    assert route == RouteResult(4321, 765, "ola", TollStatus.UNKNOWN)
    assert httpx_mock.get_request().url.path == "/routing/v1/directions"
    await provider.aclose()


@pytest.mark.asyncio
async def test_google_normalizes_route_and_reliable_toll(httpx_mock) -> None:
    httpx_mock.add_response(
        json={
            "routes": [
                {
                    "distanceMeters": 5432,
                    "duration": "900s",
                    "travelAdvisory": {
                        "tollInfo": {
                            "estimatedPrice": [
                                {"currencyCode": "INR", "units": "75", "nanos": 500000000}
                            ]
                        }
                    },
                }
            ]
        }
    )
    provider = GoogleMapsProvider(settings())

    route = await provider.get_route(*locations())

    assert route.distance_meters == 5432
    assert route.duration_seconds == 900
    assert route.toll_status is TollStatus.ESTIMATE_AVAILABLE
    assert route.toll_estimate == Decimal("75.5")
    await provider.aclose()


class StubRouteProvider:
    def __init__(self, name: str, result: RouteResult | Exception) -> None:
        self.provider_name = name
        self.result = result
        self.calls = 0

    async def get_route(self, origin, destination) -> RouteResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_router_falls_back_from_ola_to_google() -> None:
    ola = StubRouteProvider("ola", RouteProviderError("bad route"))
    google = StubRouteProvider("google", RouteResult(2000, 120, "google"))
    router = MapsRouter(settings())
    router._route_providers = [ola, google]  # type: ignore[assignment]

    result = await router.get_route(*locations())

    assert result.provider == "google"
    assert ola.calls == 1
    assert google.calls == 1


@pytest.mark.asyncio
async def test_both_route_providers_fail_without_distance_fallback() -> None:
    router = MapsRouter(settings())
    router._route_providers = [  # type: ignore[assignment]
        StubRouteProvider("ola", RouteProviderError("failed")),
        StubRouteProvider("google", RouteProviderError("failed")),
    ]

    with pytest.raises(RouteProviderError, match="route resolution failed"):
        await router.get_route(*locations())


@pytest.mark.asyncio
async def test_malformed_ola_route_is_normalized_as_failure(httpx_mock) -> None:
    httpx_mock.add_response(json={"routes": [{"legs": [{"distance": -1, "duration": 2}]}]})
    provider = OlaMapsProvider(settings())
    with pytest.raises(RouteProviderError, match="malformed"):
        await provider.get_route(*locations())
    await provider.aclose()


@pytest.mark.asyncio
async def test_route_http_failure_is_normalized(httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("late"))
    provider = OlaMapsProvider(settings())
    with pytest.raises(RouteProviderError, match="timed out"):
        await provider.get_route(*locations())
    await provider.aclose()


@pytest.mark.asyncio
async def test_location_service_retries_after_suspicious_route_and_uses_sane_fallback() -> None:
    origin = ResolvedLocation(
        "One", Decimal("25.20"), Decimal("75.80"), city="Kota", state="Rajasthan"
    )
    destination = ResolvedLocation(
        "Two", Decimal("25.21"), Decimal("75.81"), city="Kota", state="Rajasthan"
    )
    suspicious = StubRouteProvider("ola", RouteResult(100_000, 5_000, "ola"))
    sane = StubRouteProvider("google", RouteResult(2_000, 600, "google"))
    router = MapsRouter(settings())
    router._route_providers = [suspicious, sane]  # type: ignore[assignment]

    result = await LocationService(router).get_route(origin, destination)

    assert result.provider == "google"
    assert suspicious.calls == sane.calls == 1


@pytest.mark.asyncio
async def test_all_structurally_suspicious_routes_block_quote_path() -> None:
    origin = ResolvedLocation(
        "One", Decimal("25.20"), Decimal("75.80"), city="Kota", state="Rajasthan"
    )
    destination = ResolvedLocation(
        "Two", Decimal("25.21"), Decimal("75.81"), city="Kota", state="Rajasthan"
    )
    router = MapsRouter(settings())
    router._route_providers = [  # type: ignore[assignment]
        StubRouteProvider("ola", RouteResult(100_000, 5_000, "ola")),
        StubRouteProvider("google", RouteResult(120_000, 6_000, "google")),
    ]

    with pytest.raises(RouteSanityError, match="clarification"):
        await LocationService(router).get_route(origin, destination)
