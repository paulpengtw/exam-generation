"""Async SQLAlchemy engine and session factory for the web server."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")

ASYNC_ENGINE_KWARGS = {
    "echo": False,
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

engine = create_async_engine(DATABASE_URL, **ASYNC_ENGINE_KWARGS)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session."""
    async with AsyncSessionLocal() as session:
        yield session
