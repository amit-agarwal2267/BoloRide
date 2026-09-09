import asyncio

from boloride.config import get_settings
from boloride.db.session import create_database_engine, create_session_factory
from boloride.observability.logger import configure_logging
from boloride.repositories.fleet_repository import FleetRepository
from boloride.services.fleet_seed_service import FleetSeedService


async def seed() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_database_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            await FleetSeedService(session, FleetRepository(session)).seed_demo_fleet()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
