"""Tests for the stream_version 426 admission gate on /api/generate."""
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.event_protocol import CLIENT_UPDATE_REQUIRED_DETAIL
from server.models import User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params


def _make_app():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x", gemini_api_key="x")
    limiter.reset()
    return app


def test_get_without_stream_version_returns_426():
    app = _make_app()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            params = complete_math_query_params(count=1, skip_verify=True)
            params.pop("stream_version", None)  # ensure no stream_version
            resp = client.get("/api/generate", params=params)
    finally:
        limiter.reset()
    assert resp.status_code == 426
    body = resp.json()
    assert body["detail"] == CLIENT_UPDATE_REQUIRED_DETAIL
    assert body["code"] == "CLIENT_UPDATE_REQUIRED"
    assert 2 in body["supported_stream_versions"]


def test_post_without_stream_version_returns_426():
    app = _make_app()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            params = complete_math_query_params(count=1, skip_verify=True)
            params.pop("stream_version", None)  # ensure no stream_version
            resp = client.post("/api/generate", json=params)
    finally:
        limiter.reset()
    assert resp.status_code == 426


def test_get_with_stream_version_1_returns_426():
    app = _make_app()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            params = {
                **complete_math_query_params(count=1, skip_verify=True),
                "stream_version": 1,
            }
            resp = client.get("/api/generate", params=params)
    finally:
        limiter.reset()
    assert resp.status_code == 426


def test_unauthenticated_with_missing_version_returns_401():
    """Auth check wins over version check for unauthenticated requests."""
    app = create_app()
    limiter.reset()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            params = complete_math_query_params(count=1, skip_verify=True)
            params.pop("stream_version", None)  # ensure no stream_version
            resp = client.get("/api/generate", params=params)
    finally:
        limiter.reset()
    assert resp.status_code == 401


def test_preview_without_stream_version_not_426():
    """preview endpoint is not affected by stream_version admission."""
    app = _make_app()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            params = complete_math_query_params(count=1, skip_verify=True)
            resp = client.get("/api/generate/preview", params=params)
    finally:
        limiter.reset()
    assert resp.status_code != 426


def test_stream_version_in_server_only_fields():
    from server.generate.models import SERVER_ONLY_GENERATE_FIELDS
    assert "stream_version" in SERVER_ONLY_GENERATE_FIELDS
