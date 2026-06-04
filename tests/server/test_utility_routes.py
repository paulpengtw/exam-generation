"""Tests for /health and /api/schemas."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config
from server.config import ServerConfig


def _config(schemas_path: Path) -> ServerConfig:
    return ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        question_schemas_path=schemas_path,
    )


def test_health() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_schemas_returns_file_contents(tmp_path: Path) -> None:
    payload = {"學習階段": "第四學習階段", "grades": [7, 8, 9]}
    schemas_file = tmp_path / "question_schemas.json"
    schemas_file.write_text(json.dumps(payload), encoding="utf-8")

    app = create_app()
    app.dependency_overrides[get_config] = lambda: _config(schemas_file)
    with TestClient(app) as client:
        r = client.get("/api/schemas")
    assert r.status_code == 200
    assert r.json() == payload


def test_schemas_missing_file(tmp_path: Path) -> None:
    app = create_app()
    app.dependency_overrides[get_config] = lambda: _config(tmp_path / "missing.json")
    with TestClient(app) as client:
        r = client.get("/api/schemas")
    assert r.status_code == 500


def test_social_studies_schemas_include_content_types() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/schemas?subject=social_studies")
    assert r.status_code == 200
    body = r.json()
    values = [entry["value"] for entry in body["題目內容類型"]]
    assert values == ["純文字", "含圖片", "graphs/charts/tables", "customized"]

    learning_performance = body["學習表現"]
    assert learning_performance
    assert {"value", "instruction", "科目"} <= set(learning_performance[0])
    assert "社1b-Ⅳ-1" in {entry["value"] for entry in learning_performance}
