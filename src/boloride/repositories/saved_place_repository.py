from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.saved_place import SavedPlace
from boloride.domain.models.location import ResolvedLocation
from boloride.domain.models.user import normalize_saved_place_label


class SavedPlaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user_and_label(
        self, user_id: UUID, label: str
    ) -> SavedPlace | None:
        normalized = normalize_saved_place_label(label)
        return await self._session.scalar(
            select(SavedPlace).where(
                SavedPlace.user_id == user_id,
                SavedPlace.label == normalized,
            )
        )

    async def list_for_user(self, user_id: UUID) -> list[SavedPlace]:
        result = await self._session.scalars(
            select(SavedPlace)
            .where(SavedPlace.user_id == user_id)
            .order_by(SavedPlace.label)
        )
        return list(result)

    async def create(
        self, user_id: UUID, label: str, location: ResolvedLocation
    ) -> SavedPlace:
        saved_place = SavedPlace(
            user_id=user_id,
            label=normalize_saved_place_label(label),
            address=location.address,
            display_name=location.display_name,
            latitude=location.latitude,
            longitude=location.longitude,
            provider=location.provider,
            provider_place_id=location.provider_place_id,
        )
        self._session.add(saved_place)
        await self._session.flush()
        return saved_place
