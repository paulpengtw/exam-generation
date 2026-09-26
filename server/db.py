"""Async SQLAlchemy engine and session factory for the web server."""

from __future__ import annotations

import math
import os
from collections.abc import AsyncGenerator, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db_attribution import install_checkout_attribution

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")


class DatabaseUnavailableError(RuntimeError):
    """Raised when an authenticated database lookup cannot reach the database."""


def build_async_engine_kwargs(
    database_url: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the shared async engine options for a database URL."""
    kwargs: dict[str, Any] = {
        "echo": False,
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    if database_url.partition(":")[0] != "postgresql+asyncpg":
        return kwargs

    raw_timeout = (os.environ if env is None else env).get(
        "DATABASE_CONNECT_TIMEOUT_SECONDS", "10"
    )
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        timeout = 10.0
    if not math.isfinite(timeout) or timeout <= 0:
        timeout = 10.0
    if timeout.is_integer():
        timeout = int(timeout)
    kwargs["connect_args"] = {"timeout": timeout}
    return kwargs


ASYNC_ENGINE_KWARGS = build_async_engine_kwargs(DATABASE_URL)


def _get_attribution_enabled() -> bool:
    """Return True when DB_POOL_CHECKOUT_ATTRIBUTION is set to a truthy value.

    Truthy values: "1", "true" (case-insensitive).  Everything else is off,
    including unset / empty string / "yes" / "on".
    """
    return os.environ.get("DB_POOL_CHECKOUT_ATTRIBUTION", "").lower() in {"1", "true"}


engine = create_async_engine(DATABASE_URL, **ASYNC_ENGINE_KWARGS)
install_checkout_attribution(engine.sync_engine, enabled=_get_attribution_enabled())

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session."""
    async with AsyncSessionLocal() as session:
        yield session
