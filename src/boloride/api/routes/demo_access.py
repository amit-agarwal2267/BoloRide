from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.api.dependencies import (
    AuthenticatedDemoUser,
    get_current_demo_user,
    get_db_session,
)
from boloride.repositories.demo_access_repository import (
    DemoAccessRepository,
)
from boloride.schemas.demo_access import (
    DemoAccessResponse,
)
from boloride.services.demo_access_service import (
    DemoAccessResult,
    DemoAccessService,
)


router = APIRouter(
    prefix="/api/demo/access",
    tags=["demo-access"],
)


DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_db_session),
]

CurrentDemoUser = Annotated[
    AuthenticatedDemoUser,
    Depends(get_current_demo_user),
]


def _to_response(
    result: DemoAccessResult,
) -> DemoAccessResponse:
    return DemoAccessResponse(
        status=result.status,
        position=result.position,
        granted_at=result.granted_at,
    )


@router.get(
    "",
    response_model=DemoAccessResponse,
)
async def get_demo_access(
    session: DatabaseSession,
    user: CurrentDemoUser,
) -> DemoAccessResponse:
    repository = DemoAccessRepository(session)
    service = DemoAccessService(repository)

    result = await service.get_access(
        auth_user_id=user.id,
    )

    return _to_response(result)


@router.post(
    "/request",
    response_model=DemoAccessResponse,
    status_code=status.HTTP_200_OK,
)
async def request_demo_access(
    session: DatabaseSession,
    user: CurrentDemoUser,
) -> DemoAccessResponse:
    repository = DemoAccessRepository(session)
    service = DemoAccessService(repository)

    result = await service.request_access(
        auth_user_id=user.id,
        email=user.email,
    )

    await session.commit()

    return _to_response(result)