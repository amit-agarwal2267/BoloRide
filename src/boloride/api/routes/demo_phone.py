from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.api.dependencies import (
    AuthenticatedDemoUser,
    get_current_demo_user,
    get_db_session,
)
from boloride.repositories.demo_phone_repository import DemoPhoneRepository
from boloride.schemas.demo_phone import (
    DemoPhoneCallEndRequest,
    DemoPhoneCallStartResponse,
    DemoPhonePublicResponse,
)
from boloride.services.demo_phone_service import (
    DemoPhoneAllocationError,
    DemoPhoneInUseError,
    DemoPhoneService,
)


router = APIRouter(prefix="/api/demo/phone", tags=["demo-phone"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentDemoUser = Annotated[AuthenticatedDemoUser, Depends(get_current_demo_user)]


def _service(session: AsyncSession) -> DemoPhoneService:
    return DemoPhoneService(session, DemoPhoneRepository(session))


@router.get("", response_model=DemoPhonePublicResponse)
async def get_demo_phone(
    session: DatabaseSession,
    user: CurrentDemoUser,
) -> DemoPhonePublicResponse:
    try:
        result = await _service(session).get_or_allocate(user.id)
        await session.commit()
    except DemoPhoneAllocationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return DemoPhonePublicResponse(
        masked_number=result.masked_number,
        in_use=result.in_use,
    )


@router.post("/roll", response_model=DemoPhonePublicResponse)
async def roll_demo_phone(
    session: DatabaseSession,
    user: CurrentDemoUser,
) -> DemoPhonePublicResponse:
    try:
        result = await _service(session).roll(user.id)
        await session.commit()
    except DemoPhoneInUseError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except DemoPhoneAllocationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return DemoPhonePublicResponse(
        masked_number=result.masked_number,
        in_use=result.in_use,
    )


@router.post("/call/start", response_model=DemoPhoneCallStartResponse)
async def start_demo_call(
    session: DatabaseSession,
    user: CurrentDemoUser,
) -> DemoPhoneCallStartResponse:
    try:
        result = await _service(session).start_call(user.id)
        await session.commit()
    except DemoPhoneInUseError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except DemoPhoneAllocationError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return DemoPhoneCallStartResponse(
        phone_number=result.phone_number,
        masked_number=result.masked_number,
        call_id=result.call_id,
        expires_at=result.expires_at,
    )


@router.post("/call/end", response_model=DemoPhonePublicResponse)
async def end_demo_call(
    payload: DemoPhoneCallEndRequest,
    session: DatabaseSession,
    user: CurrentDemoUser,
) -> DemoPhonePublicResponse:
    result = await _service(session).end_call(user.id, payload.call_id)
    await session.commit()
    return DemoPhonePublicResponse(
        masked_number=result.masked_number,
        in_use=result.in_use,
    )
