from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from boloride.db.models.demo_access_request import (
    DemoAccessRequest,
)
from boloride.repositories.demo_access_repository import (
    DemoAccessRepository,
)


DemoAccessStatus = Literal[
    "not_requested",
    "waitlisted",
    "approved",
]


@dataclass(frozen=True, slots=True)
class DemoAccessResult:
    status: DemoAccessStatus
    position: int | None = None
    granted_at: datetime | None = None


class DemoAccessService:
    def __init__(
        self,
        repository: DemoAccessRepository,
    ) -> None:
        self._repository = repository

    async def get_access(
        self,
        auth_user_id: UUID,
    ) -> DemoAccessResult:
        request = await self._repository.get_by_auth_user_id(
            auth_user_id
        )

        if request is None:
            return DemoAccessResult(
                status="not_requested",
            )

        return await self._result_for_request(request)

    async def request_access(
        self,
        auth_user_id: UUID,
        email: str,
    ) -> DemoAccessResult:
        creation = await self._repository.create_or_get(
            auth_user_id=auth_user_id,
            email=email,
        )

        return await self._result_for_request(
            creation.request
        )

    async def _result_for_request(
        self,
        request: DemoAccessRequest,
    ) -> DemoAccessResult:
        if request.access_granted:
            return DemoAccessResult(
                status="approved",
                granted_at=request.granted_at,
            )

        position = await self._repository.get_waitlist_position(
            request
        )

        return DemoAccessResult(
            status="waitlisted",
            position=position,
        )