"""Async SQLAlchemy engine and session factory for the web server."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db_attribution import install_checkout_attribution

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")

ASYNC_ENGINE_KWARGS = {
    "echo": False,
    "pool_pre_ping": True,
    "pool_recycle": 300,
}


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
