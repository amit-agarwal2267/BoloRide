from decimal import Decimal

import httpx
import pytest

from boloride.config import Settings
from boloride.domain.exceptions import LocationProviderTimeoutError
from boloride.domain.models.location import AirportClassification, LocationSearchContext
from boloride.integrations.maps.google_maps import GoogleMapsProvider


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@postgres/db",
        langfuse_enabled=False,
        google_maps_api_key="google-key",
    )


@pytest.mark.asyncio
async def test_google_normalizes_new_places_text_search(httpx_mock) -> None:
    httpx_mock.add_response(
        json={
            "places": [
                {
                    "id": "google-1",
                    "displayName": {"text": "Kota Junction"},
                    "formattedAddress": "Kota Junction, Rajasthan, India",
                    "location": {"latitude": 25.2138, "longitude": 75.8648},
                    "types": ["train_station", "transit_station"],
                    "addressComponents": [
                        {"longText": "Kota", "types": ["locality"]},
                        {
                            "longText": "Rajasthan",
                            "types": ["administrative_area_level_1"],
                        },
                    ],
                }
            ]
        }
    )
    provider = GoogleMapsProvider(make_settings())
    results = await provider.search_location(
        "railway station",
        LocationSearchContext(city="Kota", state="Rajasthan", country="IN", language="en"),
    )

    request = httpx_mock.get_request()
    assert request.method == "POST"
    assert request.url.path == "/v1/places:searchText"
    assert request.headers["X-Goog-Api-Key"] == "google-key"
    assert request.headers["X-Goog-FieldMask"]
    assert request.read()
    assert results[0].display_name == "Kota Junction"
    assert results[0].latitude == Decimal("25.2138")
    assert results[0].city == "Kota"
    assert results[0].provider == "google"
    assert results[0].place_types == ("train_station", "transit_station")
    assert not hasattr(results[0], "raw")
    await provider.aclose()


@pytest.mark.asyncio
async def test_google_normalizes_timeout(httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("late"))
    provider = GoogleMapsProvider(make_settings())
    with pytest.raises(LocationProviderTimeoutError):
        await provider.search_location("Kota")
    await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("types", "expected"),
    [
        (["airport", "point_of_interest"], AirportClassification.AIRPORT),
        (["train_station"], AirportClassification.NOT_AIRPORT),
        (None, AirportClassification.UNKNOWN),
    ],
)
async def test_google_airport_classification_uses_structured_types_only(
    httpx_mock, types: list[str] | None, expected: AirportClassification
) -> None:
    place = {
        "id": "google-place",
        "displayName": {"text": "Airport wording is not evidence"},
        "formattedAddress": "Airport Road",
        "location": {"latitude": 25.2, "longitude": 75.8},
    }
    if types is not None:
        place["types"] = types
    httpx_mock.add_response(json={"places": [place]})
    provider = GoogleMapsProvider(make_settings())

    result = await provider.search_location("somewhere")

    assert result[0].airport_classification is expected
    await provider.aclose()
