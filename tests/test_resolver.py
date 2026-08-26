"""Pure resolver contract tests."""

from __future__ import annotations

import secrets

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


def test_resolve_assigns_a_seed_when_the_request_omits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets, "randbelow", lambda _upper: 123)

    result = resolve(
        {
            "subject": "math",
            "grade": 8,
            "context": ["個人"],
            "set_type": "單一題",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "content_type": "純文字",
            "learning_content": ["A-7-7"],
            "learning_performance": ["s-IV-12"],
            "core_competency": ["數-J-A2"],
        }
    )

    assert result.payload["seed"] == 123
    assert "seed" in result.drawn


def test_resolve_draws_blank_per_subquestion_curriculum_fields() -> None:
    result = resolve(
        {
            "subject": "social_studies",
            "seed": 41,
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
            "subquestion_configs": [{}, {}, {}],
        }
    )

    configs = result.payload["subquestion_configs"]
    assert configs[0]["learning_content"]
    assert configs[0]["learning_performance"]
    assert "subquestion_configs[0].learning_content" in result.drawn
    assert "subquestion_configs[0].learning_performance" in result.drawn


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
    assert all(
        f"per_question_params[{index}].題目內容類型" in result.drawn
        for index in range(2)
    )
    if subject != "math":
        assert all(
            f"per_question_params[{question_index}].subquestion_configs[{subquestion_index}].learning_content"
            in result.drawn
            and (
                f"per_question_params[{question_index}].subquestion_configs[{subquestion_index}].learning_performance"
                in result.drawn
            )
            for question_index in range(2)
            for subquestion_index in range(3)
        )


def test_resolve_keeps_configured_base_seed_out_of_drawn_paths() -> None:
    result = resolve(
        {
            "subject": "math",
            "count": 2,
            "seed": 700,
            "per_question_params": [{}, {}],
        }
    )

    assert [row["seed"] for row in result.payload["per_question_params"]] == [700, 701]
    assert "per_question_params[0].seed" not in result.drawn
    assert "per_question_params[1].seed" not in result.drawn


def test_resolve_keeps_request_level_fields_out_of_batch_rows() -> None:
    result = resolve(
        {
            "subject": "math",
            "count": 1,
            "seed": 700,
            "core_question_callback": True,
            "max_retries": 4,
            "drawn": ["learning_content"],
            "per_question_params": [{}],
        }
    )

    row = result.payload["per_question_params"][0]
    assert "core_question_callback" not in row
    assert "max_retries" not in row
    assert "drawn" not in row


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


def test_resolve_rejects_a_pinned_civic_domain_with_an_empty_learning_content_intersection(
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

    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "seed": 23,
                "grade": 8,
                "context": ["個人"],
                "set_type": "題組題",
                "subject_filter": ["公民與社會"],
                "content_domain": target_domain,
            }
        )

    assert exc_info.value.errors == [
        {
            "field": "learning_content",
            "code": "incompatible_parent",
            "parent": target_domain,
        }
    ]


def test_resolve_keeps_a_pinned_civic_domain_without_consuming_its_keyed_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.social_studies import sampler

    target_domain = "Civic Roles and Identities"
    original_draw_rng = sampler.draw_rng
    domain_stream_calls: list[str] = []

    def tracked_draw_rng(seed, field_path, counter=0):
        if field_path == "內容領域":
            domain_stream_calls.append(field_path)
        return original_draw_rng(seed, field_path, counter)

    monkeypatch.setattr(sampler, "draw_rng", tracked_draw_rng)

    result = resolve(
        {
            "subject": "social_studies",
            "seed": 41,
            "grade": 8,
            "context": ["個人"],
            "set_type": "題組題",
            "subject_filter": ["公民與社會"],
            "content_domain": target_domain,
            "content_type": "純文字",
            "learning_content": ["公Aa-Ⅳ-1"],
            "learning_performance": ["社1a-Ⅳ-1"],
        }
    )

    assert result.payload["content_domain"] == target_domain
    assert "內容領域" not in result.drawn
    assert domain_stream_calls == []


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
