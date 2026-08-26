"""Tests for /health and /api/schemas."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config
from server.config import _DEFAULT_MODELS_ALLOWED, ServerConfig


def _schema_curriculum_entries(
    body: dict,
    key: str,
) -> dict[str, dict]:
    entries = body[key]
    assert entries
    assert all("admitted_by" in entry for entry in entries)
    assert all(
        "科目" in entry["admitted_by"]
        and set(entry["admitted_by"]) <= {"科目", "內容領域"}
        for entry in entries
    )
    assert all(isinstance(entry["admitted_by"]["科目"], list) for entry in entries)
    return {entry["value"]: entry for entry in entries}


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
    live_categories = {
        "情境",
        "題型種類",
        "題型",
        "認知歷程",
        "內容領域",
        "科目",
        "題目內容類型",
        "難度",
    }
    assert live_categories <= body.keys()
    assert "閱讀歷程" not in body
    assert "文本形式" not in body
    values = [entry["value"] for entry in body["題目內容類型"]]
    assert values == [
        "純文字",
        "含圖片",
        "graphs/charts/tables",
        "customized",
        "混合",
        "數位閱讀",
    ]

    learning_performance = body["學習表現"]
    assert learning_performance
    assert {"value", "instruction", "科目"} <= set(learning_performance[0])
    assert "社1b-Ⅳ-1" in {entry["value"] for entry in learning_performance}
    assert [entry["value"] for entry in body["核心素養"]] == [
        "社-J-A1", "社-J-A2", "社-J-A3",
        "社-J-B1", "社-J-B2", "社-J-B3",
        "社-J-C1", "社-J-C2", "社-J-C3",
    ]


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
    assert all(
        set(entry) == {"value", "instruction", "科目", "admitted_by"}
        for entry in learning_content
    )
    assert all(
        len(entry["科目"]) == 1 and entry["科目"] in strand_prefixes
        for entry in learning_content
    )
    assert [entry["value"] for entry in r.json()["核心素養"]] == [
        "數-J-A1", "數-J-A2", "數-J-A3",
        "數-J-B1", "數-J-B2", "數-J-B3",
        "數-J-C1", "數-J-C2", "數-J-C3",
    ]


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


@pytest.mark.parametrize("subject", ["social_studies", "math"])
def test_curriculum_schema_tags_match_each_backend_subject_pool(subject: str) -> None:
    from src.common.curriculum_loader import (
        load_learning_content,
        load_learning_performance,
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get(f"/api/schemas?subject={subject}&grade=7")

    assert response.status_code == 200
    body = response.json()
    content_by_code = _schema_curriculum_entries(body, "學習內容")
    performance_by_code = _schema_curriculum_entries(body, "學習表現")
    learning_stage = "第四學習階段"
    if subject == "social_studies":
        data_dir = Path(__file__).resolve().parents[2] / "data" / "social_studies" / "curriculum"
        content_data = load_learning_content(data_dir)
        performance_data = load_learning_performance(data_dir)
        expected_prefixes = {
            "歷史": {"歷", "社", ""},
            "地理": {"地", "社", ""},
            "公民與社會": {"公", "社", ""},
            "跨科": {"歷", "地", "公", "社", ""},
        }
    else:
        data_dir = Path(__file__).resolve().parents[2] / "data" / "math" / "curriculum"
        content_data = load_learning_content(data_dir)
        performance_data = load_learning_performance(data_dir)
        expected_prefixes = {
            "數與量": {"N", "n"},
            "代數": {"A", "F", "R", "a", "f", "r"},
            "幾何": {"S", "G", "s", "g"},
            "統計與機率": {"D", "P", "d", "p"},
            "跨領域": {
                "N", "A", "F", "R", "S", "G", "D", "P",
                "n", "a", "f", "r", "s", "g", "d", "p",
            },
        }

    expected_content_subjects = {
        candidate: {
            entry["value"]
            for entry in content_data["學習內容"]
            if entry["學習階段"] == learning_stage
            and entry["科目"] in prefixes
        }
        for candidate, prefixes in expected_prefixes.items()
    }
    expected_performance_subjects = {
        candidate: {
            entry["value"]
            for entry in performance_data["學習表現"]
            if entry["學習階段"] == learning_stage
            and entry["科目"] in prefixes
        }
        for candidate, prefixes in expected_prefixes.items()
    }

    for candidate, expected_codes in expected_content_subjects.items():
        actual_codes = {
            code
            for code, entry in content_by_code.items()
            if candidate in entry["admitted_by"]["科目"]
        }
        assert actual_codes == expected_codes
    for candidate, expected_codes in expected_performance_subjects.items():
        actual_codes = {
            code
            for code, entry in performance_by_code.items()
            if candidate in entry["admitted_by"]["科目"]
        }
        assert actual_codes == expected_codes


def test_social_schema_tags_keep_literal_shared_curriculum_entries() -> None:
    app = create_app()
    with TestClient(app) as client:
        content_response = client.get("/api/schemas?subject=social_studies&grade=3")
        performance_response = client.get("/api/schemas?subject=social_studies&grade=7")

    assert content_response.status_code == 200
    assert performance_response.status_code == 200
    content_by_code = _schema_curriculum_entries(content_response.json(), "學習內容")
    performance_by_code = _schema_curriculum_entries(
        performance_response.json(), "學習表現"
    )

    assert content_by_code["Aa-Ⅱ-1"]["admitted_by"] == {
        "科目": ["歷史", "地理", "公民與社會", "跨科"],
    }
    assert performance_by_code["社1a-Ⅳ-1"]["admitted_by"] == {
        "科目": ["歷史", "地理", "公民與社會", "跨科"],
    }


def test_social_schema_tags_use_a_runtime_curriculum_directory(tmp_path: Path) -> None:
    (tmp_path / "schema_meta.csv").write_text(
        "欄位,值\n學習階段,第四學習階段\ngrades,7;8;9\n",
        encoding="utf-8-sig",
    )
    (tmp_path / "schema_parameters.csv").write_text(
        "類別,value,instruction\n"
        "科目,歷史,\n"
        "科目,地理,\n",
        encoding="utf-8-sig",
    )
    (tmp_path / "內容領域_mapping.csv").write_text(
        "編碼,內容領域\n",
        encoding="utf-8-sig",
    )
    (tmp_path / "learning_content.json").write_text(
        json.dumps(
            {
                "學習內容": [
                    {"value": "shared-runtime", "學習階段": "第四學習階段", "科目": ""},
                    {"value": "history-runtime", "學習階段": "第四學習階段", "科目": "歷"},
                    {"value": "geography-runtime", "學習階段": "第四學習階段", "科目": "地"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "learning_performance.json").write_text(
        json.dumps(
            {
                "學習表現": [
                    {
                        "value": "shared-performance-runtime",
                        "學習階段": "第四學習階段",
                        "科目": "社",
                    },
                    {
                        "value": "history-performance-runtime",
                        "學習階段": "第四學習階段",
                        "科目": "歷",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from src.social_studies.curriculum_loader import (
        load_learning_content,
        load_learning_performance,
    )

    loaded_content = load_learning_content(tmp_path / "learning_content.json")
    assert loaded_content["學習內容"][0]["admitted_by"] == {
        "科目": ["歷史", "地理", "公民與社會", "跨科"],
    }
    loaded_performance = load_learning_performance(
        tmp_path / "learning_performance.json"
    )
    assert loaded_performance["學習表現"][0]["admitted_by"] == {
        "科目": ["歷史", "地理", "公民與社會", "跨科"],
    }

    app = create_app()
    cfg = ServerConfig(
        api_key="x",
        jwt_secret="test-secret",
        social_studies_curriculum_dir=tmp_path,
    )
    app.dependency_overrides[get_config] = lambda: cfg
    with TestClient(app) as client:
        response = client.get("/api/schemas?subject=social_studies")

    assert response.status_code == 200
    body = response.json()
    content_by_code = _schema_curriculum_entries(body, "學習內容")
    performance_by_code = _schema_curriculum_entries(body, "學習表現")
    assert content_by_code["shared-runtime"]["admitted_by"] == {
        "科目": ["歷史", "地理", "公民與社會", "跨科"],
    }
    assert content_by_code["history-runtime"]["admitted_by"] == {
        "科目": ["歷史", "跨科"],
    }
    assert performance_by_code["shared-performance-runtime"]["admitted_by"] == {
        "科目": ["歷史", "地理", "公民與社會", "跨科"],
    }


def test_social_studies_schemas_expose_the_iccs_code_to_domain_mapping() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/schemas?subject=social_studies")

    assert response.status_code == 200
    mapping = response.json()["內容領域_mapping"]
    assert mapping["公Aa-Ⅳ-1"] == ["Civic Roles and Identities"]
    assert set(mapping["公Ab-Ⅳ-1"]) == {
        "Civic Institutions and Systems",
        "Civic Principles",
    }


def test_social_learning_content_schema_tags_iccs_admitting_domains_without_affecting_history(
) -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/schemas?subject=social_studies&grade=7")

    assert response.status_code == 200
    content_by_code = {
        entry["value"]: entry for entry in response.json()["學習內容"]
    }

    assert content_by_code["公Aa-Ⅳ-1"]["admitted_by"] == {
        "科目": ["公民與社會", "跨科"],
        "內容領域": ["Civic Roles and Identities"],
    }
    assert content_by_code["公Ab-Ⅳ-1"]["admitted_by"] == {
        "科目": ["公民與社會", "跨科"],
        "內容領域": [
            "Civic Institutions and Systems",
            "Civic Principles",
        ],
    }
    assert content_by_code["歷Ka-Ⅳ-1"]["admitted_by"] == {
        "科目": ["歷史", "跨科"],
    }
    assert "內容領域" not in content_by_code["歷Ka-Ⅳ-1"]["admitted_by"]
    assert "內容領域" not in content_by_code["地Aa-Ⅳ-1"]["admitted_by"]
    assert content_by_code["歷Ka-Ⅳ-1"] == {
        "value": "歷Ka-Ⅳ-1",
        "instruction": "中華民國的建立與早期發展",
        "科目": "歷",
        "admitted_by": {"科目": ["歷史", "跨科"]},
    }
    assert content_by_code["地Aa-Ⅳ-1"] == {
        "value": "地Aa-Ⅳ-1",
        "instruction": "全球經緯度座標系統。",
        "科目": "地",
        "admitted_by": {"科目": ["地理", "跨科"]},
    }


def test_natural_sciences_schemas_include_pisa_science_dimensions() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/schemas?subject=natural_sciences")
    assert r.status_code == 200
    body = r.json()

    assert body["grades"] == [7, 8, 9, 10, 11, 12]
    assert "閱讀歷程" not in body
    assert "文本形式" not in body
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
    assert [entry["value"] for entry in body["reporting_scale"]] == [
        "1c", "1b", "1a", "2", "3", "4", "5", "6",
    ]
    assert all(entry["instruction"] for entry in body["reporting_scale"])

    learning_performance = body["學習表現"]
    assert len(learning_performance) == 20
    assert {"value", "instruction", "科目"} <= set(learning_performance[0])
    assert "tr-Ⅳ-1" in {entry["value"] for entry in learning_performance}


def test_natural_sciences_subcontexts_declare_their_admitting_context() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/schemas?subject=natural_sciences")

    assert response.status_code == 200
    entries = response.json()["情境子類別"]
    assert entries
    assert all("parent" in entry for entry in entries)
    assert all("admitted_by" in entry for entry in entries)
    assert all(set(entry["admitted_by"]) == {"情境"} for entry in entries)
    assert all(isinstance(entry["admitted_by"]["情境"], list) for entry in entries)

    by_value = {entry["value"]: entry for entry in entries}
    assert by_value["Choosing non-dairy and vegetarian diets"]["admitted_by"] == {
        "情境": ["Personal"],
    }
    assert by_value["Food security"]["admitted_by"] == {
        "情境": ["Global"],
    }


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
    body = r.json()
    assert body["allowed"] == [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-6",
    ]
    assert body["defaults"]["plan"] == "claude-opus-4-6"
    assert body["defaults"]["execute"] == "claude-sonnet-4-6"
    # Effort defaults and roster are present (issue #254).
    assert body["defaults"]["effort_plan"] == "medium"
    assert body["defaults"]["effort_execute"] == "medium"
    assert "effort" in body


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
    assert body["defaults"]["plan"] == "claude-opus-4-6"
    assert body["defaults"]["execute"] == "claude-sonnet-4-6"
    assert body["allowed"] == ["claude-opus-4-6", "claude-sonnet-4-6"]
    # Effort defaults present (issue #254).
    assert body["defaults"]["effort_plan"] == "medium"
    assert body["defaults"]["effort_execute"] == "medium"


def test_models_endpoint_fresh_env_returns_six_models_and_sonnet_default(
    tmp_path: Path,
) -> None:
    """GET /api/models on a fresh (env-less) config must return the built-in
    6-model roster and plan default of claude-sonnet-4-6 (issue #344, updated by #379)."""
    env = {"LLM_API_KEY": "x", "JWT_SECRET": "test-secret"}
    with mock.patch.dict(os.environ, env, clear=True):
        cfg = ServerConfig.from_env(env_file=tmp_path / ".env.missing")
    app = create_app()
    app.dependency_overrides[get_config] = lambda: cfg
    with TestClient(app) as client:
        r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["defaults"]["plan"] == "claude-sonnet-4-6"
    assert body["defaults"]["execute"] == "claude-sonnet-4-6"
    assert body["allowed"] == list(_DEFAULT_MODELS_ALLOWED)
    # Effort defaults are medium by default (issue #254).
    assert body["defaults"]["effort_plan"] == "medium"
    assert body["defaults"]["effort_execute"] == "medium"


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
