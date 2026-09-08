from boloride.domain.models.location import LocationCandidate, ResolvedLocation
from boloride.schemas.location import LocationSchema
from boloride.services.location_service import LocationService


async def search_locations(
	service: LocationService,
	query: str,
	*,
	city: str | None = None,
	state: str | None = None,
	country: str = "IN",
	session_id: str | None = None,
) -> list[LocationCandidate]:
	return await service.search_locations(
		query,
		city=city,
		state=state,
		country=country,
		session_id=session_id,
	)


def resolve_location(
	service: LocationService, location: LocationSchema
) -> ResolvedLocation:
	return service.resolve(location)
