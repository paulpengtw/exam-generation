"""Tests for server/db_attribution.py — pool checkout attribution.

TDD seams
---------
Seam 1  abandoned connection  → one WARNING naming _abandon_connection + duration ≥ 0
Seam 2  properly closed       → no WARNING
Seam 3  enabled=False         → returns False, no listeners registered
Seam 4  env parsing in db.py  → default off; "1" and "true" enable

The asyncpg test at the bottom runs only when pgserver and asyncpg are
importable; it exercises the production pool class (AsyncAdaptedQueuePool /
asyncpg.pool.PoolConnectionHolder) to confirm the attribution fires there too.
"""

from __future__ import annotations

import gc
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import create_engine  # noqa: E402, I001

from server.db_attribution import install_checkout_attribution  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers shared across seams 1-3  (sync SQLite — no asyncio needed)
# ---------------------------------------------------------------------------

def _make_sync_engine():
    """Fresh in-memory sync SQLite engine for testing attribution mechanics."""
    return create_engine("sqlite:///:memory:")


def _abandon_connection(engine) -> None:
    """Check out a raw sync connection and drop it without closing.

    This function is deliberately named so the attribution warning can cite it.
    """
    conn = engine.raw_connection()  # fires checkout event
    del conn  # CPython: ref-count → 0 → weakref.finalize fires immediately


def _close_connection(engine) -> None:
    """Check out a raw sync connection and properly close it."""
    conn = engine.raw_connection()
    conn.close()  # fires checkin event, clears _attribution


# ---------------------------------------------------------------------------
# Seam 1 (RED first)  — abandoned → warning names _abandon_connection + duration
# ---------------------------------------------------------------------------

def test_abandoned_connection_emits_attribution_warning(caplog):
    """Seam 1: GC-finalised connection produces a warning naming the origin."""
    engine = _make_sync_engine()
    install_checkout_attribution(engine, enabled=True)

    with caplog.at_level(logging.WARNING, logger="server.db_attribution"):
        _abandon_connection(engine)
        gc.collect()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) >= 1, (
        "Expected at least one db_attribution WARNING; caplog:\n" + caplog.text
    )
    msg = warnings[0].message
    assert "_abandon_connection" in msg, (
        f"Expected '_abandon_connection' in warning message; got:\n{msg}"
    )
    held = warnings[0].__dict__.get("db_attribution_held_s")
    assert held is not None, "db_attribution_held_s missing from log record extra"
    assert held >= 0, f"held duration must be ≥ 0, got {held}"


# ---------------------------------------------------------------------------
# Seam 2 — properly closed → no warning
# ---------------------------------------------------------------------------

def test_properly_closed_connection_emits_no_warning(caplog):
    """Seam 2: explicit checkin clears attribution so no warning fires on GC."""
    engine = _make_sync_engine()
    install_checkout_attribution(engine, enabled=True)

    with caplog.at_level(logging.WARNING, logger="server.db_attribution"):
        _close_connection(engine)
        gc.collect()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [], (
        "Unexpected attribution warning for a properly closed connection:\n"
        + caplog.text
    )


# ---------------------------------------------------------------------------
# Seam 3 — enabled=False → returns False, no listeners registered
# ---------------------------------------------------------------------------

def test_disabled_returns_false_and_registers_no_listeners():
    """Seam 3: disabled install is a strict no-op — no pool listeners added."""
    engine = _make_sync_engine()

    # Count pre-existing listeners via behavioural probe: checking out with
    # disabled install must NOT set _attribution in connection_record.info.
    result = install_checkout_attribution(engine, enabled=False)
    assert result is False

    # Confirm no listener was registered by checking out and inspecting info.
    conn = engine.raw_connection()
    try:
        record = getattr(conn, "_connection_record", None)
        assert record is not None, "_connection_record not accessible on raw fairy"
        assert "_attribution" not in record.info, (
            "Attribution was set despite enabled=False"
        )
    finally:
        conn.close()

    # Also confirm via sqlalchemy.event: after a *second* engine with enabled=True,
    # that engine does get listeners while the disabled one never had any.
    engine2 = _make_sync_engine()
    result2 = install_checkout_attribution(engine2, enabled=True)
    assert result2 is True
    # engine (disabled) must have no checkout listeners; engine2 must have one.
    # We probe behaviorally: checkout on engine never sets _attribution.
    conn2 = engine2.raw_connection()
    try:
        rec2 = getattr(conn2, "_connection_record", None)
        assert rec2 is not None
        assert "_attribution" in rec2.info, (
            "Attribution not set on enabled engine — listeners missing"
        )
    finally:
        conn2.close()


