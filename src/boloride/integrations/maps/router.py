from boloride.config import Settings
from boloride.domain.exceptions import LocationConfigurationError
from boloride.integrations.maps.base import MapsProvider
from boloride.integrations.maps.google_maps import GoogleMapsProvider
from boloride.integrations.maps.ola_maps import OlaMapsProvider


class MapsRouter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider: MapsProvider | None = None

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

    async def aclose(self) -> None:
        if self._provider is not None:
            await self._provider.aclose()
