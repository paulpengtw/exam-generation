"""Startup pruning for generation_records (GENERATION_HISTORY_RETENTION_DAYS)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import _prune_generation_records
from server.models import Base, GenerationRecord, User


def _seed(session_maker, ages_days):
    async def _run():
        async with session_maker() as session:
            user = User(id=uuid.uuid4(), email="u@example.com")
            session.add(user)
            await session.flush()
            now = datetime.now(timezone.utc)
            for age in ages_days:
                session.add(
                    GenerationRecord(
                        user_id=user.id,
                        subject="math",
                        question_id=f"q_{age}",
                        params_json={},
                        question_json={},
                        image_files=[],
                        created_at=now - timedelta(days=age),
                    )
                )
            await session.commit()
    asyncio.run(_run())


def _count(session_maker):
    async def _run():
        async with session_maker() as session:
            result = await session.execute(select(GenerationRecord))
            return len(result.scalars().all())
    return asyncio.run(_run())


def test_prune_keeps_all_when_retention_zero():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    _seed(sm, [0, 10, 100])

    async def prune():
        async with sm() as s:
            await _prune_generation_records(s, 0)
    asyncio.run(prune())

    assert _count(sm) == 3
    asyncio.run(engine.dispose())


def test_prune_deletes_rows_older_than_retention():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    sm = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    _seed(sm, [1, 10, 45])

    async def prune():
        async with sm() as s:
            await _prune_generation_records(s, 30)
    asyncio.run(prune())

    assert _count(sm) == 2
    asyncio.run(engine.dispose())
