from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)
from starlette.concurrency import run_in_threadpool
from supabase import Client, create_client
from supabase.client import ClientOptions
from supabase_auth.errors import AuthError

from boloride.config import Settings, get_settings


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthenticatedDemoUser:
    id: UUID
    email: str


@lru_cache(maxsize=4)
def _create_supabase_client(
    supabase_url: str,
    publishable_key: str,
) -> Client:
    return create_client(
        supabase_url,
        publishable_key,
        options=ClientOptions(
            auto_refresh_token=False,
            persist_session=False,
        ),
    )


async def get_db_session(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    session_factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.db_session_factory,
    )

    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def _is_authenticated_audience(audience: object) -> bool:
    if isinstance(audience, str):
        return audience == "authenticated"

    if isinstance(audience, list):
        return "authenticated" in audience

    return False


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_demo_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedDemoUser:
    if credentials is None:
        raise _unauthorized()

    if (
        settings.supabase_url is None
        or settings.supabase_publishable_key is None
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo authentication is not configured.",
        )

    supabase = _create_supabase_client(
        settings.supabase_url,
        settings.supabase_publishable_key.get_secret_value(),
    )

    try:
        claims_response = await run_in_threadpool(
            supabase.auth.get_claims,
            credentials.credentials,
        )
    except AuthError:
        raise _unauthorized() from None

    if claims_response is None:
        raise _unauthorized()

    claims = claims_response["claims"]

    expected_issuer = (
        f"{settings.supabase_url.rstrip('/')}/auth/v1"
    )

    if claims.get("iss") != expected_issuer:
        raise _unauthorized()

    if claims.get("role") != "authenticated":
        raise _unauthorized()

    if not _is_authenticated_audience(claims.get("aud")):
        raise _unauthorized()

    if claims.get("is_anonymous") is True:
        raise _unauthorized()

    subject = claims.get("sub")

    if not isinstance(subject, str):
        raise _unauthorized()

    try:
        user_id = UUID(subject)
    except ValueError:
        raise _unauthorized() from None

    email = claims.get("email")

    if not isinstance(email, str) or not email.strip():
        raise _unauthorized()

    return AuthenticatedDemoUser(
        id=user_id,
        email=email.strip().lower(),
    )