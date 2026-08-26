"""Pure resolver contract tests."""

from __future__ import annotations

import pytest

from src.common.resolver import ResolveConflictError, resolve


def test_resolve_draws_math_thinking_and_core_competency_when_blank() -> None:
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
        "content_type": "純文字",
    }

    result = resolve(payload)

    assert result.payload["math_thinking"] == ["形成", "詮釋評估"]
    assert result.payload["core_competency"] == ["數-J-C1"]
    assert result.drawn == ["數學思考", "核心素養"]


def test_resolve_leaves_supplied_math_thinking_and_core_competency_pinned() -> None:
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
        "math_thinking": ["運用"],
        "core_competency": ["數-J-A2"],
        "content_type": "純文字",
    }

    result = resolve(payload)

    assert result.payload == payload
    assert result.drawn == []


def test_resolve_draws_social_core_competency_when_blank() -> None:
    payload = {
        "subject": "social_studies",
        "seed": 7,
        "grade": 8,
        "context": ["個人"],
        "set_type": "題組題",
        "q_type": ["選擇題"],
        "subject_filter": ["歷史"],
        "content_domain": "Civic Institutions and Systems",
        "target_surface": "紙本",
        "learning_content": ["歷Ba-Ⅳ-1"],
        "learning_performance": ["歷1a-Ⅳ-1"],
        "content_type": "純文字",
    }

    result = resolve(payload)

    assert result.payload["core_competency"] == ["社-J-C2"]
    assert result.drawn == ["核心素養"]


def test_resolve_leaves_supplied_social_core_competency_pinned() -> None:
    payload = {
        "subject": "social_studies",
        "seed": 7,
        "grade": 8,
        "context": ["個人"],
        "set_type": "題組題",
        "q_type": ["選擇題"],
        "subject_filter": ["歷史"],
        "content_domain": "Civic Institutions and Systems",
        "target_surface": "紙本",
        "learning_content": ["歷Ba-Ⅳ-1"],
        "learning_performance": ["歷1a-Ⅳ-1"],
        "core_competency": ["社-J-A1"],
        "content_type": "純文字",
    }

    result = resolve(payload)

    assert result.payload == payload
    assert result.drawn == []


def test_resolve_fills_one_blank_math_field_from_the_request_seed() -> None:
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
        "math_thinking": ["形成"],
        "core_competency": ["數-J-A2"],
    }

    result = resolve(payload)

    assert result.payload["content_type"] == "含圖片"
    assert result.drawn == ["題目內容類型"]
    assert payload == {
        "subject": "math",
        "seed": 41,
        "grade": 8,
        "context": ["個人"],
        "set_type": "單一題",
        "q_type": ["選擇題"],
        "style": ["text_only"],
        "learning_content": ["A-7-7"],
        "learning_performance": ["s-IV-12"],
        "math_thinking": ["形成"],
        "core_competency": ["數-J-A2"],
    }


def test_resolve_complete_payload_is_unchanged() -> None:
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
        "math_thinking": ["形成"],
        "core_competency": ["數-J-A2"],
        "content_type": "含圖片",
    }

    result = resolve(payload)

    assert result.payload == payload
    assert result.drawn == []


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
                    "math_thinking": ["形成"],
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
                    "math_thinking": ["形成"],
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
def test_resolve_batch_uses_base_seed_plus_index_for_each_subject(
    subject: str,
    rows: list[dict[str, object]],
    expected_content_types: list[str],
) -> None:
    result = resolve(
        {
            "subject": subject,
            "count": 2,
            "seed": 1,
            "per_question_params": rows,
        }
    )

    resolved_rows = result.payload["per_question_params"]
    assert [row["seed"] for row in resolved_rows] == [1, 2]
    assert [row["content_type"] for row in resolved_rows] == expected_content_types
    assert result.drawn == [
        "per_question_params[0].題目內容類型",
        "per_question_params[1].題目內容類型",
    ]


def test_resolve_batch_honors_an_explicit_per_question_seed() -> None:
    row = {
        "grade": 8,
        "context": ["個人"],
        "set_type": "單一題",
        "q_type": ["選擇題"],
        "style": ["text_only"],
        "learning_content": ["A-7-7"],
        "learning_performance": ["s-IV-12"],
        "math_thinking": ["形成"],
        "core_competency": ["數-J-A2"],
    }

    result = resolve(
        {
            "subject": "math",
            "count": 2,
            "seed": 1,
            "per_question_params": [row, {**row, "seed": 99}],
        }
    )

    resolved_rows = result.payload["per_question_params"]
    assert [item["seed"] for item in resolved_rows] == [1, 99]
    assert [item["content_type"] for item in resolved_rows] == [
        "graphs/charts/tables",
        "純文字",
    ]


def test_resolve_completed_batch_is_idempotent() -> None:
    first = resolve(
        {
            "subject": "math",
            "count": 2,
            "seed": 1,
            "per_question_params": [
                {
                    "grade": 8,
                    "context": ["個人"],
                    "set_type": "單一題",
                    "q_type": ["選擇題"],
                    "style": ["text_only"],
                    "learning_content": ["A-7-7"],
                    "learning_performance": ["s-IV-12"],
                    "math_thinking": ["形成"],
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
                    "math_thinking": ["形成"],
                    "core_competency": ["數-J-A2"],
                },
            ],
        }
    )

    second = resolve(first.payload)

    assert second.payload == first.payload
    assert second.drawn == []


def test_resolve_redraw_counter_changes_only_the_requested_field() -> None:
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
        "math_thinking": ["形成"],
        "core_competency": ["數-J-A2"],
    }

    first = resolve(payload)
    redrawn = resolve(payload, redraws={"題目內容類型": 1})

    assert first.payload["content_type"] == "含圖片"
    assert redrawn.payload["content_type"] == "純文字"
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
        "math_thinking": ["形成"],
        "core_competency": ["數-J-A2"],
    }
    assert {
        key: value for key, value in redrawn.payload.items() if key != "content_type"
    } == expected_pinned
    assert first.drawn == redrawn.drawn == ["題目內容類型"]


def test_resolve_rejects_incompatible_natural_parent_pin() -> None:
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
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
            }
        )

    assert exc_info.value.errors == [
        {
            "field": "sub_context",
            "code": "incompatible_parent",
            "parent": "Personal",
        }
    ]


def test_resolve_accepts_any_admitted_natural_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.natural_sciences import sampler

    monkeypatch.setitem(
        sampler._SUB_CONTEXT_ADMITTED_BY,
        "Maintenance of health",
        ["Personal", "Global"],
    )

    result = resolve(
        {
            "subject": "natural_sciences",
            "context": ["Global"],
            "sub_context": "Maintenance of health",
        }
    )

    assert result.payload["context"] == ["Global"]
