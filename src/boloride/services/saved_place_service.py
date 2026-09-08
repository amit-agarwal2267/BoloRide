from uuid import UUID

from boloride.domain.models.location import ResolvedLocation
from boloride.repositories.saved_place_repository import SavedPlaceRepository


class SavedPlaceService:
	def __init__(self, places: SavedPlaceRepository) -> None:
		self._places = places

	async def save_place(
		self, user_id: UUID, label: str, location: ResolvedLocation
	) -> object:
		return await self._places.create(user_id, label, location)

	async def get_place(self, user_id: UUID, label: str) -> object | None:
		return await self._places.get_by_user_and_label(user_id, label)

	async def list_places(self, user_id: UUID) -> list[object]:
		return await self._places.list_for_user(user_id)
