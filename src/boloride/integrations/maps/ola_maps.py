from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import httpx

from boloride.config import Settings
from boloride.domain.exceptions import LocationConfigurationError, LocationProviderError, LocationProviderTimeoutError
from boloride.domain.models.location import LocationCandidate, LocationSearchContext
from boloride.integrations.maps.google_maps import contextual_query, optional_string


class OlaMapsProvider:
    provider_name = "ola"
    attribution = "Powered by Ola Maps"
    endpoint = "https://api.olamaps.io/places/v1/textsearch"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        key = settings.ola_maps_api_key
        if key is None or not key.get_secret_value().strip():
            raise LocationConfigurationError("OLA_MAPS_API_KEY is required for the Ola Maps provider")
        self._api_key = key.get_secret_value()
        self._client = client or httpx.AsyncClient(timeout=settings.maps_timeout_seconds)
        self._owns_client = client is None

    async def search_location(self, query: str, context: LocationSearchContext | None = None) -> list[LocationCandidate]:
        try:
            response = await self._client.get(self.endpoint, params={"input": contextual_query(query, context), "api_key": self._api_key}, headers={"X-Request-Id": str(uuid4())})
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise LocationProviderTimeoutError("Ola Maps request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise LocationProviderError(f"Ola Maps request failed with status {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LocationProviderError("Ola Maps request failed") from exc
        except ValueError as exc:
            raise LocationProviderError("Ola Maps returned invalid JSON") from exc
        items: object = payload.get("predictions", payload.get("results", [])) if isinstance(payload, Mapping) else []
        if not isinstance(items, list):
            raise LocationProviderError("Ola Maps returned an invalid results list")
        return [candidate for item in items if (candidate := self._candidate(item)) is not None]

    def _candidate(self, item: object) -> LocationCandidate | None:
        if not isinstance(item, Mapping):
            return None
        location = item.get("location")
        geometry = item.get("geometry")
        if not isinstance(location, Mapping) and isinstance(geometry, Mapping):
            location = geometry.get("location")
        if not isinstance(location, Mapping):
            return None
        try:
            latitude = Decimal(str(location.get("lat", location.get("latitude"))))
            longitude = Decimal(str(location.get("lng", location.get("longitude"))))
        except (InvalidOperation, TypeError, ValueError):
            return None
        structured = item.get("structured_formatting")
        display_name = optional_string(structured.get("main_text")) if isinstance(structured, Mapping) else None
        display_name = display_name or optional_string(item.get("name"))
        address = optional_string(item.get("formatted_address")) or optional_string(item.get("description"))
        display_name = display_name or address
        if display_name is None or address is None:
            return None
        return LocationCandidate(display_name, address, latitude, longitude, self.provider_name, optional_string(item.get("place_id", item.get("placeId"))), locality=optional_string(item.get("locality")), city=optional_string(item.get("city")), state=optional_string(item.get("state")), country=optional_string(item.get("country")))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
