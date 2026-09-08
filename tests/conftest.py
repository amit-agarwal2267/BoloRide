from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from boloride.config import Settings
from boloride.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        langfuse_enabled=False,
        llm_primary_model="google-primary-test",
        llm_fallback_1_model="google-fallback-test",
        llm_fallback_2_model="groq-fallback-test",
        google_api_key="test-google-key",
        groq_api_key="test-groq-key",
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[object]:
    application = create_app(settings)
    yield application
    await application.state.db_engine.dispose()


@pytest.fixture
async def client(app: object) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as test_client:
        yield test_client


@pytest.fixture
async def db_session(app: object) -> AsyncIterator[AsyncSession]:
    async with app.state.db_session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
