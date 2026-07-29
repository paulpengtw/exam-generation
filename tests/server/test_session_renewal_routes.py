"""HTTP-level tests for login-session renewal."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.routes import refresh
from server.auth.tokens import JWT_ALGORITHM, create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import jwt_user_key, limiter


@pytest.fixture
def app_ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    session_local = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_local() as session:
            yield session

    config = ServerConfig(
        api_key="test-api-key",
        jwt_secret="test-secret",
        jwt_expire_days=7,
        session_renewal_threshold_days=3,
        frontend_url="https://example.com",
    )
    app = create_app()
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_config] = lambda: config

    limiter.reset()
    yield app, session_local, config
    limiter.reset()
    asyncio.run(engine.dispose())


def _add_user(session_local, user: User) -> None:
    async def _add() -> None:
        async with session_local() as session:
            session.add(user)
            await session.commit()

    asyncio.run(_add())


def test_me_returns_session_expiry_and_renewal_threshold(app_ctx) -> None:
    app, session_local, config = app_ctx
    user_id = uuid.uuid4()
    _add_user(session_local, User(id=user_id, email="teacher@example.com"))
    token = create_jwt(user_id, "teacher@example.com", config=config)
    payload = jwt.decode(
        token,
        config.jwt_secret,
        algorithms=[JWT_ALGORITHM],
    )

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    session_expires_at = datetime.fromisoformat(
        body["session_expires_at"].replace("Z", "+00:00")
    )
    assert session_expires_at == datetime.fromtimestamp(payload["exp"], timezone.utc)
    assert body["renewal_threshold_days"] == 3
    assert body["id"] == str(user_id)
    assert body["email"] == "teacher@example.com"


def test_refresh_returns_later_token_with_preserved_origin_that_authenticates(
    app_ctx,
) -> None:
    app, session_local, config = app_ctx
    user_id = uuid.uuid4()
    email = "teacher@example.com"
    _add_user(session_local, User(id=user_id, email=email))
    config.jwt_expire_days = 1
    old_token = create_jwt(user_id, email, config=config)
    old_payload = jwt.decode(
        old_token,
        config.jwt_secret,
        algorithms=[JWT_ALGORITHM],
    )
    config.jwt_expire_days = 7

    with TestClient(app) as client:
        refresh_response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert refresh_response.status_code == 200
        refresh_body = refresh_response.json()
        new_token = refresh_body["access_token"]
        me_response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )

    assert refresh_body["token_type"] == "bearer"
    new_payload = jwt.decode(
        new_token,
        config.jwt_secret,
        algorithms=[JWT_ALGORITHM],
    )
    assert new_payload["exp"] > old_payload["exp"]
    assert new_payload["origin"] == old_payload["origin"]
    assert new_payload["sub"] == old_payload["sub"]
    assert new_payload["email"] == old_payload["email"]
    assert me_response.status_code == 200
    assert me_response.json()["id"] == str(user_id)


def test_refresh_rejects_session_older_than_thirty_days(app_ctx) -> None:
    app, session_local, config = app_ctx
    user_id = uuid.uuid4()
    email = "teacher@example.com"
    _add_user(session_local, User(id=user_id, email=email))
    old_origin = int(
        (datetime.now(timezone.utc) - timedelta(days=31)).timestamp()
    )
    token = create_jwt(user_id, email, config=config, origin=old_origin)

    with TestClient(app) as client:
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401


def test_refresh_legacy_token_uses_issued_at_as_origin(app_ctx) -> None:
    app, session_local, config = app_ctx
    user_id = uuid.uuid4()
    email = "legacy@example.com"
    _add_user(session_local, User(id=user_id, email=email))
    now = datetime.now(timezone.utc)
    issued_at = int(now.timestamp())
    legacy_token = jwt.encode(
        {
            "sub": str(user_id),
            "email": email,
            "iat": issued_at,
            "exp": int((now + timedelta(days=7)).timestamp()),
        },
        config.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )

    with TestClient(app) as client:
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {legacy_token}"},
        )

    assert response.status_code == 200
    refreshed_payload = jwt.decode(
        response.json()["access_token"],
        config.jwt_secret,
        algorithms=[JWT_ALGORITHM],
    )
    assert refreshed_payload["origin"] == issued_at


def test_refresh_without_bearer_token_returns_401(app_ctx) -> None:
    app, _, _ = app_ctx

    with TestClient(app) as client:
        response = client.post("/auth/refresh")

    assert response.status_code == 401


def test_refresh_with_expired_token_returns_401(app_ctx) -> None:
    app, session_local, config = app_ctx
    user_id = uuid.uuid4()
    email = "expired@example.com"
    _add_user(session_local, User(id=user_id, email=email))
    now = datetime.now(timezone.utc)
    expired_token = jwt.encode(
        {
            "sub": str(user_id),
            "email": email,
            "iat": int((now - timedelta(days=8)).timestamp()),
            "exp": int((now - timedelta(days=1)).timestamp()),
            "origin": int((now - timedelta(days=8)).timestamp()),
        },
        config.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )

    with TestClient(app) as client:
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {expired_token}"},
        )

    assert response.status_code == 401


def test_refresh_rate_limit_is_ten_per_hour_per_user() -> None:
    route_key = f"{refresh.__module__}.{refresh.__name__}"

    route_limits = limiter._route_limits[route_key]

    assert len(route_limits) == 1
    assert str(route_limits[0].limit) == "10 per 1 hour"
    assert route_limits[0].key_func is jwt_user_key
