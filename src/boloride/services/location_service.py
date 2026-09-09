import logging
from time import monotonic

from boloride.domain.exceptions import DomainValidationError, LocationNotFoundError
from boloride.domain.models.location import (
	LocationClarificationReason,
	LocationCandidate,
	LocationResolutionResult,
	LocationResolutionStatus,
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
		urban_radius_meters: int = 1000,
		rural_radius_meters: int = 20000,
	) -> None:
		self._router = router
		self._max_candidates = max_candidates
		self._default_country = default_country
		self._default_language = default_language
		self._urban_radius_meters = urban_radius_meters
		self._rural_radius_meters = rural_radius_meters

	async def resolve_query(
		self,
		query: str,
		*,
		city: str | None = None,
		state: str | None = None,
		country: str | None = None,
		language: str | None = None,
		dense_context: bool = True,
		require_city_context: bool = False,
		session_id: str | None = None,
	) -> LocationResolutionResult:
		normalized_query = " ".join(query.split())
		if not normalized_query:
			raise DomainValidationError("location query cannot be blank")
		logger.info("location_resolution_requested", extra={"event": "location_resolution_requested", "session_id": session_id})
		if require_city_context and city is None and _looks_like_incomplete_address(normalized_query):
			logger.info("location_clarification_required", extra={"event": "location_clarification_required", "session_id": session_id, "reason": "missing_city"})
			return LocationResolutionResult(
				LocationResolutionStatus.CLARIFICATION_REQUIRED,
				clarification_reason=LocationClarificationReason.MISSING_CITY,
			)
		context = LocationSearchContext(
			country=country or self._default_country,
			city=city,
			state=state,
			language=language or self._default_language,
			radius_meters=self._urban_radius_meters if dense_context else self._rural_radius_meters,
		)
		started_at = monotonic()
		candidates, provider, fallback_used, unavailable = await self._router.search_location(normalized_query, context)
		candidates = candidates[:3]
		status = LocationResolutionStatus.PROVIDER_UNAVAILABLE if unavailable else LocationResolutionStatus.NOT_FOUND
		if candidates:
			if len(candidates) == 1:
				resolved = await self.resolve_candidate(candidates[0])
				status = LocationResolutionStatus.RESOLVED
				result = LocationResolutionResult(status, location=resolved, provider=provider, fallback_used=fallback_used)
			else:
				states = {candidate.state.casefold() for candidate in candidates if candidate.state}
				reason = LocationClarificationReason.AMBIGUOUS_STATE if len(states) > 1 else LocationClarificationReason.AMBIGUOUS_CANDIDATES
				status = LocationResolutionStatus.CLARIFICATION_REQUIRED
				result = LocationResolutionResult(status, candidates=tuple(candidates), clarification_reason=reason, provider=provider, fallback_used=fallback_used)
		else:
			result = LocationResolutionResult(status, provider=provider, fallback_used=fallback_used)
		logger.info("location_resolution_completed", extra={"event": "location_resolution_completed", "session_id": session_id, "result": status.value, "provider": provider, "fallback_used": fallback_used, "candidate_count_bucket": str(min(len(candidates), 3)), "duration_ms": round((monotonic()-started_at)*1000, 2)})
		event = {
			LocationResolutionStatus.RESOLVED: "location_resolved",
			LocationResolutionStatus.CLARIFICATION_REQUIRED: "location_clarification_required",
			LocationResolutionStatus.NOT_FOUND: "location_not_found",
			LocationResolutionStatus.PROVIDER_UNAVAILABLE: "location_provider_unavailable",
		}[status]
		logger.info(event, extra={"event": event, "session_id": session_id, "provider": provider, "fallback_used": fallback_used})
		return result

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

	async def resolve_candidate(self, candidate: LocationCandidate) -> ResolvedLocation:
		provider = next((item for item in self._router.get_search_providers() if item.provider_name == candidate.provider), None)
		if provider is None:
			provider = self._router.get_provider()
		enriched = await provider.enrich_candidate(candidate)
		return enriched.to_resolved_location()

	async def get_route(
		self, origin: ResolvedLocation, destination: ResolvedLocation
	):
		return await self._router.get_route(origin, destination)

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


def _looks_like_incomplete_address(query: str) -> bool:
	"""Conservatively identify street/house input lacking geographic context."""
	parts = [part.strip() for part in query.split(",") if part.strip()]
	return len(parts) >= 2 and any(character.isdigit() for character in parts[0])
