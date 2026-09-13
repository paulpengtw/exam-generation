"""Tests for server/db_attribution.py — pool checkout attribution.

TDD seams
---------
Seam 1  abandoned connection  → one WARNING naming _abandon_connection + duration ≥ 0
Seam 2  properly closed       → no WARNING
Seam 3  enabled=False         → returns False, no listeners registered
Seam 4  env parsing in db.py  → default off; "1" and "true" enable
Seam 5  asyncpg + AsyncSession + nested coroutine → first frame names the nested
         leaking function, not SQLAlchemy runtime-generated ``<string>`` code
         (issue #585 follow-up: greenlet parent frame walk)
Seam 6  Sentry delivery → abandoned connection warning reaches Sentry as its own
         event with level "warning" and origin in db_attribution_origin extra

The asyncpg tests at the bottom run only when pgserver and asyncpg are
importable; they exercise the production pool class (AsyncAdaptedQueuePool /
asyncpg.pool.PoolConnectionHolder) to confirm attribution fires and origins are
meaningful there.
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

# ---------------------------------------------------------------------------
# Seam 5 — asyncpg + AsyncSession + nested coroutine names the leaking frame
# ---------------------------------------------------------------------------
#
# The production checkout path uses AsyncSession (not engine.connect directly).
# SQLAlchemy's async adapter dispatches the pool checkout event inside a
# greenlet spawned by greenlet_spawn.  There, traceback.extract_stack() and
# asyncio.current_task().get_stack() do NOT reach the nested coroutine that
# actually leaked the session.  Walking greenlet.getcurrent().parent.gr_frame
# is required to recover user frames.
#
# Expected RED (before fix): origin is "<string>:_connection_for_bind:2"
# Expected GREEN (after fix): first frame names _nested_session_leaker

import asyncio as _asyncio  # noqa: E402

from sqlalchemy import text as _text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker as _async_sessionmaker,
)

from server.db import ASYNC_ENGINE_KWARGS  # noqa: E402


async def _nested_session_leaker(session_factory) -> None:
    """Nested coroutine that leaks an AsyncSession without closing it.

    Named deliberately so the greenlet-parent-frame walk can cite this
    function in the attribution origin (issue #585 follow-up).
    """
    s = session_factory()
    await s.execute(_text("select 1"))
    # Intentionally NOT closing — the reference is dropped here.


async def _outer_session_coro(session_factory) -> None:
    """Outer coroutine that awaits the nested leaking helper."""
    await _nested_session_leaker(session_factory)


def test_asyncpg_asyncsession_nested_coroutine_names_leaker(
    postgres_server, caplog
):
    """Seam 5: greenlet parent walk names the nested leaking coroutine.

    The session is abandoned inside *_nested_session_leaker*, which is called
    from *_outer_session_coro*.  Without the greenlet parent frame walk, the
    origin would be ``<string>:_connection_for_bind:2`` — useless.  After the
    fix, the first frame must cite *_nested_session_leaker*.
    """
    database_url = make_url(postgres_server.get_uri()).set(
        drivername="postgresql+asyncpg"
    )
    engine = create_async_engine(database_url, **ASYNC_ENGINE_KWARGS)
    install_checkout_attribution(engine.sync_engine, enabled=True)

    session_factory = _async_sessionmaker(
        engine, expire_on_commit=False, class_=_AsyncSession
    )

    with caplog.at_level(logging.WARNING, logger="server.db_attribution"):
        _asyncio.run(_outer_session_coro(session_factory))
        gc.collect()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) >= 1, (
        "Expected at least one db_attribution WARNING for AsyncSession nested "
        "leak; caplog:\n" + caplog.text
    )
    msg = warnings[0].message
    # First frame (most-recent; text before first " <- ") must name the leaker.
    first_frame = msg.split(" <- ")[0]
    assert "_nested_session_leaker" in first_frame, (
        f"Expected '_nested_session_leaker' as first frame; "
        f"got full origin:\n{msg}"
    )
    # Must not contain SQLAlchemy runtime-generated frames.
    assert "<string>" not in msg, (
        f"Origin must not contain '<string>' (runtime-generated frame); "
        f"got:\n{msg}"
    )

    _asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seam 6 — attribution warning is delivered to Sentry as its own event
# ---------------------------------------------------------------------------
#
# server.observability configures LoggingIntegration, which forwards WARNING+
# log records to Sentry.  This seam confirms end-to-end delivery: after
# abandoning a connection on an instrumented sync SQLite engine, a Sentry
# event appears with level "warning", logger "server.db_attribution", and
# origin naming _abandon_connection.
#
# This seam may be GREEN on first run (delivery was confirmed manually); it
# is kept as a regression guard.

import json as _json  # noqa: E402

pytest.importorskip("sentry_sdk", reason="requires [web] extras: uv sync --extra web")
import sentry_sdk  # noqa: E402
import sentry_sdk.transport  # noqa: E402


def test_attribution_warning_delivered_to_sentry(monkeypatch):
    """Seam 6: abandoned connection warning reaches Sentry via LoggingIntegration."""
    from server import observability

    # Initialise Sentry through the real init_sentry() with a dummy DSN so
    # LoggingIntegration is wired up exactly as in production.
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setattr(observability, "_initialized", False)
    observability.init_sentry()

    # Replace active transport with an in-memory capturing transport so
    # nothing leaves the process.
    captured_envelopes: list = []

    class _CaptureTransport(sentry_sdk.transport.Transport):
        def capture_envelope(self, envelope) -> None:
            captured_envelopes.append(envelope)

    client = sentry_sdk.get_client()
    original_transport = client.transport
    client.transport = _CaptureTransport()

    try:
        # Abandon a connection on the existing sync SQLite helper — cheap,
        # no pgserver needed for this seam.
        engine = _make_sync_engine()
        install_checkout_attribution(engine, enabled=True)
        _abandon_connection(engine)
        gc.collect()
        sentry_sdk.flush()

        # Collect attribution events from all captured envelopes.
        attr_events: list[dict] = []
        for env in captured_envelopes:
            for item in env.items:
                if item.type == "event":
                    data = _json.loads(item.get_bytes())
                    if data.get("logger") == "server.db_attribution":
                        attr_events.append(data)

        assert len(attr_events) >= 1, (
            f"Expected at least one Sentry event from server.db_attribution; "
            f"got {len(captured_envelopes)} envelopes total (0 matching)"
        )
        ev = attr_events[0]
        assert ev["level"] == "warning", (
            f"Expected Sentry event level 'warning'; got {ev['level']}"
        )
        extra = ev.get("extra", {})
        origin = extra.get("db_attribution_origin", "")
        assert "_abandon_connection" in origin, (
            f"Expected '_abandon_connection' in db_attribution_origin extra; "
            f"got: {origin!r}.  Full extra: {extra}"
        )
        assert "db_attribution_held_s" in extra, (
            f"db_attribution_held_s missing from Sentry event extra; got: {extra}"
        )
    finally:
        # Restore global Sentry state so no later test in the session runs with
        # a live client.  Close flushes in-flight events; set_client(None) on
        # the global scope unbinds the client, leaving a NonRecordingClient.
        client.transport = original_transport
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)
        monkeypatch.setattr(observability, "_initialized", False)
