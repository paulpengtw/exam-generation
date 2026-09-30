"""Pytest plugin: session-level Postgres availability check for ``postgres`` tests.

If any test marked ``postgres`` is collected, the plugin checks for the
``TEST_POSTGRES_URL`` environment variable.  When absent but the ``pgserver``
package (a dev dependency) is importable, the plugin starts an in-process
Postgres 16 instance for the session.  When neither is available, every
marked test is skipped with a clear message naming the variable to set.  If
no postgres-marked tests are collected the check is skipped entirely.

Unmarked tests are never affected: they continue to use the default SQLite
engine from ``server/db.py`` (``DATABASE_URL`` is intentionally not set).
The dedicated variable ``TEST_POSTGRES_URL`` (not ``DATABASE_URL``) is used
because ``server/db.py`` reads ``DATABASE_URL`` at import time; overriding it
would silently route every test that imports ``server.db`` through Postgres.

Public helpers provided
-----------------------
``postgres_test_url(database=None) -> str | None``
    Returns an asyncpg SQLAlchemy URL for either the ``TEST_POSTGRES_URL``
    case or the pgserver fallback, optionally pointed at a different database.
    Returns ``None`` when Postgres is unavailable.  Tests use this instead of
    reading private plugin state such as ``_PGSERVER_CONNECT_ARGS``.

Fixtures provided
-----------------
``pg_engine`` (session-scoped, async, requires ``postgres`` marker)
    An async SQLAlchemy engine pointed at the test Postgres instance.
    Tests that need the engine should request this fixture directly.

See: docs/adr/0035-run-claim-tests-target-postgres-in-ci.md
"""

from __future__ import annotations

import os

import pytest

# Module-level state.
_POSTGRES_SKIP_REASON: str | None = None
_PROBE_DONE: bool = False
# Holds a pgserver.PostgresServer instance when started by the plugin.
_PGSERVER_INSTANCE = None
# The effective engine kwargs when pgserver is used (connect_args with socket host).
_PGSERVER_CONNECT_ARGS: dict | None = None
# The effective async-engine URL when pgserver is used.
_PGSERVER_URL: str | None = None

_ENV_VAR = "TEST_POSTGRES_URL"


def postgres_test_url(database: str | None = None) -> str | None:
    """Return an asyncpg SQLAlchemy URL for the test Postgres instance.

    Points at *database* (default: the database from ``TEST_POSTGRES_URL``, or
    ``postgres`` for the pgserver fallback).  Returns ``None`` when Postgres is
    unavailable so callers can ``pytest.skip`` without importing private names.

    For pgserver, the socket directory is embedded as ``?host=<dir>`` in the
    returned URL so the URL is self-contained for both SQLAlchemy and asyncpg DSN
    use.  Callers that need keyword-argument form for ``asyncpg.connect()`` can
    derive it from the URL::

        url = postgres_test_url()
        if url and "?host=" in url:
            socket_dir = url.split("?host=")[1]
        else:
            admin_dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    See the ``pg_engine`` fixture for session-level usage.
    """
    url = os.environ.get(_ENV_VAR)
    if url:
        if database is not None:
            url = f"{url.rsplit('/', 1)[0]}/{database}"
        return url
    if _PGSERVER_CONNECT_ARGS is not None:
        socket_dir = _PGSERVER_CONNECT_ARGS.get("host")
        if socket_dir:
            db = database or "postgres"
            return f"postgresql+asyncpg://postgres@/{db}?host={socket_dir}"
    return None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "postgres: mark test as requiring a Postgres 16 database "
        f"(set {_ENV_VAR}=postgresql+asyncpg://... to enable, "
        "or ensure the pgserver dev package is installed)",
    )


