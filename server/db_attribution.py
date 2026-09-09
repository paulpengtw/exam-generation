"""Pool checkout attribution for asyncpg leak detection.

Enabled by setting the env var ``DB_POOL_CHECKOUT_ATTRIBUTION=1`` (or ``true``).
Default: **off**.  When enabled, two SQLAlchemy pool event listeners are
registered on the sync engine:

* ``checkout`` — records the call-stack origin (up to 5 frames, excluding
  SQLAlchemy / asyncio / anyio / starlette internals) and a monotonic timestamp
  in ``connection_record.info``, then attaches a :func:`weakref.finalize` to
  the connection proxy that fires if the proxy is garbage-collected without the
  connection having been returned to the pool.

* ``checkin`` — clears the marker so the finalizer becomes a no-op.

When the finalizer fires with the marker still present (the connection was
never explicitly returned), **one** :class:`logging.WARNING` is emitted to the
``server.db_attribution`` logger.  The :class:`sentry_sdk.integrations.logging.
LoggingIntegration` already configured in :mod:`server.observability` ships
that record to Sentry, so no additional Sentry client call is needed.

Cost
----
*Disabled* (default): zero — no listeners are registered.
*Enabled* (staging flag on): one ``traceback.extract_stack()`` call per
connection checkout.  That is cheap enough for staging traffic and adds no
measurable overhead to production when the flag is unset.
"""

from __future__ import annotations

import asyncio
import logging
import os as _os
import time
import traceback
import weakref
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger("server.db_attribution")

# Absolute path of this file — used to skip our own frames without matching
# any other file that happens to have "db_attribution" in its path.
_THIS_FILE = _os.path.abspath(__file__)

# Sub-strings that identify "infrastructure" frames we skip when building the
# origin string.  We keep frames that belong to application code.
_SKIP_SUBSTRINGS: tuple[str, ...] = (
    "sqlalchemy",
    "asyncio",
    "anyio",
    "starlette",
    "site-packages",
)


def _should_skip(filename: str) -> bool:
    """Return True if *filename* belongs to infrastructure, not application code."""
    if _os.path.abspath(filename) == _THIS_FILE:
        return True
    return any(s in filename for s in _SKIP_SUBSTRINGS)


def _origin_frames() -> str:
    """Return up to 5 caller frames outside SQLAlchemy / async internals.

    Checks both the synchronous call stack (via :func:`traceback.extract_stack`)
    and — when called inside an asyncio event loop — the coroutine frames of the
    current task (:meth:`asyncio.Task.get_stack`).  The coroutine-stack fallback
    is needed because SQLAlchemy's async adapter dispatches pool events inside a
    greenlet, so the synchronous stack contains only asyncio / SQLAlchemy
    internals with no user frames visible.

    Format: ``/abs/path.py:funcname:lineno <- …`` (most-recent first).
    """
    frames: list[str] = []

    # --- synchronous stack --------------------------------------------------
    for frame in reversed(traceback.extract_stack()):
        if _should_skip(frame.filename):
            continue
        frames.append(f"{frame.filename}:{frame.name}:{frame.lineno}")
        if len(frames) >= 5:
            break

    # --- asyncio task coroutine stack (fallback for async pool adapters) -----
    if not frames:
        try:
            task = asyncio.current_task()
            if task is not None:
                for f in reversed(task.get_stack()):
                    filename = f.f_code.co_filename
                    name = f.f_code.co_name
                    lineno = f.f_lineno
                    if _should_skip(filename):
                        continue
                    frames.append(f"{filename}:{name}:{lineno}")
                    if len(frames) >= 5:
                        break
        except Exception:
            pass

    return " <- ".join(frames) if frames else "unknown"


def install_checkout_attribution(engine: Engine, *, enabled: bool) -> bool:
    """Register pool checkout attribution hooks on *engine* (a **sync** Engine).

    Pass ``async_engine.sync_engine`` when working with an
    :class:`sqlalchemy.ext.asyncio.AsyncEngine`.

    When *enabled* is ``False`` this function is a strict no-op: no listeners
    are registered and ``False`` is returned.

    When *enabled* is ``True`` two pool event listeners are registered
    (``checkout`` and ``checkin``) and ``True`` is returned.

    The hooks are idempotent with respect to *enabled=True*: calling this
    function twice on the same engine with *enabled=True* registers duplicate
    listeners (SQLAlchemy allows this); callers should call it exactly once.

    Args:
        engine: A SQLAlchemy **sync** :class:`~sqlalchemy.engine.Engine`.
        enabled: Whether to install the attribution hooks.

    Returns:
        ``True`` if hooks were installed, ``False`` otherwise.
    """
    if not enabled:
        return False

    @event.listens_for(engine, "checkout")
    def _on_checkout(
        dbapi_connection: Any,
        connection_record: Any,
        connection_proxy: Any,
    ) -> None:
        try:
            origin = _origin_frames()
            start = time.monotonic()
            connection_record.info["_attribution"] = (origin, start)

            # Capture only connection_record (long-lived, pool-owned) in the
            # closure.  Do NOT capture connection_proxy: that would create a
            # reference cycle and prevent the proxy from being collected.
            _rec = connection_record

            def _on_gc() -> None:
                """Finalizer: fires when proxy is GC'd without being checked in."""
                try:
                    attr = _rec.info.pop("_attribution", None)
                    if attr is None:
                        # checkin already cleared the marker — normal path.
                        return
                    origin_str, t0 = attr
                    held = time.monotonic() - t0
                    logger.warning(
                        "Pool connection finalized without checkin: "
                        "origin=%s held=%.3fs",
                        origin_str,
                        held,
                        extra={
                            "db_attribution_origin": origin_str,
                            "db_attribution_held_s": held,
                        },
                    )
                except Exception:
                    # Never raise from a GC finalizer.
                    pass

            try:
                # CPython clears weakrefs in LIFO order, so this finalizer
                # (registered after SQLAlchemy's own fairy_ref weakref) fires
                # FIRST when the proxy is collected — before checkin fires.
                weakref.finalize(connection_proxy, _on_gc)
            except TypeError:
                # Proxy does not support weak references — skip silently.
                pass
        except Exception:
            # Never raise from a pool event hook.
            pass

    @event.listens_for(engine, "checkin")
    def _on_checkin(dbapi_connection: Any, connection_record: Any) -> None:
        try:
            # Clear the marker so _on_gc is a no-op when the proxy is GC'd.
            connection_record.info.pop("_attribution", None)
        except Exception:
            pass

    return True
