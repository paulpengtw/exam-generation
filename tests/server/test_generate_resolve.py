"""Tests for the whole-payload generation resolver endpoint."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.models import User
from server.rate_limit import limiter


@pytest.fixture
def resolve_client() -> TestClient:
    limiter.reset()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_config] = lambda: ServerConfig(api_key="x")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    limiter.reset()


def test_resolve_endpoint_returns_completed_math_payload(resolve_client: TestClient) -> None:
    payload = {
        "subject": "math",
        "seed": 41,
        "grade": 8,
        "context": ["個人"],
        "set_type": "單一題",
        "q_type": ["選擇題"],
        "style": ["text_only"],
        "learning_content": ["A-7-7"],
        "learning_performance": ["s-IV-12"],
        "core_competency": ["數-J-A2"],
    }

    response = resolve_client.post("/api/generate/resolve", json=payload)

    assert response.status_code == 200
    assert response.json()["payload"]["content_type"] == "含圖片"
    assert response.json()["drawn"] == ["數學思考", "題目內容類型"]


def test_resolve_endpoint_predraws_social_count_and_rebuilds_slots(
    resolve_client: TestClient,
) -> None:
    payload = {
        "subject": "social_studies",
        "seed": 0,
        "grade": 8,
        "context": ["個人"],
        "set_type": "題組題",
        "subject_filter": ["歷史"],
        "core_competency": ["社-J-A1"],
        "content_domain": "Civic Institutions and Systems",
        "target_surface": "紙本",
        "learning_content": ["歷Ba-Ⅳ-1"],
        "learning_performance": ["歷1a-Ⅳ-1"],
        "content_type": "純文字",
    }

    first_response = resolve_client.post("/api/generate/resolve", json=payload)

    assert first_response.status_code == 200
    first = first_response.json()
    initial_count = first["payload"]["sub_question_count"]
    initial_configs = first["payload"]["subquestion_configs"]
    assert 3 <= initial_count <= 7
    assert len(initial_configs) == initial_count
    assert "sub_question_count" in first["drawn"]
    assert all(
        config["question_type"]
        and config["cognitive_process"]
        and config["learning_content"]
        and config["learning_performance"]
        for config in initial_configs
    )

    pinned_paths = {
        "subquestion_configs[0].question_type",
        "subquestion_configs[0].認知歷程",
        "subquestion_configs[0].learning_content",
        "subquestion_configs[0].learning_performance",
    }
    redraw_payload = {
        **first["payload"],
        "sub_question_count": None,
        "subquestion_configs": [
            {**initial_configs[0], "question_type": "開放式建構反應題"},
            *initial_configs[1:],
        ],
        "drawn": [path for path in first["drawn"] if path not in pinned_paths],
    }
    redraw_response = resolve_client.post(
        "/api/generate/resolve",
        json={**redraw_payload, "redraws": {"sub_question_count": 1}},
    )

    assert redraw_response.status_code == 200
    redrawn = redraw_response.json()
    assert redrawn["payload"]["sub_question_count"] == 6
    assert len(redrawn["payload"]["subquestion_configs"]) == 6
    assert redrawn["payload"]["subquestion_configs"][0]["question_type"] == "開放式建構反應題"
    assert "sub_question_count" in redrawn["drawn"]


@pytest.mark.parametrize(
    "math_thinking",
    [[], ["形成", "運用", "詮釋評估", "形成"], ["不合法"]],
)
def test_resolve_endpoint_rejects_invalid_math_thinking(
    resolve_client: TestClient,
    math_thinking: list[str],
) -> None:
    response = resolve_client.post(
        "/api/generate/resolve",
        json={"subject": "math", "math_thinking": math_thinking},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("subject", "rows", "expected_content_types"),
    [
        (
            "math",
            [
                {
                    "grade": 8,
                    "context": ["個人"],
                    "set_type": "單一題",
                    "q_type": ["選擇題"],
                    "style": ["text_only"],
                    "learning_content": ["A-7-7"],
                    "learning_performance": ["s-IV-12"],
                    "core_competency": ["數-J-A2"],
                },
                {
                    "grade": 8,
                    "context": ["個人"],
                    "set_type": "單一題",
                    "q_type": ["選擇題"],
                    "style": ["text_only"],
                    "learning_content": ["A-7-7"],
                    "learning_performance": ["s-IV-12"],
                    "core_competency": ["數-J-A2"],
                },
            ],
            ["graphs/charts/tables", "純文字"],
        ),
        (
            "social_studies",
            [
                {
                    "grade": 8,
                    "context": ["個人"],
                    "set_type": "題組題",
                    "subject_filter": ["歷史"],
                    "core_competency": ["社-J-A1"],
                    "content_domain": "Civic Institutions and Systems",
                    "target_surface": "紙本",
                    "learning_content": ["歷Ba-Ⅳ-1"],
                    "learning_performance": ["歷1a-Ⅳ-1"],
                    "sub_question_count": 3,
                    "subquestion_configs": [
                        {
                            "question_type": "選擇題",
                            "cognitive_process": "Knowing–Defining and Describing",
                        },
                        {
                            "question_type": "選擇題",
                            "cognitive_process": "Knowing–Illustrating with examples",
                        },
                        {
                            "question_type": "選擇題",
                            "cognitive_process": "Reasoning and Applying–Interpret information",
                        },
                    ],
                },
                {
                    "grade": 8,
                    "context": ["個人"],
                    "set_type": "題組題",
                    "subject_filter": ["歷史"],
                    "core_competency": ["社-J-A1"],
                    "content_domain": "Civic Institutions and Systems",
                    "target_surface": "紙本",
                    "learning_content": ["歷Ba-Ⅳ-1"],
                    "learning_performance": ["歷1a-Ⅳ-1"],
                    "sub_question_count": 3,
                    "subquestion_configs": [
                        {
                            "question_type": "選擇題",
                            "cognitive_process": "Knowing–Defining and Describing",
                        },
                        {
                            "question_type": "選擇題",
                            "cognitive_process": "Knowing–Illustrating with examples",
                        },
                        {
                            "question_type": "選擇題",
                            "cognitive_process": "Reasoning and Applying–Interpret information",
                        },
                    ],
                },
            ],
            ["數位閱讀", "含圖片"],
        ),
        (
            "natural_sciences",
            [
                {
                    "grade": 8,
                    "context": ["Personal"],
                    "sub_context": "Maintenance of health",
                    "set_type": "題組題",
                    "q_type": ["Simple multiple-choice"],
                    "science_competency": ["能力一：以科學的角度解釋現象"],
                    "learning_content": ["INa-Ⅳ-1"],
                    "learning_performance": ["ti-Ⅳ-1"],
                    "sub_question_count": 3,
                    "subquestion_configs": [
                        {"question_type": "Simple multiple-choice", "reporting_scale": "1"},
                        {"question_type": "Simple multiple-choice", "reporting_scale": "2"},
                        {"question_type": "Simple multiple-choice", "reporting_scale": "3"},
                    ],
                },
                {
                    "grade": 8,
                    "context": ["Personal"],
                    "sub_context": "Maintenance of health",
                    "set_type": "題組題",
                    "q_type": ["Simple multiple-choice"],
                    "science_competency": ["能力一：以科學的角度解釋現象"],
                    "learning_content": ["INa-Ⅳ-1"],
                    "learning_performance": ["ti-Ⅳ-1"],
                    "sub_question_count": 3,
                    "subquestion_configs": [
                        {"question_type": "Simple multiple-choice", "reporting_scale": "1"},
                        {"question_type": "Simple multiple-choice", "reporting_scale": "2"},
                        {"question_type": "Simple multiple-choice", "reporting_scale": "3"},
                    ],
                },
            ],
            ["graphs/charts/tables", "純文字"],
        ),
    ],
)
def test_resolve_endpoint_resolves_each_subject_batch(
    resolve_client: TestClient,
    subject: str,
    rows: list[dict[str, object]],
    expected_content_types: list[str],
) -> None:
    response = resolve_client.post(
        "/api/generate/resolve",
        json={"subject": subject, "count": 2, "seed": 1, "per_question_params": rows},
    )

    assert response.status_code == 200
    result = response.json()
    assert [row["seed"] for row in result["payload"]["per_question_params"]] == [1, 2]
    assert [
        row["content_type"] for row in result["payload"]["per_question_params"]
    ] == expected_content_types


def test_resolve_endpoint_is_idempotent_and_accepts_wrapped_body(
    resolve_client: TestClient,
) -> None:
    request = {
        "payload": {
            "subject": "math",
            "seed": 41,
            "grade": 8,
            "context": ["個人"],
            "set_type": "單一題",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "learning_content": ["A-7-7"],
            "learning_performance": ["s-IV-12"],
            "core_competency": ["數-J-A2"],
        },
        "redraws": {},
    }

    first_response = resolve_client.post("/api/generate/resolve", json=request)
    first = first_response.json()
    second_response = resolve_client.post(
        "/api/generate/resolve", json=first["payload"]
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == {
        "payload": first["payload"],
        "drawn": [],
        "cleared": [],
    }


def test_resolve_endpoint_redraw_preserves_seed_and_siblings(
    resolve_client: TestClient,
) -> None:
    payload = {
        "subject": "math",
        "seed": 41,
        "grade": 8,
        "context": ["個人"],
        "set_type": "單一題",
        "q_type": ["選擇題"],
        "style": ["text_only"],
        "learning_content": ["A-7-7"],
        "learning_performance": ["s-IV-12"],
        "core_competency": ["數-J-A2"],
    }
    first = resolve_client.post("/api/generate/resolve", json=payload).json()
    redrawn = resolve_client.post(
        "/api/generate/resolve",
        json={**payload, "redraws": {"題目內容類型": 1}},
    ).json()

    assert first["payload"]["content_type"] == "含圖片"
    assert redrawn["payload"]["content_type"] == "純文字"
    expected_pinned = {
        "subject": "math",
        "seed": 41,
        "grade": 8,
        "context": ["個人"],
        "set_type": "單一題",
        "q_type": ["選擇題"],
        "style": ["text_only"],
        "learning_content": ["A-7-7"],
        "learning_performance": ["s-IV-12"],
        "math_thinking": ["形成", "詮釋評估"],
        "core_competency": ["數-J-A2"],
    }
    assert {
        key: value for key, value in redrawn["payload"].items() if key != "content_type"
    } == expected_pinned


def test_resolve_endpoint_rejects_incompatible_parent_without_payload(
    resolve_client: TestClient,
) -> None:
    response = resolve_client.post(
        "/api/generate/resolve",
        json={
            "subject": "natural_sciences",
            "seed": 1,
            "grade": 8,
            "context": ["Global"],
            "sub_context": "Maintenance of health",
            "set_type": "單一題",
            "q_type": ["Simple multiple-choice"],
            "science_competency": ["能力一：以科學的角度解釋現象"],
            "learning_content": ["INa-Ⅳ-1"],
            "learning_performance": ["ti-Ⅳ-1"],
            "content_type": "純文字",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "field": "sub_context",
            "code": "incompatible_parent",
            "parent": "Personal",
        }
    ]
    assert "payload" not in response.json()


def test_resolve_endpoint_reports_cleared_child_after_parent_edit(
    resolve_client: TestClient,
) -> None:
    response = resolve_client.post(
        "/api/generate/resolve",
        json={
            "subject": "natural_sciences",
            "seed": 41,
            "grade": 8,
            "context": ["Global"],
            "sub_context": "Maintenance of health",
            "set_type": "題組題",
            "q_type": ["Simple multiple-choice"],
            "science_competency": ["能力一：以科學的角度解釋現象"],
            "learning_content": ["INa-Ⅳ-1"],
            "learning_performance": ["ti-Ⅳ-1"],
            "content_type": "純文字",
            "sub_question_count": 3,
            "subquestion_configs": [
                {
                    "question_type": "Simple multiple-choice",
                    "reporting_scale": "1",
                    "learning_content": ["INa-Ⅳ-1"],
                    "learning_performance": ["ti-Ⅳ-1"],
                },
                {
                    "question_type": "Simple multiple-choice",
                    "reporting_scale": "2",
                    "learning_content": ["INa-Ⅳ-1"],
                    "learning_performance": ["ti-Ⅳ-1"],
                },
                {
                    "question_type": "Simple multiple-choice",
                    "reporting_scale": "3",
                    "learning_content": ["INa-Ⅳ-1"],
                    "learning_performance": ["ti-Ⅳ-1"],
                },
            ],
            "redraws": {"情境": 1},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cleared"] == ["情境子類別"]
    assert body["drawn"] == ["情境子類別"]


def test_resolve_endpoint_rejects_an_empty_pinned_civic_intersection(
    resolve_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.social_studies import sampler

    target_domain = "Civic Principles"
    monkeypatch.setattr(
        sampler,
        "_LC_DATA",
        {
            "學習內容": [
                {
                    "學習階段": "第四學習階段",
                    "科目": "公",
                    "value": "公Synthetic-Ⅳ-1",
                    "admitted_by": {
                        "科目": ["公民與社會", "跨科"],
                        "內容領域": ["Civic Participation"],
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        sampler,
        "_LP_DATA",
        {"學習表現": [{"學習階段": "第四學習階段", "科目": "社", "value": "社1a-Ⅳ-1"}]},
    )

    response = resolve_client.post(
        "/api/generate/resolve",
        json={
            "subject": "social_studies",
            "seed": 23,
            "grade": 8,
            "context": ["個人"],
            "set_type": "題組題",
            "subject_filter": ["公民與社會"],
            "content_domain": target_domain,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "field": "learning_content",
            "code": "incompatible_parent",
            "parent": target_domain,
        }
    ]
    assert "payload" not in response.json()


def test_resolve_endpoint_requires_authentication() -> None:
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/generate/resolve", json={"subject": "math"})

    assert response.status_code == 401


def test_resolve_endpoint_rate_limit_matches_preview(resolve_client: TestClient) -> None:
    payload = {"subject": "math", "seed": 41, "grade": 8}

    for _ in range(30):
        response = resolve_client.post("/api/generate/resolve", json=payload)
        assert response.status_code == 200

    limited = resolve_client.post("/api/generate/resolve", json=payload)

    assert limited.status_code == 429
    assert "Rate limit exceeded" in limited.json()["detail"]
