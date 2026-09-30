"""Issue #911 – Postgres concurrent-claim tests.

Two concurrent hosts racing to claim the same queued or stale run must each
succeed at most once (FOR UPDATE SKIP LOCKED guarantee).  These tests run
against a real Postgres instance because SQLite ignores the SKIP LOCKED clause.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.config import ServerConfig
from server.generate.run import (
    MAX_ATTEMPTS,
    STALE_THRESHOLD_S,
    ClaimedRun,
    accept_run,
    claim_next_run,
)
from server.models import Base, GenerationLog, User
from tests.server.generate_test_utils import resolved_generate_params

_MATH: dict[str, Any] = {
    "subject": "math",
    "seed": 41,
    "grade": 8,
    "context": ["個人"],
    "set_type": "單一題",
    "q_type": ["選擇題"],
    "style": ["text_only"],
    "math_thinking": ["形成"],
    "learning_content": ["A-7-7"],
    "learning_performance": ["s-IV-12"],
    "core_competency": ["數-J-A2"],
    "content_type": "純文字",
    "skip_verify": True,
}


async def _setup_pg(sf: Any) -> uuid.UUID:
    """Create tables and a test user; return the user's id."""
    engine = sf.kw["bind"]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    owner = uuid.uuid4()
    async with sf() as session:
        session.add(User(id=owner, email=f"{owner}@example.com"))
        await session.commit()
    return owner


@pytest.mark.postgres
def test_concurrent_claimers_never_claim_same_run(pg_engine: Any) -> None:
    """Two concurrent hosts racing to claim a queued run must not both succeed.

    One host gets the run; the other gets None.
    """
    sf = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _run() -> None:
        async with pg_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Truncate tables to avoid state from other postgres tests.
            for tbl in reversed(Base.metadata.sorted_tables):
                await conn.execute(tbl.delete())

        owner = uuid.uuid4()
        async with sf() as session:
            session.add(User(id=owner, email=f"{owner}@example.com"))
            await session.commit()

        params = resolved_generate_params({**_MATH, "count": 1})
        async with sf() as session:
            accepted = await accept_run(params, owner, session=session)
        run_id = uuid.UUID(accepted.run_id)

        # Two concurrent claims.
        host_a_task = asyncio.create_task(
            claim_next_run(sf, host_id="host-a")
        )
        host_b_task = asyncio.create_task(
            claim_next_run(sf, host_id="host-b")
        )
        results = await asyncio.gather(host_a_task, host_b_task)

        non_none = [r for r in results if r is not None]
        assert len(non_none) == 1, (
            f"exactly one claim must succeed; got {len(non_none)} winners: {results}"
        )
        assert non_none[0].run_id == run_id

    asyncio.run(_run())


@pytest.mark.postgres
def test_concurrent_stale_reclaim_exactly_one_wins(pg_engine: Any) -> None:
    """Two concurrent hosts racing to reclaim a stale running run — exactly one wins."""
    sf = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _run() -> None:
        async with pg_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for tbl in reversed(Base.metadata.sorted_tables):
                await conn.execute(tbl.delete())

        owner = uuid.uuid4()
        async with sf() as session:
            session.add(User(id=owner, email=f"{owner}@example.com"))
            await session.commit()

        params = resolved_generate_params({**_MATH, "count": 1})
        async with sf() as session:
            accepted = await accept_run(params, owner, session=session)
        run_id = uuid.UUID(accepted.run_id)

        # Make the run stale (1 attempt used, not exhausted).
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD_S + 60)
        async with sf() as session:
            await session.execute(
                update(GenerationLog)
                .where(GenerationLog.id == run_id)
                .values(
                    status="running",
                    attempts=1,
                    claimed_by="dead-host",
                    heartbeat_at=stale_time,
                    started_at=stale_time,
                )
            )
            await session.commit()

        host_a_task = asyncio.create_task(claim_next_run(sf, host_id="host-a"))
        host_b_task = asyncio.create_task(claim_next_run(sf, host_id="host-b"))
        results = await asyncio.gather(host_a_task, host_b_task)

        non_none = [r for r in results if r is not None]
        assert len(non_none) == 1, (
            f"exactly one reclaim must succeed; got {len(non_none)}: {results}"
        )
        assert non_none[0].run_id == run_id
        assert non_none[0].attempt == 2

    asyncio.run(_run())