# ---------------------------------------------------------------------------
# Seam 4 — env var parsing in server/db.py
# ---------------------------------------------------------------------------

def test_env_var_default_is_off(monkeypatch):
    """Seam 4a: DB_POOL_CHECKOUT_ATTRIBUTION defaults to off when unset."""
    monkeypatch.delenv("DB_POOL_CHECKOUT_ATTRIBUTION", raising=False)
    from server.db import _get_attribution_enabled
    assert _get_attribution_enabled() is False


def test_env_var_one_enables_attribution(monkeypatch):
    """Seam 4b: DB_POOL_CHECKOUT_ATTRIBUTION=1 returns True."""
    monkeypatch.setenv("DB_POOL_CHECKOUT_ATTRIBUTION", "1")
    from server.db import _get_attribution_enabled
    assert _get_attribution_enabled() is True


def test_env_var_true_enables_attribution(monkeypatch):
    """Seam 4c: DB_POOL_CHECKOUT_ATTRIBUTION=true (case-insensitive) returns True."""
    monkeypatch.setenv("DB_POOL_CHECKOUT_ATTRIBUTION", "true")
    from server.db import _get_attribution_enabled
    assert _get_attribution_enabled() is True


def test_env_var_other_values_are_off(monkeypatch):
    """Seam 4d: arbitrary non-truthy values remain off."""
    monkeypatch.setenv("DB_POOL_CHECKOUT_ATTRIBUTION", "yes")
    from server.db import _get_attribution_enabled
    assert _get_attribution_enabled() is False


# ---------------------------------------------------------------------------
# asyncpg / pgserver — production pool class confirmation
# ---------------------------------------------------------------------------

pgserver = pytest.importorskip("pgserver")
asyncpg = pytest.importorskip("asyncpg")

from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


@pytest.fixture
def postgres_server(tmp_path: Path) -> Iterator:
    try:
        server = pgserver.get_server(tmp_path / "pgdata", cleanup_mode="delete")
        server.psql("SELECT 1")
    except Exception as exc:
        pytest.skip(f"pgserver bootstrap failed: {exc}")
    try:
        yield server
    finally:
        server.cleanup()


async def _abandon_connection_coro(engine) -> None:
    """Coroutine that checks out a connection from an async engine and drops it.

    Named with ``_abandon_connection`` so the attribution warning can cite it
    via the asyncio task's coroutine stack (SQLAlchemy's greenlet adapter means
    the synchronous stack is invisible at checkout time; the coroutine stack
    is used as a fallback to recover user frames).
    """
    await engine.connect()
    # Intentionally NOT closing — the reference is dropped here.


def _run_abandon_connection_coro(engine) -> None:
    """Sync wrapper: runs _abandon_connection_coro and triggers GC."""
    import asyncio

    asyncio.run(_abandon_connection_coro(engine))


def test_asyncpg_abandoned_connection_emits_attribution_warning(
    postgres_server, caplog
):
    """Seam 1 (asyncpg): attribution fires on GC for the asyncpg production pool."""
    database_url = make_url(postgres_server.get_uri()).set(
        drivername="postgresql+asyncpg"
    )
    engine = create_async_engine(database_url)
    install_checkout_attribution(engine.sync_engine, enabled=True)

    with caplog.at_level(logging.WARNING, logger="server.db_attribution"):
        _run_abandon_connection_coro(engine)
        gc.collect()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) >= 1, (
        "Expected attribution warning for asyncpg abandoned connection; "
        "caplog:\n" + caplog.text
    )
    msg = warnings[0].message
    assert "_abandon_connection" in msg, (
        f"Origin not found in asyncpg warning: {msg}"
    )
