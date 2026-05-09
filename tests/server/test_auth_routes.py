"""Tests for /auth/* endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.email import ConsoleEmailSender
from server.auth.routes import _email_sender_dep
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, MagicLinkToken, User


def _config() -> ServerConfig:
    return ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        jwt_expire_days=7,
        frontend_url="https://example.com",
        email_backend="console",
    )


class _CapturingSender(ConsoleEmailSender):
    def __init__(self) -> None:
        super().__init__(frontend_url="https://example.com")
        self.sent: list[tuple[str, str]] = []

    def send(self, to_email: str, raw_token: str) -> None:  # type: ignore[override]
        self.sent.append((to_email, raw_token))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


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

    config = _config()
    sender = _CapturingSender()

    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config
    app.dependency_overrides[_email_sender_dep] = lambda: sender

    yield app, SessionLocal, config, sender

    asyncio.run(engine.dispose())


def _query_all(SessionLocal, model):
    async def _q():
        async with SessionLocal() as session:
            res = await session.execute(select(model))
            return res.scalars().all()

    return asyncio.run(_q())


def _add(SessionLocal, *objs):
    async def _a():
        async with SessionLocal() as session:
            for o in objs:
                session.add(o)
            await session.commit()

    asyncio.run(_a())


def test_magic_link_returns_200_for_unknown_email(app_ctx) -> None:
    app, SessionLocal, _, sender = app_ctx
    with TestClient(app) as client:
        resp = client.post("/auth/magic-link", json={"email": "new@example.com"})
    assert resp.status_code == 200
    assert resp.json() == {"message": "Check your email"}
    assert sender.sent and sender.sent[0][0] == "new@example.com"

    rows = _query_all(SessionLocal, MagicLinkToken)
    assert len(rows) == 1
    assert rows[0].token_hash == hashlib.sha256(sender.sent[0][1].encode()).hexdigest()


def test_verify_with_valid_token_creates_user_and_returns_jwt(app_ctx) -> None:
    app, SessionLocal, config, sender = app_ctx
    with TestClient(app) as client:
        client.post("/auth/magic-link", json={"email": "new@example.com"})
        email, raw = sender.sent[0]
        resp = client.get("/auth/verify", params={"token": raw, "email": email})

    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    users = _query_all(SessionLocal, User)
    tokens = _query_all(SessionLocal, MagicLinkToken)
    assert len(users) == 1
    assert users[0].email == "new@example.com"
    assert tokens[0].used_at is not None


def test_verify_with_expired_token_returns_401(app_ctx) -> None:
    app, SessionLocal, _, _ = app_ctx
    raw = "expired-raw-token"
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    _add(
        SessionLocal,
        MagicLinkToken(
            email="user@example.com",
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ),
    )

    with TestClient(app) as client:
        resp = client.get(
            "/auth/verify", params={"token": raw, "email": "user@example.com"}
        )
    assert resp.status_code == 401


def test_verify_reused_token_returns_401(app_ctx) -> None:
    app, _, _, sender = app_ctx
    with TestClient(app) as client:
        client.post("/auth/magic-link", json={"email": "u@example.com"})
        email, raw = sender.sent[0]
        first = client.get("/auth/verify", params={"token": raw, "email": email})
        assert first.status_code == 200
        second = client.get("/auth/verify", params={"token": raw, "email": email})
    assert second.status_code == 401


def test_me_without_token_returns_401(app_ctx) -> None:
    app, _, _, _ = app_ctx
    with TestClient(app) as client:
        resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_with_valid_jwt_returns_user(app_ctx) -> None:
    app, SessionLocal, config, _ = app_ctx
    user_id = uuid.uuid4()
    _add(SessionLocal, User(id=user_id, email="me@example.com"))

    token = create_jwt(user_id, "me@example.com", config=config)
    with TestClient(app) as client:
        resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "me@example.com"
    assert body["id"] == str(user_id)


def test_me_with_bad_jwt_returns_401(app_ctx) -> None:
    app, _, _, _ = app_ctx
    with TestClient(app) as client:
        resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_app_includes_auth_routes() -> None:
    app = create_app()
    paths = {route.path for route in app.router.routes}
    assert "/auth/magic-link" in paths
    assert "/auth/verify" in paths
    assert "/auth/me" in paths
