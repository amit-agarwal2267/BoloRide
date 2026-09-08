from uuid import UUID

from boloride.domain.models.location import ResolvedLocation
from boloride.services.saved_place_service import SavedPlaceService


async def save_place(
	service: SavedPlaceService,
	user_id: UUID,
	label: str,
	location: ResolvedLocation,
) -> object:
	return await service.save_place(user_id, label, location)


async def get_saved_place(
	service: SavedPlaceService, user_id: UUID, label: str
) -> object | None:
	return await service.get_place(user_id, label)


async def get_saved_places(
	service: SavedPlaceService, user_id: UUID
) -> list[object]:
	return await service.list_places(user_id)
