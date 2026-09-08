from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import httpx

from boloride.config import Settings
from boloride.domain.exceptions import (
    LocationConfigurationError,
    LocationProviderError,
    LocationProviderTimeoutError,
    RouteProviderError,
)
from boloride.domain.models.location import (
    LocationCandidate,
    LocationSearchContext,
    ResolvedLocation,
    RouteResult,
    TollStatus,
)
from boloride.integrations.maps.google_maps import (
    contextual_query,
    normalized_types,
    optional_string,
)


class OlaMapsProvider:
    provider_name = "ola"
    attribution = "Powered by Ola Maps"
    endpoint = "https://api.olamaps.io/places/v1/textsearch"
    details_endpoint = "https://api.olamaps.io/places/v1/details"
    route_endpoint = "https://api.olamaps.io/routing/v1/directions"

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
        return LocationCandidate(display_name, address, latitude, longitude, self.provider_name, optional_string(item.get("place_id", item.get("placeId"))), locality=optional_string(item.get("locality")), city=optional_string(item.get("city")), state=optional_string(item.get("state")), country=optional_string(item.get("country")), place_types=normalized_types(item.get("types", item.get("categories"))))

    async def enrich_candidate(self, candidate: LocationCandidate) -> LocationCandidate:
        if candidate.place_types is not None or not candidate.provider_place_id:
            return candidate
        try:
            response = await self._client.get(
                self.details_endpoint,
                params={
                    "place_id": candidate.provider_place_id,
                    "api_key": self._api_key,
                },
                headers={"X-Request-Id": str(uuid4())},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise LocationProviderTimeoutError("Ola Place Details timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise LocationProviderError(
                f"Ola Place Details failed with status {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise LocationProviderError("Ola Place Details request failed") from exc
        except ValueError as exc:
            raise LocationProviderError("Ola Place Details returned invalid JSON") from exc
        details = _ola_details(payload)
        return replace(candidate, place_types=_ola_place_types(details))

    async def get_route(
        self, origin: ResolvedLocation, destination: ResolvedLocation
    ) -> RouteResult:
        try:
            response = await self._client.post(
                self.route_endpoint,
                params={
                    "origin": f"{origin.latitude},{origin.longitude}",
                    "destination": f"{destination.latitude},{destination.longitude}",
                    "mode": "driving",
                    "steps": "false",
                    "overview": "false",
                    "api_key": self._api_key,
                },
                headers={"X-Request-Id": str(uuid4())},
            )
            response.raise_for_status()
            payload = response.json()
            return self._route_result(payload)
        except httpx.TimeoutException as exc:
            raise RouteProviderError("Ola Directions request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise RouteProviderError(
                f"Ola Directions failed with status {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise RouteProviderError("Ola Directions request failed") from exc
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise RouteProviderError("Ola Directions returned malformed metrics") from exc

    def _route_result(self, payload: object) -> RouteResult:
        if not isinstance(payload, Mapping):
            raise ValueError("route payload must be an object")
        routes = payload.get("routes")
        if not isinstance(routes, list) or not routes or not isinstance(routes[0], Mapping):
            raise ValueError("route result is missing")
        route = routes[0]
        distance = route.get("distance")
        duration = route.get("duration")
        if distance is None or duration is None:
            legs = route.get("legs")
            if not isinstance(legs, list) or not legs:
                raise ValueError("route metrics are missing")
            if distance is None:
                distance = sum(_numeric_metric(leg, "distance") for leg in legs)
            if duration is None:
                duration = sum(_numeric_metric(leg, "duration") for leg in legs)
        return RouteResult(
            _whole_metric(distance, "distance"),
            _whole_metric(duration, "duration"),
            self.provider_name,
            TollStatus.UNKNOWN,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _ola_details(payload: object) -> Mapping[object, object]:
    if not isinstance(payload, Mapping):
        return {}
    for key in ("result", "place", "data"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return payload


def _ola_place_types(details: Mapping[object, object]) -> tuple[str, ...] | None:
    return normalized_types(details.get("types", details.get("categories")))


def _numeric_metric(value: object, key: str) -> Decimal:
    if not isinstance(value, Mapping):
        raise ValueError(f"route {key} is invalid")
    return Decimal(str(value.get(key)))


def _whole_metric(value: object, key: str) -> int:
    metric = Decimal(str(value))
    if metric < 0 or metric != metric.to_integral_value():
        raise ValueError(f"route {key} is invalid")
    return int(metric)
