"""Server-level test: requested_model survives persistence and is returned by the
exchanges endpoint (issue #942, task 3.2).

Verifies that:
- A substituted exchange (request_body contains requested_model) is returned
  verbatim by GET /api/generation-logs/{id}/exchanges with model_used equal to
  the dispatched model and requested_model equal to the original Fable id.
- An unsubstituted exchange (no requested_model in request_body) has no such key
  in the response.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, GenerationLog, LLMExchange, User
from server.rate_limit import limiter

DISPATCHED_MODEL = "claude-opus-4-6"
REQUESTED_MODEL = "claude-fable-5"


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


def _seed_exchanges(SessionLocal, user_id: uuid.UUID, log_id: uuid.UUID) -> None:
    """Seed one substituted exchange (exchange_order=1) and one plain one (order=2)."""

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
            # Exchange 1: substituted — request_body carries requested_model.
            s.add(
                LLMExchange(
                    generation_log_id=log_id,
                    exchange_order=1,
                    agent="verifier",
                    purpose="verify",
                    request_body={
                        "messages": [{"role": "user", "content": "q"}],
                        "model": DISPATCHED_MODEL,
                        "requested_model": REQUESTED_MODEL,
                    },
                    response_body={"content": "ok"},
                    model_used=DISPATCHED_MODEL,
                    prompt_tokens=10,
                    completion_tokens=5,
                )
            )
            # Exchange 2: not substituted — no requested_model in request_body.
            s.add(
                LLMExchange(
                    generation_log_id=log_id,
                    exchange_order=2,
                    agent="generator",
                    purpose="generate",
                    request_body={
                        "messages": [{"role": "user", "content": "gen"}],
                        "model": DISPATCHED_MODEL,
                    },
                    response_body={"content": "result"},
                    model_used=DISPATCHED_MODEL,
                    prompt_tokens=20,
                    completion_tokens=10,
                )
            )
            await s.commit()

    asyncio.run(_add())


def test_exchanges_endpoint_returns_requested_model_for_substituted(app_ctx):
    """Substituted exchange: model_used is dispatched model; request_body has requested_model."""
    app, SessionLocal, config = app_ctx
    user_id = uuid.uuid4()
    log_id = uuid.uuid4()
    _seed_exchanges(SessionLocal, user_id, log_id)

    token = create_jwt(user_id, f"{user_id}@example.com", config=config)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/generation-logs/{log_id}/exchanges",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    substituted = data[0]  # exchange_order=1
    assert substituted["exchange_order"] == 1
    assert substituted["model_used"] == DISPATCHED_MODEL
    assert substituted["request_body"]["model"] == DISPATCHED_MODEL
    assert substituted["request_body"]["requested_model"] == REQUESTED_MODEL


def test_exchanges_endpoint_omits_requested_model_for_unsubstituted(app_ctx):
    """Unsubstituted exchange: request_body must not contain requested_model key."""
    app, SessionLocal, config = app_ctx
    user_id = uuid.uuid4()
    log_id = uuid.uuid4()
    _seed_exchanges(SessionLocal, user_id, log_id)

    token = create_jwt(user_id, f"{user_id}@example.com", config=config)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/generation-logs/{log_id}/exchanges",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    plain = data[1]  # exchange_order=2
    assert plain["exchange_order"] == 2
    assert plain["model_used"] == DISPATCHED_MODEL
    assert "requested_model" not in plain["request_body"]
