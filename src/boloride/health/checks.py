from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def database_is_ready(engine: AsyncEngine) -> None:
    """Raise when PostgreSQL cannot execute a minimal query."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
