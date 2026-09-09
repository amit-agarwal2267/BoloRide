from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.booking_attempt import BookingAttempt
from boloride.domain.models.booking import BookingAttemptState


class BookingAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_quote(self, quote_id: UUID, *, for_update: bool = False) -> BookingAttempt | None:
        statement = select(BookingAttempt).where(BookingAttempt.quote_id == quote_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)
    async def create(self, **values: object) -> BookingAttempt:
        attempt = BookingAttempt(**values)
        self._session.add(attempt)
        await self._session.flush()
        return attempt

    async def claim(self, attempt_id: UUID, expected: BookingAttemptState, started_at: datetime) -> bool:
        result = await self._session.execute(
            update(BookingAttempt)
            .where(BookingAttempt.id == attempt_id, BookingAttempt.state == expected.value)
            .values(state=BookingAttemptState.PROVIDER_CALLING.value, provider_call_started_at=started_at)
        )
        return result.rowcount == 1

    async def get(self, attempt_id: UUID, *, for_update: bool = False) -> BookingAttempt | None:
        statement = select(BookingAttempt).where(BookingAttempt.id == attempt_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)
