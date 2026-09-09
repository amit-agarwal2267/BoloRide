from uuid import UUID

from boloride.domain.models.location import ResolvedLocation
from boloride.domain.models.user import normalize_saved_place_label
from boloride.domain.exceptions import DomainValidationError
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

	async def resolve_label(self, user_id: UUID, label: str) -> ResolvedLocation | None:
		"""Resolve only this customer's saved snapshot; never call a maps provider."""
		normalized = normalize_saved_place_label(label)
		aliases = {"home", "ghar"} if normalized in {"home", "ghar"} else {normalized}
		matches = [place for place in await self._places.list_for_user(user_id) if place.label in aliases]
		if len(matches) > 1:
			raise DomainValidationError("saved place label is ambiguous")
		if not matches:
			return None
		place = matches[0]
		return ResolvedLocation(
			address=place.address,
			display_name=place.display_name,
			latitude=place.latitude,
			longitude=place.longitude,
			provider=place.provider,
			provider_place_id=place.provider_place_id,
		)
