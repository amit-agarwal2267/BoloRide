import logging
from time import monotonic

from boloride.domain.exceptions import DomainValidationError, LocationNotFoundError
from boloride.domain.models.location import (
	LocationCandidate,
	LocationSearchContext,
	ResolvedLocation,
)
from boloride.integrations.maps.router import MapsRouter
from boloride.schemas.location import LocationSchema

logger = logging.getLogger(__name__)


class LocationService:
	def __init__(
		self,
		router: MapsRouter,
		*,
		max_candidates: int = 5,
		default_country: str = "IN",
		default_language: str = "en",
	) -> None:
		self._router = router
		self._max_candidates = max_candidates
		self._default_country = default_country
		self._default_language = default_language

	async def search_locations(
		self,
		query: str,
		*,
		city: str | None = None,
		state: str | None = None,
		country: str | None = None,
		language: str | None = None,
		session_id: str | None = None,
	) -> list[LocationCandidate]:
		normalized_query = " ".join(query.split())
		if not normalized_query:
			raise DomainValidationError("location query cannot be blank")
		context = LocationSearchContext(
			country=country or self._default_country,
			city=city,
			state=state,
			language=language or self._default_language,
		)
		provider = self._router.get_provider()
		started_at = monotonic()
		try:
			candidates = await provider.search_location(normalized_query, context)
		except Exception:
			logger.exception(
				"location_lookup_failed",
				extra={
					"event": "location_lookup_failed",
					"provider": provider.provider_name,
					"query_length": len(normalized_query),
					"success": False,
					"duration_ms": round((monotonic() - started_at) * 1000, 2),
					"session_id": session_id,
				},
			)
			raise
		candidates = candidates[: self._max_candidates]
		duration_ms = round((monotonic() - started_at) * 1000, 2)
		logger.info(
			"location_lookup_completed",
			extra={
				"event": "location_lookup_completed",
				"provider": provider.provider_name,
				"query_length": len(normalized_query),
				"candidate_count": len(candidates),
				"success": bool(candidates),
				"duration_ms": duration_ms,
				"session_id": session_id,
			},
		)
		if not candidates:
			raise LocationNotFoundError(
				f"no locations found for query using {provider.provider_name}"
			)
		return candidates

	def resolve_candidate(self, candidate: LocationCandidate) -> ResolvedLocation:
		return candidate.to_resolved_location()

	def resolve(self, location: LocationSchema) -> ResolvedLocation:
		if location.provider_place_id and not location.provider:
			raise DomainValidationError(
				"provider is required when provider place ID is provided"
			)
		return ResolvedLocation(
			address=location.formatted_address,
			latitude=location.latitude,
			longitude=location.longitude,
			display_name=location.display_name,
			provider=location.provider,
			provider_place_id=location.provider_place_id,
		)
