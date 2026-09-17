from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.db.models.demo_access_request import (
    DemoAccessRequest,
)


@dataclass(frozen=True, slots=True)
class DemoAccessCreationResult:
    request: DemoAccessRequest
    created: bool


class DemoAccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_auth_user_id(
        self,
        auth_user_id: UUID,
    ) -> DemoAccessRequest | None:
        return await self._session.scalar(
            select(DemoAccessRequest).where(
                DemoAccessRequest.auth_user_id == auth_user_id
            )
        )

    async def create_or_get(
        self,
        auth_user_id: UUID,
        email: str,
    ) -> DemoAccessCreationResult:
        normalized_email = email.strip().lower()

        existing = await self.get_by_auth_user_id(auth_user_id)

        if existing is not None:
            if existing.email != normalized_email:
                existing.email = normalized_email
                await self._session.flush()

            return DemoAccessCreationResult(
                request=existing,
                created=False,
            )

        request = DemoAccessRequest(
            auth_user_id=auth_user_id,
            email=normalized_email,
        )

        try:
            async with self._session.begin_nested():
                self._session.add(request)
                await self._session.flush()
        except IntegrityError:
            existing = await self.get_by_auth_user_id(auth_user_id)

            if existing is None:
                raise

            return DemoAccessCreationResult(
                request=existing,
                created=False,
            )

        return DemoAccessCreationResult(
            request=request,
            created=True,
        )

    async def get_waitlist_position(
        self,
        request: DemoAccessRequest,
    ) -> int | None:
        if request.access_granted:
            return None

        position = await self._session.scalar(
            select(func.count())
            .select_from(DemoAccessRequest)
            .where(
                DemoAccessRequest.access_granted.is_(False),
                or_(
                    DemoAccessRequest.requested_at
                    < request.requested_at,
                    and_(
                        DemoAccessRequest.requested_at
                        == request.requested_at,
                        DemoAccessRequest.auth_user_id
                        <= request.auth_user_id,
                    ),
                ),
            )
        )

        return int(position or 0)