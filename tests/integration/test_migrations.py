import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from boloride.config import Settings, get_settings


async def create_database(admin_url: str, database_name: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        await engine.dispose()


async def drop_database(admin_url: str, database_name: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await connection.exec_driver_sql(f'DROP DATABASE "{database_name}"')
    finally:
        await engine.dispose()


async def schema_state(database_url: str) -> tuple[str, set[str]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            tables = set(
                await connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            )
            return revision, tables
    finally:
        await engine.dispose()


async def insert_phone_only_prototype_data(database_url: str) -> None:
    engine = create_async_engine(database_url)
    user_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, phone_number) "
                    "VALUES (:id, '+919876543210')"
                ),
                {"id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO saved_places "
                    "(id, user_id, label, address, latitude, longitude) VALUES "
                    "(:id, :user_id, 'home', 'Old home', 25.18, 75.83)"
                ),
                {"id": uuid4(), "user_id": user_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO rides "
                    "(id, user_id, pickup_address, pickup_latitude, pickup_longitude, "
                    "destination_address, destination_latitude, destination_longitude, "
                    "requested_ride_at, status) VALUES "
                    "(:id, :user_id, 'Old home', 25.18, 75.83, "
                    "'Station', 25.22, 75.88, now(), 'requested')"
                ),
                {"id": uuid4(), "user_id": user_id},
            )
    finally:
        await engine.dispose()


async def identity_schema_state(database_url: str) -> tuple[set[str], dict[str, int]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            columns = set(
                await connection.scalars(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'users'"
                    )
                )
            )
            counts = {
                table: int(
                    await connection.scalar(text(f"SELECT count(*) FROM {table}"))
                    or 0
                )
                for table in ("rides", "saved_places", "users")
            }
            return columns, counts
    finally:
        await engine.dispose()


def test_clean_database_upgrade_downgrade_and_reupgrade(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_url = make_url(settings.database_url)
    database_name = f"boloride_test_{uuid4().hex}"
    admin_url = source_url.set(database="postgres").render_as_string(hide_password=False)
    test_url = source_url.set(database=database_name).render_as_string(hide_password=False)
    alembic_config = Config(Path(__file__).resolve().parents[2] / "alembic.ini")

    asyncio.run(create_database(admin_url, database_name))
    monkeypatch.setenv("DATABASE_URL", test_url)
    get_settings.cache_clear()
    try:
        command.upgrade(alembic_config, "head")
        revision, tables = asyncio.run(schema_state(test_url))
        assert revision == "006"
        assert {"users", "saved_places", "rides"}.issubset(tables)

        command.downgrade(alembic_config, "005")
        revision, _ = asyncio.run(schema_state(test_url))
        columns, _ = asyncio.run(identity_schema_state(test_url))
        assert revision == "005"
        assert not {"name", "normalized_name", "age"}.intersection(columns)

        asyncio.run(insert_phone_only_prototype_data(test_url))
        command.upgrade(alembic_config, "head")
        assert asyncio.run(schema_state(test_url))[0] == "006"
        columns, counts = asyncio.run(identity_schema_state(test_url))
        assert {"name", "normalized_name", "age"}.issubset(columns)
        assert counts == {"rides": 0, "saved_places": 0, "users": 0}

        command.downgrade(alembic_config, "001")
        revision, tables = asyncio.run(schema_state(test_url))
        assert revision == "001"
        assert not {"users", "saved_places", "rides"}.intersection(tables)

        command.upgrade(alembic_config, "head")
        assert asyncio.run(schema_state(test_url))[0] == "006"
    finally:
        monkeypatch.setenv("DATABASE_URL", settings.database_url)
        get_settings.cache_clear()
        asyncio.run(drop_database(admin_url, database_name))
