from boloride.config import Settings
from boloride.domain.exceptions import (
    LocationConfigurationError,
    RouteProviderError,
)
from boloride.domain.models.location import ResolvedLocation, RouteResult
from boloride.integrations.maps.base import MapsProvider
from boloride.integrations.maps.google_maps import GoogleMapsProvider
from boloride.integrations.maps.ola_maps import OlaMapsProvider


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
