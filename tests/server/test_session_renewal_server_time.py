"""Contract test for the server clock returned by ``GET /auth/me``."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth.dependencies import (
    get_config,
    get_current_token_payload,
    get_current_user,
)
from server.auth.routes import router
from server.config import ServerConfig
from server.models import User


def test_me_returns_current_utc_server_time() -> None:
    now = datetime.now(timezone.utc)
    user = User(
        id=uuid.uuid4(),
        email="teacher@example.com",
        created_at=now,
    )
    config = ServerConfig(
        api_key="test-api-key",
        jwt_secret="test-secret",
        frontend_url="https://example.com",
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_token_payload] = lambda: {
        "exp": int((now + timedelta(days=7)).timestamp()),
    }
    app.dependency_overrides[get_config] = lambda: config

    before_request = datetime.now(timezone.utc)
    with TestClient(app) as client:
        response = client.get("/auth/me")
    after_request = datetime.now(timezone.utc)

    assert response.status_code == 200
    server_time = datetime.fromisoformat(
        response.json()["server_time"].replace("Z", "+00:00")
    )
    tolerance = timedelta(seconds=3)
    assert before_request - tolerance <= server_time <= after_request + tolerance