def pytest_collection_finish(session: pytest.Session) -> None:  # noqa: C901
    """After collection: ensure Postgres is available for ``postgres`` tests."""
    global _POSTGRES_SKIP_REASON, _PROBE_DONE, _PGSERVER_INSTANCE
    global _PGSERVER_CONNECT_ARGS, _PGSERVER_URL
    if _PROBE_DONE:
        return
    _PROBE_DONE = True

    marked = [item for item in session.items if item.get_closest_marker("postgres")]
    if not marked:
        return

    url = os.environ.get(_ENV_VAR)
    if url:
        # TEST_POSTGRES_URL is set; marked tests will use it directly.
        return

    # Try to start a pgserver instance as a fallback.
    try:
        import tempfile

        import pgserver  # type: ignore[import]

        pgdata = tempfile.mkdtemp(prefix="pytest_pgserver_")
        _PGSERVER_INSTANCE = pgserver.get_server(pgdata, cleanup_mode="delete")
        raw_uri = _PGSERVER_INSTANCE.get_uri()  # postgresql://postgres:@/postgres?host=<dir>
        socket_dir = raw_uri.split("?host=")[1]
        _PGSERVER_CONNECT_ARGS = {"host": socket_dir}
        _PGSERVER_URL = "postgresql+asyncpg://postgres@/postgres"
        # Leave _POSTGRES_SKIP_REASON as None: tests will run via pgserver.
        return
    except ImportError:
        pgserver_detail = "; pgserver is not installed (pip install pgserver)"
    except Exception as exc:  # noqa: BLE001
        pgserver_detail = f"; pgserver startup failed: {exc}"

    _POSTGRES_SKIP_REASON = (
        f"Postgres not available: {_ENV_VAR} is not set"
        f"{pgserver_detail}.  "
        f"Set {_ENV_VAR}=postgresql+asyncpg://user:pass@host:5432/dbname "
        "to run postgres-marked tests."
    )


def pytest_sessionfinish(
    session: pytest.Session,  # noqa: ARG001
    exitstatus: int,  # noqa: ARG001
) -> None:
    """Clean up the in-process pgserver after the session."""
    global _PGSERVER_INSTANCE
    if _PGSERVER_INSTANCE is not None:
        try:
            _PGSERVER_INSTANCE.cleanup()
        except Exception:  # noqa: BLE001
            pass
        _PGSERVER_INSTANCE = None


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip ``postgres`` tests when no Postgres backend is available."""
    if _POSTGRES_SKIP_REASON and item.get_closest_marker("postgres"):
        pytest.skip(_POSTGRES_SKIP_REASON)


def pytest_terminal_summary(
    terminalreporter,  # noqa: ANN001
    exitstatus: int,  # noqa: ARG001
    config: pytest.Config,  # noqa: ARG001
) -> None:
    """Write the Postgres unavailability cause exactly once in the terminal summary."""
    if _POSTGRES_SKIP_REASON:
        terminalreporter.write_sep("=", "Postgres precheck")
        terminalreporter.write_line(
            f"Postgres not available: {_POSTGRES_SKIP_REASON}",
            yellow=True,
        )


# ---------------------------------------------------------------------------
# Fixture provided by this plugin
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped async SQLAlchemy engine for Postgres tests.

    Connects to the URL in TEST_POSTGRES_URL when set, or to the in-process
    pgserver instance started at collection time.  If neither is available
    the test is skipped.

    The engine is created synchronously; tests call ``asyncio.run()`` for any
    async work (consistent with the existing persistence test style in this repo).

    Usage::

        @pytest.mark.postgres
        def test_something(pg_engine):
            async def _run():
                async with pg_engine.connect() as conn:
                    result = await conn.scalar(text("SELECT 1"))
            asyncio.run(_run())
    """
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ.get(_ENV_VAR)
    if url:
        engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    elif _PGSERVER_URL and _PGSERVER_CONNECT_ARGS:
        engine = create_async_engine(
            _PGSERVER_URL,
            echo=False,
            pool_pre_ping=True,
            connect_args=_PGSERVER_CONNECT_ARGS,
        )
    else:
        pytest.skip(
            f"Postgres not available: {_ENV_VAR} is not set and pgserver is unavailable."
        )
        return  # unreachable; for type checker

    yield engine

    # Dispose the engine after all postgres tests in the session finish.
    asyncio.run(engine.dispose())
