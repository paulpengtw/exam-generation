from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationLog, LLMExchange, User
from server.rate_limit import limiter


@pytest.fixture
def app_ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    config = ServerConfig(api_key="x", jwt_secret="test-secret")

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    limiter.reset()

    yield app, SessionLocal, config

    limiter.reset()
    asyncio.run(engine.dispose())


def _seed(SessionLocal, user_id: uuid.UUID, log_id: uuid.UUID, *, exchanges: int) -> None:
    async def _add() -> None:
        async with SessionLocal() as s:
            s.add(User(id=user_id, email=f"{user_id}@example.com"))
            s.add(
                GenerationLog(
                    id=log_id,
                    user_id=user_id,
                    params_json={"subject": "math"},
                    status="completed",
                )
            )
            for i in range(exchanges):
                s.add(
                    LLMExchange(
                        generation_log_id=log_id,
                        exchange_order=exchanges - i,  # inserted out of order on purpose
                        agent="generator" if i == 0 else f"sub_generator#{i}",
                        purpose="generate",
                        request_body={"messages": [{"role": "user", "content": f"q{i}"}]},
                        response_body={"content": f"a{i}"},
                        model_used="claude-sonnet-4-6",
                        prompt_tokens=10 + i,
                        completion_tokens=1 + i,
                    )
                )
            await s.commit()

    asyncio.run(_add())


def test_owner_lists_exchanges_sorted_by_order(app_ctx):
    app, SessionLocal, config = app_ctx
    user_id = uuid.uuid4()
    log_id = uuid.uuid4()
    _seed(SessionLocal, user_id, log_id, exchanges=3)

    token = create_jwt(user_id, "u@example.com", config=config)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/generation-logs/{log_id}/exchanges",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert [row["exchange_order"] for row in data] == [1, 2, 3]
    assert data[0]["model_used"] == "claude-sonnet-4-6"
    # exchange_order = exchanges - i = 3 - i, so order=1 corresponds to i=2,
    # which is deterministically the first row after ORDER BY exchange_order ASC.
    assert data[0]["request_body"]["messages"][0]["content"] == "q2"


def test_other_user_gets_404(app_ctx):
    app, SessionLocal, config = app_ctx
    owner_id = uuid.uuid4()
    log_id = uuid.uuid4()
    _seed(SessionLocal, owner_id, log_id, exchanges=1)

    other_id = uuid.uuid4()

    async def add_other() -> None:
        async with SessionLocal() as s:
            s.add(User(id=other_id, email="other@example.com"))
            await s.commit()

    asyncio.run(add_other())

    token = create_jwt(other_id, "other@example.com", config=config)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/generation-logs/{log_id}/exchanges",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 404


def test_unknown_log_id_returns_404(app_ctx):
    app, SessionLocal, config = app_ctx
    user_id = uuid.uuid4()

    async def add_user() -> None:
        async with SessionLocal() as s:
            s.add(User(id=user_id, email="u@example.com"))
            await s.commit()

    asyncio.run(add_user())

    token = create_jwt(user_id, "u@example.com", config=config)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/generation-logs/{uuid.uuid4()}/exchanges",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 404


def test_unauthenticated_returns_401(app_ctx):
    app, _SessionLocal, _config = app_ctx
    with TestClient(app) as client:
        resp = client.get(f"/api/generation-logs/{uuid.uuid4()}/exchanges")
    assert resp.status_code == 401
