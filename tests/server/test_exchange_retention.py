from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import prune_expired_llm_exchanges
from server.config import ServerConfig
from server.models import Base, GenerationLog, LLMExchange, User


def _make_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    return engine


def _seed(SessionLocal, log_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async def _add() -> None:
        async with SessionLocal() as s:
            s.add(User(id=user_id, email="u@example.com"))
            s.add(
                GenerationLog(
                    id=log_id,
                    user_id=user_id,
                    params_json={},
                    status="completed",
                )
            )
            old = datetime.now(timezone.utc) - timedelta(days=45)
            fresh = datetime.now(timezone.utc) - timedelta(days=1)
            s.add(
                LLMExchange(
                    generation_log_id=log_id,
                    exchange_order=1,
                    agent="generator",
                    purpose="generate",
                    request_body=None,
                    response_body=None,
                    model_used="m",
                    created_at=old,
                )
            )
            s.add(
                LLMExchange(
                    generation_log_id=log_id,
                    exchange_order=2,
                    agent="verifier",
                    purpose="verify",
                    request_body=None,
                    response_body=None,
                    model_used="m",
                    created_at=fresh,
                )
            )
            await s.commit()

    asyncio.run(_add())


def test_prune_removes_rows_older_than_window():
    engine = _make_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    _seed(SessionLocal, uuid.uuid4(), uuid.uuid4())
    config = ServerConfig(api_key="x", jwt_secret="s", llm_exchange_retention_days=30)

    asyncio.run(prune_expired_llm_exchanges(config, session_maker=SessionLocal))

    async def _read():
        async with SessionLocal() as s:
            result = await s.execute(select(LLMExchange).order_by(LLMExchange.exchange_order))
            return list(result.scalars().all())

    rows = asyncio.run(_read())
    asyncio.run(engine.dispose())
    assert [r.exchange_order for r in rows] == [2]
    assert rows[0].agent == "verifier"


def test_prune_is_noop_when_retention_zero():
    engine = _make_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    _seed(SessionLocal, uuid.uuid4(), uuid.uuid4())
    config = ServerConfig(api_key="x", jwt_secret="s", llm_exchange_retention_days=0)

    asyncio.run(prune_expired_llm_exchanges(config, session_maker=SessionLocal))

    async def _read():
        async with SessionLocal() as s:
            result = await s.execute(select(LLMExchange))
            return list(result.scalars().all())

    rows = asyncio.run(_read())
    asyncio.run(engine.dispose())
    # 0 means "disable persistence entirely" — pruning must not delete existing rows.
    assert len(rows) == 2
