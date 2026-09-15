import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from boloride.config import Settings, get_settings
from boloride.db.models.ride import Ride
from boloride.db.models.user import User
from boloride.evals.database_isolation import (
    create_disposable_database,
    disposable_database_urls,
    drop_disposable_database,
)


async def _commit_marker_ride(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            customer_id = uuid4()
            await connection.execute(
                User.__table__.insert().values(
                    id=customer_id,
                    phone_number="+919999999906",
                    name="Isolation Customer",
                    normalized_name="isolation customer",
                    age=30,
                )
            )
            await connection.execute(
                Ride.__table__.insert().values(
                    id=uuid4(),
                    user_id=customer_id,
                    pickup_address="Fixture Pickup",
                    pickup_latitude="25.1",
                    pickup_longitude="75.1",
                    destination_address="Fixture Destination",
                    destination_latitude="25.2",
                    destination_longitude="75.2",
                    requested_ride_at=datetime(2026, 9, 12, 12, 30, tzinfo=UTC),
                    status="booked",
                    confirmed_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
                    provider="fixture",
                    provider_booking_id="isolation-booking",
                    booked_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
                    fare_amount=Decimal("160.00"),
                    fare_currency="INR",
                )
            )
    finally:
        await engine.dispose()


async def _ride_count(database_url: str) -> int:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return int(await connection.scalar(select(func.count()).select_from(Ride)))
    finally:
        await engine.dispose()


def test_fresh_disposable_database_does_not_inherit_committed_booking(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    alembic_config = Config(Path(__file__).resolve().parents[2] / "alembic.ini")
    names = tuple(f"boloride_eval_isolation_{uuid4().hex}" for _ in range(2))
    databases = [disposable_database_urls(settings.database_url, name) for name in names]
    original_database_url = settings.database_url
    try:
        for index, ((admin_url, database_url), name) in enumerate(zip(databases, names)):
            asyncio.run(create_disposable_database(admin_url, name))
            monkeypatch.setenv("DATABASE_URL", database_url)
            get_settings.cache_clear()
            command.upgrade(alembic_config, "head")
            assert asyncio.run(_ride_count(database_url)) == 0
            if index == 0:
                asyncio.run(_commit_marker_ride(database_url))
                assert asyncio.run(_ride_count(database_url)) == 1
                asyncio.run(drop_disposable_database(admin_url, name))
    finally:
        monkeypatch.setenv("DATABASE_URL", original_database_url)
        get_settings.cache_clear()
        for (admin_url, _), name in zip(databases, names):
            asyncio.run(drop_disposable_database(admin_url, name))
