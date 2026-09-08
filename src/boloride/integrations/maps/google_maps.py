from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from boloride.config import Settings
from boloride.domain.exceptions import LocationConfigurationError, LocationProviderError, LocationProviderTimeoutError
from boloride.domain.models.location import LocationCandidate, LocationSearchContext


class GoogleMapsProvider:
    provider_name = "google"
    endpoint = "https://places.googleapis.com/v1/places:searchText"
    field_mask = "places.id,places.displayName,places.formattedAddress,places.location,places.addressComponents"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        key = settings.google_maps_api_key
        if key is None or not key.get_secret_value().strip():
            raise LocationConfigurationError("GOOGLE_MAPS_API_KEY is required for the Google maps provider")
        self._api_key = key.get_secret_value()
        self._limit = settings.maps_max_candidates
        self._client = client or httpx.AsyncClient(timeout=settings.maps_timeout_seconds)
        self._owns_client = client is None

    async def search_location(self, query: str, context: LocationSearchContext | None = None) -> list[LocationCandidate]:
        body: dict[str, Any] = {"textQuery": contextual_query(query, context), "pageSize": min(self._limit, 20)}
        if context and context.language:
            body["languageCode"] = context.language
        if context and context.country:
            body["regionCode"] = context.country.upper()
        try:
            response = await self._client.post(self.endpoint, headers={"X-Goog-Api-Key": self._api_key, "X-Goog-FieldMask": self.field_mask}, json=body)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise LocationProviderTimeoutError("Google Maps request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise LocationProviderError(f"Google Maps request failed with status {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LocationProviderError("Google Maps request failed") from exc
        except ValueError as exc:
            raise LocationProviderError("Google Maps returned invalid JSON") from exc
        places = payload.get("places", []) if isinstance(payload, Mapping) else []
        if not isinstance(places, list):
            raise LocationProviderError("Google Maps returned an invalid places list")
        return [candidate for place in places if (candidate := self._candidate(place)) is not None]

    def _candidate(self, place: object) -> LocationCandidate | None:
        if not isinstance(place, Mapping):
            return None
        location, display = place.get("location"), place.get("displayName")
        if not isinstance(location, Mapping) or not isinstance(display, Mapping):
            return None
        try:
            latitude = Decimal(str(location["latitude"]))
            longitude = Decimal(str(location["longitude"]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            return None
        display_name = optional_string(display.get("text"))
        address = optional_string(place.get("formattedAddress"))
        if display_name is None or address is None:
            return None
        components = google_components(place.get("addressComponents"))
        return LocationCandidate(display_name, address, latitude, longitude, self.provider_name, optional_string(place.get("id")), locality=components.get("sublocality") or components.get("neighborhood"), city=components.get("locality"), state=components.get("administrative_area_level_1"), country=components.get("country"))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def contextual_query(query: str, context: LocationSearchContext | None) -> str:
    if context is None:
        return query
    return ", ".join((query, *(value for value in (context.city, context.state, context.country) if value)))


def google_components(value: object) -> dict[str, str]:
    result: dict[str, str] = {}
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            name, kinds = optional_string(item.get("longText")), item.get("types")
            if name and isinstance(kinds, list):
                for kind in kinds:
                    if isinstance(kind, str):
                        result.setdefault(kind, name)
    return result


def optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
