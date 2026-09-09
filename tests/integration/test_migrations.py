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


async def insert_complete_customer_and_ride(
    database_url: str, status: str
) -> tuple[object, object]:
    engine = create_async_engine(database_url)
    user_id = uuid4()
    ride_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, phone_number, name, normalized_name, age) VALUES "
                    "(:id, '+919876543211', 'Migration User', 'migration user', 30)"
                ),
                {"id": user_id},
            )
            booking_fields = (
                ", confirmed_at, provider, provider_booking_id, booked_at, "
                "fare_amount, fare_currency"
                if status not in {"requested", "confirmed"}
                else ""
            )
            booking_values = (
                ", now(), 'mock', 'migration-booking', now(), 100, 'INR'"
                if booking_fields
                else ""
            )
            await connection.execute(
                text(
                    "INSERT INTO rides "
                    "(id, user_id, pickup_address, pickup_latitude, pickup_longitude, "
                    "destination_address, destination_latitude, destination_longitude, "
                    f"requested_ride_at, status{booking_fields}) VALUES "
                    "(:id, :user_id, 'Home', 25.18, 75.83, "
                    "'Station', 25.22, 75.88, now(), :status"
                    f"{booking_values})"
                ),
                {"id": ride_id, "user_id": user_id, "status": status},
            )
        return user_id, ride_id
    finally:
        await engine.dispose()


async def ride_status(database_url: str, ride_id: object) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.scalar(
                text("SELECT status FROM rides WHERE id = :ride_id"),
                {"ride_id": ride_id},
            )
    finally:
        await engine.dispose()


async def delete_ride(database_url: str, ride_id: object) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM rides WHERE id = :ride_id"), {"ride_id": ride_id}
            )
    finally:
        await engine.dispose()


async def set_ride_status(database_url: str, ride_id: object, status: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE rides SET status = :status WHERE id = :ride_id"),
                {"ride_id": ride_id, "status": status},
            )
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
        assert revision == "014"
        assert {"users", "saved_places", "rides", "vehicle_types", "pricing_rules", "accepted_quotes", "offers", "offer_redemptions", "booking_attempts", "drivers", "vehicles", "ride_assignments"}.issubset(tables)

        command.downgrade(alembic_config, "013")
        revision, tables = asyncio.run(schema_state(test_url))
        assert revision == "013"
        assert "ride_assignments" not in tables
        command.upgrade(alembic_config, "014")
        assert asyncio.run(schema_state(test_url))[0] == "014"

        command.downgrade(alembic_config, "012")
        revision, tables = asyncio.run(schema_state(test_url))
        assert revision == "012"
        assert not {"drivers", "vehicles"}.intersection(tables)
        command.upgrade(alembic_config, "013")
        assert asyncio.run(schema_state(test_url))[0] == "013"

        command.downgrade(alembic_config, "011")
        assert asyncio.run(schema_state(test_url))[0] == "011"
        command.upgrade(alembic_config, "012")
        assert asyncio.run(schema_state(test_url))[0] == "012"

        command.downgrade(alembic_config, "010")
        revision, tables = asyncio.run(schema_state(test_url))
        assert revision == "010"
        assert "booking_attempts" not in tables
        command.upgrade(alembic_config, "011")
        assert asyncio.run(schema_state(test_url))[0] == "011"

        command.downgrade(alembic_config, "009")
        revision, tables = asyncio.run(schema_state(test_url))
        assert revision == "009"
        assert not {"offers", "offer_redemptions"}.intersection(tables)
        command.upgrade(alembic_config, "010")
        assert asyncio.run(schema_state(test_url))[0] == "010"

        command.downgrade(alembic_config, "008")
        revision, tables = asyncio.run(schema_state(test_url))
        assert revision == "008"
        assert not {"pricing_rules", "accepted_quotes"}.intersection(tables)
        command.upgrade(alembic_config, "head")
        assert asyncio.run(schema_state(test_url))[0] == "014"

        command.downgrade(alembic_config, "007")
        revision, tables = asyncio.run(schema_state(test_url))
        assert revision == "007"
        assert "vehicle_types" not in tables
        command.upgrade(alembic_config, "head")
        assert asyncio.run(schema_state(test_url))[0] == "014"

        command.downgrade(alembic_config, "006")
        assert asyncio.run(schema_state(test_url))[0] == "006"
        _, booked_ride_id = asyncio.run(
            insert_complete_customer_and_ride(test_url, "booked")
        )
        command.upgrade(alembic_config, "head")
        assert asyncio.run(schema_state(test_url))[0] == "014"
        assert asyncio.run(ride_status(test_url, booked_ride_id)) == "booked"

        command.downgrade(alembic_config, "005")
        revision, _ = asyncio.run(schema_state(test_url))
        columns, _ = asyncio.run(identity_schema_state(test_url))
        assert revision == "005"
        assert not {"name", "normalized_name", "age"}.intersection(columns)

        asyncio.run(insert_phone_only_prototype_data(test_url))
        command.upgrade(alembic_config, "head")
        assert asyncio.run(schema_state(test_url))[0] == "014"
        columns, counts = asyncio.run(identity_schema_state(test_url))
        assert {"name", "normalized_name", "age"}.issubset(columns)
        assert counts == {"rides": 0, "saved_places": 0, "users": 0}

        command.downgrade(alembic_config, "001")
        revision, tables = asyncio.run(schema_state(test_url))
        assert revision == "001"
        assert not {"users", "saved_places", "rides"}.intersection(tables)

        command.upgrade(alembic_config, "head")
        assert asyncio.run(schema_state(test_url))[0] == "014"
    finally:
        monkeypatch.setenv("DATABASE_URL", settings.database_url)
        get_settings.cache_clear()
        asyncio.run(drop_database(admin_url, database_name))


def test_lifecycle_upgrade_fails_without_altering_legacy_rides(
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
        command.upgrade(alembic_config, "006")
        _, ride_id = asyncio.run(insert_complete_customer_and_ride(test_url, "requested"))

        with pytest.raises(Exception, match="cannot reinterpret requested or confirmed"):
            command.upgrade(alembic_config, "head")

        assert asyncio.run(schema_state(test_url))[0] == "006"
        assert asyncio.run(ride_status(test_url, ride_id)) == "requested"

        asyncio.run(delete_ride(test_url, ride_id))
        command.upgrade(alembic_config, "head")
        assert asyncio.run(schema_state(test_url))[0] == "014"
    finally:
        monkeypatch.setenv("DATABASE_URL", settings.database_url)
        get_settings.cache_clear()
        asyncio.run(drop_database(admin_url, database_name))


def test_lifecycle_downgrade_fails_without_altering_new_states(
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
        command.downgrade(alembic_config, "007")
        _, ride_id = asyncio.run(insert_complete_customer_and_ride(test_url, "assigned"))

        with pytest.raises(Exception, match="cannot reinterpret durable ride states"):
            command.downgrade(alembic_config, "006")

        assert asyncio.run(schema_state(test_url))[0] == "007"
        assert asyncio.run(ride_status(test_url, ride_id)) == "assigned"

        asyncio.run(set_ride_status(test_url, ride_id, "booked"))
        command.downgrade(alembic_config, "006")
        assert asyncio.run(schema_state(test_url))[0] == "006"
        assert asyncio.run(ride_status(test_url, ride_id)) == "booked"
    finally:
        monkeypatch.setenv("DATABASE_URL", settings.database_url)
        get_settings.cache_clear()
        asyncio.run(drop_database(admin_url, database_name))
