import logging

from boloride.config import Settings
from boloride.domain.exceptions import (
    LocationConfigurationError,
    LocationProviderError,
    RouteProviderError,
)
from boloride.domain.models.location import LocationCandidate, LocationSearchContext, ResolvedLocation, RouteResult
from boloride.integrations.maps.base import MapsProvider
from boloride.integrations.maps.google_maps import GoogleMapsProvider
from boloride.integrations.maps.ola_maps import OlaMapsProvider

logger = logging.getLogger(__name__)


class MapsRouter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider: MapsProvider | None = None
        self._route_providers: list[MapsProvider] | None = None

    @property
    def provider_name(self) -> str:
        return self._settings.maps_provider

    def get_provider(self) -> MapsProvider:
        if self._provider is not None:
            return self._provider
        if self._settings.maps_provider == "google":
            self._provider = GoogleMapsProvider(self._settings)
        elif self._settings.maps_provider == "ola":
            self._provider = OlaMapsProvider(self._settings)
        else:
            raise LocationConfigurationError(
                f"maps provider '{self._settings.maps_provider}' is not implemented"
            )
        return self._provider

    def get_route_providers(self) -> list[MapsProvider]:
        if self._route_providers is not None:
            return self._route_providers
        providers: list[MapsProvider] = []
        for provider_type in (OlaMapsProvider, GoogleMapsProvider):
            if self._provider is not None and isinstance(self._provider, provider_type):
                providers.append(self._provider)
                continue
            try:
                provider = provider_type(self._settings)
            except LocationConfigurationError:
                continue
            providers.append(provider)
        self._route_providers = providers
        return providers

    def get_search_providers(self) -> list[MapsProvider]:
        """Return configured geocoders in the approved Ola -> Google order."""
        return self.get_route_providers()

    async def search_location(
        self, query: str, context: LocationSearchContext
    ) -> tuple[list[LocationCandidate], str | None, bool, bool]:
        failures = 0
        providers = self.get_search_providers()
        for index, provider in enumerate(providers):
            try:
                candidates = await provider.search_location(query, context)
            except LocationProviderError:
                failures += 1
                if index == 0:
                    logger.warning("maps_primary_failed", extra={"event": "maps_primary_failed", "provider": provider.provider_name})
                continue
            if candidates:
                if index > 0:
                    logger.info("maps_fallback_used", extra={"event": "maps_fallback_used", "provider": provider.provider_name})
                return candidates, provider.provider_name, index > 0, False
            # A genuine no-result may still be provider-specific, so try fallback.
        return [], None, False, bool(providers) and failures == len(providers)

    async def get_route(
        self, origin: ResolvedLocation, destination: ResolvedLocation
    ) -> RouteResult:
        failures: list[str] = []
        for provider in self.get_route_providers():
            try:
                return await provider.get_route(origin, destination)
            except RouteProviderError as exc:
                failures.append(f"{provider.provider_name}: {exc}")
        detail = "; ".join(failures) or "no routing provider is configured"
        raise RouteProviderError(f"route resolution failed: {detail}")

    async def aclose(self) -> None:
        providers = [self._provider] if self._provider is not None else []
        providers.extend(self._route_providers or [])
        closed: set[int] = set()
        for provider in providers:
            if id(provider) not in closed:
                await provider.aclose()
                closed.add(id(provider))
