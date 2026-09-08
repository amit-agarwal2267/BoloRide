from typing import Protocol

from boloride.domain.models.location import LocationCandidate, LocationSearchContext


class MapsProvider(Protocol):
	provider_name: str

	async def search_location(
		self,
		query: str,
		context: LocationSearchContext | None = None,
	) -> list[LocationCandidate]:
		...

	async def aclose(self) -> None: ...
