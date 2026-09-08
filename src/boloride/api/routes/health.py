import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from boloride.health.checks import database_is_ready

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=None)
async def ready(request: Request) -> JSONResponse:
    try:
        await database_is_ready(request.app.state.db_engine)
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning(
            "database_readiness_failed",
            extra={
                "event": "database_readiness_failed",
                "error_type": type(exc).__name__,
            },
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready"},
        )

    return JSONResponse(content={"status": "ready"})
