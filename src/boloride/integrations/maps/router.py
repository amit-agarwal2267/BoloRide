import logging
from contextlib import contextmanager
from time import monotonic
from typing import Iterator

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
from boloride.observability.tracing import ObservabilityContext, Observation

logger = logging.getLogger(__name__)


class MapsRouter:
    def __init__(
        self, settings: Settings, observability: ObservabilityContext | None = None
    ) -> None:
        self._settings = settings
        self._provider: MapsProvider | None = None
        self._route_providers: list[MapsProvider] | None = None
        self._observability = observability

    @contextmanager
    def provider_observation(
        self, provider: str, operation: str, attempt_order: int
    ) -> Iterator[Observation | None]:
        if self._observability is None:
            yield None
            return
        with self._observability.observe(
            f"provider.{provider}",
            metadata={"provider": provider, "operation": operation, "attempt_order": attempt_order},
        ) as observation:
            yield observation

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

    def is_fallback_provider(self, provider_name: str) -> bool:
        names = [provider.provider_name for provider in self.get_route_providers()]
        return provider_name in names[1:]

    def record_fallback_attempt(self) -> None:
        metrics = getattr(self._observability, "metrics", None)
        if metrics is not None:
            metrics.record_maps_fallback()

    async def search_location(
        self, query: str, context: LocationSearchContext
    ) -> tuple[list[LocationCandidate], str | None, bool, bool]:
        failures = 0
        providers = self.get_search_providers()
        for index, provider in enumerate(providers):
            if index == 1:
                self.record_fallback_attempt()
            with self.provider_observation(provider.provider_name, "location_search", index + 1) as observation:
                started_at = monotonic()
                try:
                    candidates = await provider.search_location(query, context)
                except LocationProviderError:
                    failures += 1
                    if observation is not None:
                        observation.update(metadata={"provider": provider.provider_name, "operation": "location_search", "attempt_order": index + 1, "success": False, "failure_category": "provider_unavailable", "duration_ms": (monotonic() - started_at) * 1000})
                    if index == 0:
                        logger.warning("maps_primary_failed", extra={"event": "maps_primary_failed", "provider": provider.provider_name})
                    continue
                if observation is not None:
                    observation.update(metadata={"provider": provider.provider_name, "operation": "location_search", "attempt_order": index + 1, "success": bool(candidates), "candidate_count": len(candidates), "duration_ms": (monotonic() - started_at) * 1000})
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
        for index, provider in enumerate(self.get_route_providers()):
            if index == 1:
                self.record_fallback_attempt()
            with self.provider_observation(provider.provider_name, "route", index + 1) as observation:
                started_at = monotonic()
                try:
                    result = await provider.get_route(origin, destination)
                except RouteProviderError:
                    failures.append(provider.provider_name)
                    if observation is not None:
                        observation.update(metadata={"provider": provider.provider_name, "operation": "route", "attempt_order": index + 1, "success": False, "failure_category": "provider_unavailable", "duration_ms": (monotonic() - started_at) * 1000})
                    continue
                if observation is not None:
                    observation.update(metadata={"provider": provider.provider_name, "operation": "route", "attempt_order": index + 1, "success": True, "duration_ms": (monotonic() - started_at) * 1000})
                return result
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
