"""Issue #905 – Postgres-marked smoke test for the CI service container.

Verifies that:
  1. The ``postgres`` marker skips with a clear message when TEST_POSTGRES_URL
     is absent and pgserver is not importable (tested in TestSkipReason).
  2. When a real Postgres backend is available (TEST_POSTGRES_URL or pgserver),
     tests marked ``postgres`` connect via the asyncpg driver the app uses and
     exercise semantics that SQLite cannot provide:
     SELECT … FOR UPDATE SKIP LOCKED.

The test uses asyncio.run() directly (consistent with the existing persistence
suites in this repo) so no pytest-asyncio plugin is required.

Env var: TEST_POSTGRES_URL (not DATABASE_URL).
  DATABASE_URL is read at import time by server.db to build the module-level
  engine; overriding it would route all importing tests through Postgres.
  TEST_POSTGRES_URL is opt-in and only used by postgres-marked tests.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")
pytest.importorskip("asyncpg", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import text

_ENV_VAR = "TEST_POSTGRES_URL"


# ---------------------------------------------------------------------------
# Helper used by TDD tests (tests the plugin directly, not through subprocess)
# ---------------------------------------------------------------------------


def _get_test_url() -> str:
    """Return TEST_POSTGRES_URL or call pytest.skip.  Used by TDD tests only."""
    url = os.environ.get(_ENV_VAR)
    if not url:
        pytest.skip(
            f"Postgres not available: {_ENV_VAR} is not set.  "
            f"Set {_ENV_VAR}=postgresql+asyncpg://user:pass@host:5432/dbname "
            "to run postgres-marked tests."
        )
    return url


# ---------------------------------------------------------------------------
# TDD: verify the skip reason when TEST_POSTGRES_URL is absent
# ---------------------------------------------------------------------------


class TestSkipReason:
    """Ensure the plugin and helper produce helpful messages when TEST_POSTGRES_URL
    is unset.  These tests check behavior without actually connecting to Postgres,
    so they always run regardless of database availability.
    """

    def test_skip_reason_names_the_env_var(self, monkeypatch):
        """The plugin's skip reason includes the exact env var name when both
        TEST_POSTGRES_URL is absent and pgserver cannot be imported."""
        import builtins
        import sys

        import tests.plugins.postgres_db as plugin

        # Simulate collection with no TEST_POSTGRES_URL set.
        monkeypatch.delenv(_ENV_VAR, raising=False)
        # Reset the module state so the probe runs fresh.
        monkeypatch.setattr(plugin, "_PROBE_DONE", False)
        monkeypatch.setattr(plugin, "_POSTGRES_SKIP_REASON", None)
        monkeypatch.setattr(plugin, "_PGSERVER_INSTANCE", None)
        monkeypatch.setattr(plugin, "_PGSERVER_URL", None)
        monkeypatch.setattr(plugin, "_PGSERVER_CONNECT_ARGS", None)

        # Make pgserver unimportable so the fallback path is taken.
        original_import = builtins.__import__

        def blocking_import(name, *args, **kwargs):
            if name == "pgserver":
                raise ImportError("pgserver blocked for test")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocking_import)
        # Also remove from sys.modules if cached.
        saved = sys.modules.pop("pgserver", None)

        try:
            # Build a fake session with one postgres-marked item.
            class FakeMarker:
                pass

            class FakeItem:
                def get_closest_marker(self, name):
                    return FakeMarker() if name == "postgres" else None

            class FakeSession:
                items = [FakeItem()]

            plugin.pytest_collection_finish(FakeSession())  # type: ignore[arg-type]
        finally:
            if saved is not None:
                sys.modules["pgserver"] = saved

        assert plugin._POSTGRES_SKIP_REASON is not None
        assert _ENV_VAR in plugin._POSTGRES_SKIP_REASON, (
            f"Expected {_ENV_VAR!r} in skip reason, got: {plugin._POSTGRES_SKIP_REASON!r}"
        )

    def test_unmarked_test_skip_reason_absent(self, monkeypatch):
        """No skip reason is set when no postgres-marked tests are collected."""
        import tests.plugins.postgres_db as plugin

        monkeypatch.delenv(_ENV_VAR, raising=False)
        monkeypatch.setattr(plugin, "_PROBE_DONE", False)
        monkeypatch.setattr(plugin, "_POSTGRES_SKIP_REASON", None)

        class FakeItem:
            def get_closest_marker(self, name):
                return None  # Not marked postgres.

        class FakeSession:
            items = [FakeItem()]

        plugin.pytest_collection_finish(FakeSession())  # type: ignore[arg-type]

        assert plugin._POSTGRES_SKIP_REASON is None

    def test_get_test_url_skips_when_env_absent(self, monkeypatch):
        """_get_test_url() calls pytest.skip with a message naming TEST_POSTGRES_URL."""
        monkeypatch.delenv(_ENV_VAR, raising=False)
        with pytest.raises(pytest.skip.Exception) as exc_info:
            _get_test_url()
        assert _ENV_VAR in str(exc_info.value)


# ---------------------------------------------------------------------------
# The actual Postgres smoke test (requires TEST_POSTGRES_URL)
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_postgres_asyncpg_driver_and_skip_locked(pg_engine):
    """Connect via asyncpg and prove real Postgres semantics.

    Verifies:
    - The asyncpg driver is in use (dialect name is 'postgresql', not 'sqlite').
    - SELECT … FOR UPDATE SKIP LOCKED executes without error (SQLite raises a
      syntax error here; success confirms real Postgres semantics).
    - The server identifies as PostgreSQL 16 or later.

    This test is marked ``postgres`` and will be skipped automatically when
    neither TEST_POSTGRES_URL is set nor the pgserver package is importable.

    To run locally with Docker:
        docker run --rm -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16
        TEST_POSTGRES_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres \\
            uv run pytest tests/server/test_905_postgres_smoke.py -v -m postgres

    Or just install the dev dependencies (pgserver is already listed) and run
    without setting TEST_POSTGRES_URL; the plugin starts pgserver automatically.
    """

    async def _run() -> None:
        async with pg_engine.connect() as conn:
            # 1. Confirm we are talking to PostgreSQL, not SQLite.
            version_str: str = await conn.scalar(text("SELECT version()"))
            assert "PostgreSQL" in version_str, (
                f"Expected a PostgreSQL server, got: {version_str!r}"
            )

            # 2. Confirm version is 16+ (the CI service container is Postgres 16).
            #    server_version_num returns an integer string like '160004'.
            server_ver: str = await conn.scalar(text("SHOW server_version_num"))
            major = int(server_ver) // 10000
            assert major >= 16, (
                f"Expected Postgres 16+, got server_version_num={server_ver!r} (major={major})"
            )

            # 3. SELECT … FOR UPDATE SKIP LOCKED — SQLite raises a syntax error here.
            #    Use a temp table so the test is fully self-contained.
            await conn.execute(
                text(
                    "CREATE TEMP TABLE smoke_skip_locked "
                    "(id serial PRIMARY KEY, val text NOT NULL)"
                )
            )
            await conn.execute(
                text("INSERT INTO smoke_skip_locked (val) VALUES ('hello'), ('world')")
            )
            rows = await conn.execute(
                text("SELECT id, val FROM smoke_skip_locked FOR UPDATE SKIP LOCKED")
            )
            fetched = rows.fetchall()
            assert len(fetched) == 2, (
                f"Expected 2 rows from SKIP LOCKED scan, got {len(fetched)}"
            )

            # 4. Confirm the asyncpg driver is in use (not aiosqlite).
            dialect_name: str = conn.dialect.name
            assert dialect_name == "postgresql", (
                f"Expected dialect 'postgresql' (asyncpg), got {dialect_name!r}"
            )

            await conn.rollback()

    asyncio.run(_run())
