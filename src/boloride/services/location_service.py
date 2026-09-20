import logging
import re
from math import asin, cos, radians, sin, sqrt
from time import monotonic

from boloride.domain.exceptions import (
	DomainValidationError,
	LocationNotFoundError,
	RouteProviderError,
	RouteSanityError,
)
from boloride.domain.models.location import (
	assess_route_sanity,
	customer_location_label,
	deduplicate_location_candidates,
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

	def is_fallback_provider(self, provider_name: str) -> bool:
		return self._router.is_fallback_provider(provider_name)

	async def resolve_query(
		self,
		query: str,
		*,
		city: str | None = None,
		state: str | None = None,
		country: str | None = None,
		language: str | None = None,
		dense_context: bool = True,
		session_id: str | None = None,
		location_role: str | None = None,
		context_source: str | None = None,
		explicit_geography_present: bool = False,
		context_conflict_detected: bool = False,
	) -> LocationResolutionResult:
		normalized_query = " ".join(query.split())
		if not normalized_query:
			raise DomainValidationError("location query cannot be blank")
		logger.info(
			"location_context_derived",
			extra={
				"event": "location_context_derived",
				"session_id": session_id,
				"location_role": location_role,
				"explicit_geography_present": explicit_geography_present,
				"context_source": context_source,
				"context_city": city,
				"context_state": state,
				"context_conflict_detected": context_conflict_detected,
			},
		)
		logger.info("location_resolution_requested", extra={"event": "location_resolution_requested", "session_id": session_id})
		context = LocationSearchContext(
			country=country or self._default_country,
			city=city,
			state=state,
			language=language or self._default_language,
			radius_meters=self._urban_radius_meters if dense_context else self._rural_radius_meters,
		)
		if city is None and state is None:
			logger.info(
				"location_unbiased_search_started",
				extra={
					"event": "location_unbiased_search_started",
					"session_id": session_id,
					"location_role": location_role,
				},
			)
		started_at = monotonic()
		candidates, provider, fallback_used, unavailable = await self._router.search_location(normalized_query, context)
		original_count = len(candidates)
		provider_names = {candidate.provider for candidate in candidates}
		consensus = _consensus_candidate(
			candidates,
			normalized_query,
			city=city,
			state=state,
		) if len(provider_names) >= 2 else None
		candidates = _rank_location_candidates(
			deduplicate_location_candidates(candidates),
			normalized_query,
			city=city,
			state=state,
		)[:3]
		if len(candidates) < original_count:
			logger.info(
				"location_candidates_deduplicated",
				extra={
					"event": "location_candidates_deduplicated",
					"session_id": session_id,
					"provider": provider,
					"removed_count": original_count - len(candidates),
				},
			)
		status = LocationResolutionStatus.PROVIDER_UNAVAILABLE if unavailable else LocationResolutionStatus.NOT_FOUND
		if candidates:
			if consensus is not None:
				resolved = await self.resolve_candidate(consensus)
				status = LocationResolutionStatus.RESOLVED
				result = LocationResolutionResult(
					status,
					location=resolved,
					provider="consensus",
					fallback_used=False,
				)
				logger.info(
					"location_provider_consensus_resolved",
					extra={
						"event": "location_provider_consensus_resolved",
						"session_id": session_id,
						"location_role": location_role,
						"providers": sorted(provider_names),
					},
				)
			elif city is None and state is None:
				status = LocationResolutionStatus.LIKELY_MATCH_CONFIRMATION_REQUIRED
				result = LocationResolutionResult(
					status,
					candidates=(candidates[0],),
					provider=provider,
					fallback_used=fallback_used,
				)
				logger.info(
					"location_likely_candidate_proposed",
					extra={
						"event": "location_likely_candidate_proposed",
						"session_id": session_id,
						"location_role": location_role,
						"provider": provider,
					},
				)
			elif len(candidates) == 1:
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
		if fallback_used:
			logger.info(
				"location_provider_fallback_context_preserved",
				extra={
					"event": "location_provider_fallback_context_preserved",
					"session_id": session_id,
					"location_role": location_role,
					"context_source": context_source,
					"provider": provider,
				},
			)
		logger.info("location_resolution_completed", extra={"event": "location_resolution_completed", "session_id": session_id, "result": status.value, "provider": provider, "fallback_used": fallback_used, "candidate_count_bucket": str(min(len(candidates), 3)), "duration_ms": round((monotonic()-started_at)*1000, 2)})
		event = {
			LocationResolutionStatus.RESOLVED: "location_resolved",
			LocationResolutionStatus.LIKELY_MATCH_CONFIRMATION_REQUIRED: "location_candidate_confirmation_required",
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
		self,
		origin: ResolvedLocation,
		destination: ResolvedLocation,
		*,
		session_id: str | None = None,
	):
		provider_failures = 0
		sanity_failures: list[str] = []
		for index, provider in enumerate(self._router.get_route_providers()):
			if index == 1:
				self._router.record_fallback_attempt()
			with self._router.provider_observation(provider.provider_name, "route", index + 1) as observation:
				started_at = monotonic()
				try:
					route = await provider.get_route(origin, destination)
				except RouteProviderError:
					provider_failures += 1
					if observation is not None:
						observation.update(metadata={"provider": provider.provider_name, "operation": "route", "attempt_order": index + 1, "success": False, "failure_category": "provider_unavailable", "duration_ms": (monotonic() - started_at) * 1000})
					continue
				if observation is not None:
					observation.update(metadata={"provider": provider.provider_name, "operation": "route", "attempt_order": index + 1, "success": True, "duration_ms": (monotonic() - started_at) * 1000, "route_duration_seconds": route.duration_seconds, "route_distance_meters": route.distance_meters})
			sanity = assess_route_sanity(origin, destination, route)
			fields = {
				"session_id": session_id,
				"provider": route.provider,
				"fallback_used": index > 0,
				"route_distance_km": round(route.distance_meters / 1000, 2),
				"route_duration_seconds": route.duration_seconds,
				"pickup_city": origin.city,
				"pickup_state": origin.state,
				"destination_city": destination.city,
				"destination_state": destination.state,
				"route_sanity_reason": sanity.reason,
			}
			if sanity.status.value == "passed":
				logger.info(
					"route_sanity_passed",
					extra={"event": "route_sanity_passed", **fields},
				)
				return route
			sanity_failures.append(sanity.reason)
			logger.warning(
				"route_sanity_failed",
				extra={"event": "route_sanity_failed", **fields},
			)
		if sanity_failures:
			raise RouteSanityError(
				"route and endpoint geography are inconsistent; location clarification is required"
			)
		raise RouteProviderError(
			f"route resolution failed across {provider_failures} configured providers"
		)

	@staticmethod
	def customer_candidate_label(candidate: LocationCandidate) -> str:
		return customer_location_label(candidate)

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


_LOCATION_TOKEN_STOPWORDS = frozenset({
	"the", "near", "at", "in", "to", "from", "road", "rd", "india", "ind",
})


def _location_tokens(value: str) -> set[str]:
	return {
		token
		for token in re.findall(r"[\w]+", value.casefold())
		if len(token) > 1 and token not in _LOCATION_TOKEN_STOPWORDS
	}


def _candidate_query_coverage(candidate: LocationCandidate, query: str) -> float:
	query_tokens = _location_tokens(query)
	if not query_tokens:
		return 0.0
	candidate_tokens = _location_tokens(
		f"{candidate.display_name} {candidate.formatted_address}"
	)
	return len(query_tokens & candidate_tokens) / len(query_tokens)


def _candidate_text_similarity(left: LocationCandidate, right: LocationCandidate) -> float:
	left_tokens = _location_tokens(f"{left.display_name} {left.formatted_address}")
	right_tokens = _location_tokens(f"{right.display_name} {right.formatted_address}")
	union = left_tokens | right_tokens
	return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _candidate_distance(left: LocationCandidate, right: LocationCandidate) -> float:
	lat1, lat2 = radians(float(left.latitude)), radians(float(right.latitude))
	dlat = lat2 - lat1
	dlon = radians(float(right.longitude - left.longitude))
	value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
	return 6_371_000 * 2 * asin(sqrt(min(1.0, value)))


def _known_geography_agrees(
	left: LocationCandidate,
	right: LocationCandidate,
) -> bool:
	for field in ("city", "state", "country"):
		left_value = getattr(left, field)
		right_value = getattr(right, field)
		if left_value and right_value and left_value.casefold() != right_value.casefold():
			return False
	return True


def _consensus_candidate(
	candidates: list[LocationCandidate],
	query: str,
	*,
	city: str | None,
	state: str | None,
) -> LocationCandidate | None:
	"""Resolve automatically only when independent providers agree on the same relevant place."""
	for index, left in enumerate(candidates):
		if _candidate_query_coverage(left, query) < 0.5:
			continue
		if city and left.city and left.city.casefold() != city.casefold():
			continue
		if state and left.state and left.state.casefold() != state.casefold():
			continue
		for right in candidates[index + 1:]:
			if left.provider == right.provider:
				continue
			if _candidate_query_coverage(right, query) < 0.5:
				continue
			if not _known_geography_agrees(left, right):
				continue
			if city and right.city and right.city.casefold() != city.casefold():
				continue
			if state and right.state and right.state.casefold() != state.casefold():
				continue
			if (
				_candidate_distance(left, right) <= 250
				or _candidate_text_similarity(left, right) >= 0.5
			):
				return max(
					(left, right),
					key=lambda item: (
						_candidate_query_coverage(item, query),
						item.provider == "google",
					),
				)
	return None


def _rank_location_candidates(
	candidates: list[LocationCandidate],
	query: str,
	*,
	city: str | None,
	state: str | None,
) -> list[LocationCandidate]:
	def score(candidate: LocationCandidate) -> tuple[float, int, int]:
		geography = int(bool(city and candidate.city and city.casefold() == candidate.city.casefold()))
		geography += int(bool(state and candidate.state and state.casefold() == candidate.state.casefold()))
		return (
			_candidate_query_coverage(candidate, query),
			geography,
			int(candidate.provider == "google"),
		)
	return sorted(candidates, key=score, reverse=True)
