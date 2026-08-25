"""Admission check: gpt_image mode is rejected when IMAGE_API_KEY is not set."""
from __future__ import annotations

import json
import uuid

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.models import User
from server.rate_limit import limiter


def _make_client(image_api_key: str = "") -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(
        api_key="x", gemini_api_key="x", image_api_key=image_api_key
    )
    limiter.reset()
    return TestClient(app, raise_server_exceptions=False)


def test_gpt_image_mode_empty_key_rejected_422() -> None:
    client = _make_client(image_api_key="")
    try:
        response = client.get("/api/generate?image_generation_mode=gpt_image")
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "IMAGE_API_KEY" in response.text


def test_gpt_image_mode_with_key_passes_admission() -> None:
    client = _make_client(image_api_key="sk-test-key")
    try:
        response = client.get("/api/generate?image_generation_mode=gpt_image")
    finally:
        limiter.reset()
    assert response.status_code != 422


def test_html_mode_empty_key_passes_admission() -> None:
    client = _make_client(image_api_key="")
    try:
        response = client.get("/api/generate")
    finally:
        limiter.reset()
    assert response.status_code != 422


def test_subquestion_configs_gpt_image_empty_key_rejected() -> None:
    configs = json.dumps([{"image_generation_mode": "gpt_image"}])
    client = _make_client(image_api_key="")
    try:
        response = client.get(
            f"/api/generate?subquestion_configs={configs}"
        )
    finally:
        limiter.reset()
    assert response.status_code == 422
    assert "IMAGE_API_KEY" in response.text
