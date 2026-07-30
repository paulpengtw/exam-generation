"""Tests for /health and /api/schemas."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config
from server.config import ServerConfig, _DEFAULT_MODELS_ALLOWED


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
    body = r.json()
    # Math is the default subject; the base file contents must be present,
    # plus the math augmentation fields (科目, 題目內容類型, 學習表現).
    assert body["學習階段"] == payload["學習階段"]
    assert body["grades"] == payload["grades"]
    assert {entry["value"] for entry in body["科目"]} == {
        "數與量", "代數", "幾何", "統計與機率",
    }
    assert [entry["value"] for entry in body["題目內容類型"]] == [
        "純文字", "含圖片", "graphs/charts/tables", "customized",
    ]
    assert "學習表現" in body


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


def test_math_schemas_include_the_learning_content_pool(tmp_path: Path) -> None:
    payload = {"學習階段": "第四學習階段", "grades": [7, 8, 9]}
    schemas_file = tmp_path / "question_schemas.json"
    schemas_file.write_text(json.dumps(payload), encoding="utf-8")

    app = create_app()
    app.dependency_overrides[get_config] = lambda: _config(schemas_file)
    with TestClient(app) as client:
        r = client.get("/api/schemas?subject=math")

    assert r.status_code == 200
    learning_content = r.json()["學習內容"]
    assert learning_content
    strand_prefixes = set("NnAaFfRrSsGgDdPp")
    assert all(set(entry) == {"value", "instruction", "科目"} for entry in learning_content)
    assert all(
        len(entry["科目"]) == 1 and entry["科目"] in strand_prefixes
        for entry in learning_content
    )


def test_math_learning_content_is_filtered_to_the_resolved_learning_stage(
    tmp_path: Path,
) -> None:
    payload = {"學習階段": "第五學習階段", "grades": [7, 8, 9]}
    schemas_file = tmp_path / "question_schemas.json"
    schemas_file.write_text(json.dumps(payload), encoding="utf-8")
    content_path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "math"
        / "curriculum"
        / "learning_content.json"
    )
    content_data = json.loads(content_path.read_text(encoding="utf-8"))
    expected_values = {
        entry["value"]
        for entry in content_data["學習內容"]
        if entry["學習階段"] == "第四學習階段"
    }

    app = create_app()
    app.dependency_overrides[get_config] = lambda: _config(schemas_file)
    with TestClient(app) as client:
        r = client.get("/api/schemas?subject=math&grade=7")

    assert r.status_code == 200
    returned_values = {entry["value"] for entry in r.json()["學習內容"]}
    assert returned_values == expected_values


def test_natural_sciences_schemas_include_pisa_science_dimensions() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/schemas?subject=natural_sciences")
    assert r.status_code == 200
    body = r.json()

    assert body["grades"] == [7, 8, 9, 10, 11, 12]
    assert [entry["value"] for entry in body["情境"]] == [
        "Personal",
        "Local and national",
        "Global",
    ]
    assert [entry["value"] for entry in body["題型種類"]] == ["題組題"]
    assert [entry["value"] for entry in body["題型"]] == [
        "Simple multiple-choice",
        "Complex multiple-choice",
        "Constructed response",
    ]
    assert len(body["科學能力"]) == 6
    assert any(entry.get("parent") == "Global" for entry in body["情境子類別"])

    learning_performance = body["學習表現"]
    assert len(learning_performance) == 20
    assert {"value", "instruction", "科目"} <= set(learning_performance[0])
    assert "tr-Ⅳ-1" in {entry["value"] for entry in learning_performance}


def test_models_endpoint_returns_allowlist_and_defaults() -> None:
    app = create_app()
    cfg = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        model_plan="claude-opus-4-6",
        model_execute="claude-sonnet-4-6",
        llm_models_allowed=(
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-6",
        ),
    )
    app.dependency_overrides[get_config] = lambda: cfg
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 200
    assert r.json() == {
        "allowed": [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-6",
        ],
        "defaults": {
            "plan": "claude-opus-4-6",
            "execute": "claude-sonnet-4-6",
        },
    }


def test_models_endpoint_falls_back_to_defaults_only() -> None:
    app = create_app()
    cfg = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        model_plan="claude-opus-4-6",
        model_execute="claude-sonnet-4-6",
        # Explicitly empty allowlist to mirror the "env unset" default before
        # from_env fills it in — the endpoint must still return both defaults.
        llm_models_allowed=("claude-opus-4-6", "claude-sonnet-4-6"),
    )
    app.dependency_overrides[get_config] = lambda: cfg
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["defaults"] == {
        "plan": "claude-opus-4-6",
        "execute": "claude-sonnet-4-6",
    }
    assert body["allowed"] == ["claude-opus-4-6", "claude-sonnet-4-6"]


def test_models_endpoint_fresh_env_returns_five_models_and_sonnet_default(
    tmp_path: Path,
) -> None:
    """GET /api/models on a fresh (env-less) config must return the built-in
    5-model roster and plan default of claude-sonnet-4-6 (issue #252, updated by #379)."""
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "test-secret"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    app = create_app()
    app.dependency_overrides[get_config] = lambda: cfg
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["defaults"] == {"plan": "claude-sonnet-4-6", "execute": "claude-sonnet-4-6"}
    assert body["allowed"] == list(_DEFAULT_MODELS_ALLOWED)


def test_schemas_rejects_unknown_subject_422(tmp_path: Path) -> None:
    """GET /api/schemas with an unknown subject must return 422."""
    schemas_file = tmp_path / "question_schemas.json"
    schemas_file.write_text("{}", encoding="utf-8")

    app = create_app()
    app.dependency_overrides[get_config] = lambda: _config(schemas_file)
    with TestClient(app) as client:
        r = client.get("/api/schemas?subject=unknown_thing")
    assert r.status_code == 422
    detail = r.json()["detail"]
    # Error must name the offending value and list allowed subjects.
    assert "unknown_thing" in detail
    assert "math" in detail
