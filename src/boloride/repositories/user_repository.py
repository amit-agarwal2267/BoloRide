from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.user import User
from boloride.domain.models.user import (
    normalize_customer_age,
    normalize_customer_name,
    normalize_indian_phone_number,
)


@dataclass(frozen=True, slots=True)
class UserCreationResult:
    user: User
    created: bool


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_phone(self, phone_number: str) -> User | None:
        normalized = normalize_indian_phone_number(phone_number)
        return await self._session.scalar(
            select(User).where(User.phone_number == normalized)
        )

    async def create(self, phone_number: str, name: str, age: int) -> User:
        display_name = " ".join(name.split())
        user = User(
            phone_number=normalize_indian_phone_number(phone_number),
            name=display_name,
            normalized_name=normalize_customer_name(name),
            age=normalize_customer_age(age),
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def create_or_get(
        self, phone_number: str, name: str, age: int
    ) -> UserCreationResult:
        """Create once, recovering safely if another transaction wins the race."""
        normalized_phone = normalize_indian_phone_number(phone_number)
        display_name = " ".join(name.split())
        normalized_name = normalize_customer_name(name)
        normalized_age = normalize_customer_age(age)

        existing = await self._session.scalar(
            select(User).where(User.phone_number == normalized_phone)
        )
        if existing is not None:
            return UserCreationResult(existing, False)

        user = User(
            phone_number=normalized_phone,
            name=display_name,
            normalized_name=normalized_name,
            age=normalized_age,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(user)
                await self._session.flush()
        except IntegrityError:
            existing = await self._session.scalar(
                select(User).where(User.phone_number == normalized_phone)
            )
            if existing is None:
                raise
            return UserCreationResult(existing, False)
        return UserCreationResult(user, True)
