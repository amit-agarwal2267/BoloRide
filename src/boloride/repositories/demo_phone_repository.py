from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.demo_phone_lease import DemoPhoneLease
from boloride.db.models.user import User


class DemoPhoneRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, auth_user_id: UUID, *, for_update: bool = False
    ) -> DemoPhoneLease | None:
        statement = select(DemoPhoneLease).where(
            DemoPhoneLease.auth_user_id == auth_user_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def phone_available(self, phone_number: str) -> bool:
        lease_owner = await self._session.scalar(select(DemoPhoneLease.auth_user_id).where(DemoPhoneLease.phone_number == phone_number))
        customer = await self._session.scalar(select(User.id).where(User.phone_number == phone_number))
        return lease_owner is None and customer is None

    async def create(
        self, auth_user_id: UUID, phone_number: str
    ) -> DemoPhoneLease:
        lease = DemoPhoneLease(
            auth_user_id=auth_user_id,
            phone_number=phone_number,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(lease)
                await self._session.flush()
        except IntegrityError:
            raise
        return lease
