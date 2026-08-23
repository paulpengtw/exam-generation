from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

pgserver = pytest.importorskip("pgserver")
pytest.importorskip("asyncpg")
pytest.importorskip("aiosqlite")
pytest.importorskip("sqlalchemy")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from server import db  # noqa: E402


@pytest.fixture
def postgres_server(tmp_path: Path) -> Iterator[pgserver.PostgresServer]:
    try:
        server = pgserver.get_server(tmp_path / "pgdata", cleanup_mode="delete")
        server.psql("SELECT 1")
    except Exception as exc:
        pytest.skip(f"pgserver bootstrap failed: {exc}")

    try:
        yield server
    finally:
        server.cleanup()


async def _run_connection_resilience_check(postgres_server: pgserver.PostgresServer) -> None:
    database_url = make_url(postgres_server.get_uri()).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(database_url, **db.ASYNC_ENGINE_KWARGS)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with session_factory() as session:
            await session.execute(
                text(
                    "CREATE TABLE pooled_connection_resilience "
                    "(id integer PRIMARY KEY, payload text NOT NULL)"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO pooled_connection_resilience (id, payload) "
                    "VALUES (1, 'before')"
                )
            )
            await session.commit()

        postgres_server.psql(
            "SELECT pg_terminate_backend(pid) "
            "FROM pg_stat_activity WHERE pid <> pg_backend_pid()"
        )

        async with session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO pooled_connection_resilience (id, payload) "
                    "VALUES (2, 'after')"
                )
            )
            await session.commit()
            result = await session.execute(
                text(
                    "SELECT payload FROM pooled_connection_resilience "
                    "ORDER BY id"
                )
            )

        assert result.scalars().all() == ["before", "after"]
    finally:
        await engine.dispose()


def test_asyncpg_pool_recovers_after_server_terminates_connections(
    postgres_server: pgserver.PostgresServer,
) -> None:
    asyncio.run(_run_connection_resilience_check(postgres_server))
