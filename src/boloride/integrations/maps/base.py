from typing import Protocol

from boloride.domain.models.location import (
	LocationCandidate,
	LocationSearchContext,
	ResolvedLocation,
	RouteResult,
)


class MapsProvider(Protocol):
	provider_name: str

	async def search_location(
		self,
		query: str,
		context: LocationSearchContext | None = None,
	) -> list[LocationCandidate]:
		...

	async def enrich_candidate(self, candidate: LocationCandidate) -> LocationCandidate:
		...

	async def get_route(
		self, origin: ResolvedLocation, destination: ResolvedLocation
	) -> RouteResult:
		...

	async def aclose(self) -> None: ...
