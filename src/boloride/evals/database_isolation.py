from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

_DISPOSABLE_DATABASE = re.compile(
    r"^boloride_eval_(?:c[3-6]_a[123]|isolation_[0-9a-f]{32})$"
)


def disposable_database_urls(source_url: str, database_name: str) -> tuple[str, str]:
    _validate_disposable_name(database_name)
    source = make_url(source_url)
    if source.get_backend_name() != "postgresql":
        raise ValueError("evaluation isolation requires PostgreSQL")
    admin = source.set(database="postgres")
    target = source.set(database=database_name)
    return _render(admin), _render(target)


async def create_disposable_database(admin_url: str, database_name: str) -> None:
    _validate_disposable_name(database_name)
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            )
            if exists:
                raise ValueError(
                    f"disposable evaluation database already exists: {database_name}"
                )
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    finally:
        await engine.dispose()


async def drop_disposable_database(admin_url: str, database_name: str) -> None:
    _validate_disposable_name(database_name)
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database_name},
            )
            await connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}"'
            )
    finally:
        await engine.dispose()


def _validate_disposable_name(database_name: str) -> None:
    if not _DISPOSABLE_DATABASE.fullmatch(database_name):
        raise ValueError("refusing non-disposable evaluation database name")


def _render(url: URL) -> str:
    return url.render_as_string(hide_password=False)
