from collections.abc import AsyncIterator

import httpx
import pytest

from boloride.config import Settings
from boloride.main import create_app


@pytest.mark.asyncio
async def test_liveness(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_request_id_is_preserved(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/health/live", headers={"X-Request-ID": "test-request-123"}
    )

    assert response.headers["X-Request-ID"] == "test-request-123"


@pytest.mark.asyncio
async def test_readiness_with_postgres(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_readiness_when_postgres_is_unavailable() -> None:
    unavailable_settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://boloride:unused@127.0.0.1:1/boloride",
        database_connect_timeout_seconds=0.1,
    )
    application = create_app(unavailable_settings)
    transport = httpx.ASGITransport(app=application)

    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as test_client:
            response = await test_client.get("/health/ready")
    finally:
        await application.state.db_engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
