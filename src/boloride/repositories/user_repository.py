from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.user import User
from boloride.domain.models.user import normalize_indian_phone_number


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_phone(self, phone_number: str) -> User | None:
        normalized = normalize_indian_phone_number(phone_number)
        return await self._session.scalar(
            select(User).where(User.phone_number == normalized)
        )

    async def create(self, phone_number: str) -> User:
        user = User(phone_number=normalize_indian_phone_number(phone_number))
        self._session.add(user)
        await self._session.flush()
        return user
