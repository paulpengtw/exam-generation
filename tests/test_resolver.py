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
    assert "核心素養" in result.drawn
    assert 3 <= result.payload["sub_question_count"] <= 7
    assert len(result.payload["subquestion_configs"]) == result.payload["sub_question_count"]
    assert "sub_question_count" in result.drawn


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

    assert result.payload["core_competency"] == payload["core_competency"]
    assert 3 <= result.payload["sub_question_count"] <= 7
    assert len(result.payload["subquestion_configs"]) == result.payload["sub_question_count"]
    assert "sub_question_count" in result.drawn


def test_pinned_learning_performance_is_unchanged_by_content_domain_for_civic_subject() -> None:
    """公1c-Ⅳ-1 maps to no ICCS 內容領域 (#833); pinning it must resolve as-is."""
    payload = {
        "subject": "social_studies",
        "seed": 7,
        "grade": 8,
        "context": ["個人"],
        "set_type": "題組題",
        "q_type": ["選擇題"],
        "subject_filter": ["公民與社會"],
        "content_domain": "Civic Institutions and Systems",
        "target_surface": "紙本",
        "learning_performance": ["公1c-Ⅳ-1"],
        "content_type": "純文字",
    }

    result = resolve(payload)

    assert result.payload["learning_performance"] == ["公1c-Ⅳ-1"]
    assert "learning_performance" not in result.drawn


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


def test_resolve_blank_social_count_builds_a_resolved_slot_list() -> None:
    result = resolve(
        {
            "subject": "social_studies",
            "seed": 606,
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
    )

    count = result.payload["sub_question_count"]
    configs = result.payload["subquestion_configs"]

    assert 3 <= count <= 7
    assert len(configs) == count
    assert "sub_question_count" in result.drawn
    assert all(config["question_type"] for config in configs)
    assert all(config["cognitive_process"] for config in configs)
    assert all(config["learning_content"] for config in configs)
    assert all(config["learning_performance"] for config in configs)
    assert all(
        f"subquestion_configs[{index}].{field}" in result.drawn
        for index in range(count)
        for field in (
            "question_type",
            "認知歷程",
            "learning_content",
            "learning_performance",
        )
    )


def test_resolve_blank_natural_count_builds_a_resolved_slot_list() -> None:
    result = resolve(
        {
            "subject": "natural_sciences",
            "seed": 606,
            "grade": 8,
            "context": ["Personal"],
            "sub_context": "Maintenance of health",
            "set_type": "題組題",
            "science_competency": ["能力一：以科學的角度解釋現象"],
            "learning_content": ["INa-Ⅳ-1"],
            "learning_performance": ["ti-Ⅳ-1"],
            "content_type": "純文字",
        }
    )

    count = result.payload["sub_question_count"]
    configs = result.payload["subquestion_configs"]

    assert 3 <= count <= 7
    assert len(configs) == count
    assert "sub_question_count" in result.drawn
    assert all(config["question_type"] for config in configs)
    assert all(config["reporting_scale"] for config in configs)
    assert all(config["learning_content"] for config in configs)
    assert all(config["learning_performance"] for config in configs)
    assert all(
        f"subquestion_configs[{index}].{field}" in result.drawn
        for index in range(count)
        for field in (
            "question_type",
            "reporting_scale",
            "learning_content",
            "learning_performance",
        )
    )


def test_resolve_count_redraw_rebuilds_slots_and_preserves_pinned_rows() -> None:
    initial = resolve(
        {
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
            "sub_question_count": 3,
        }
    )
    initial_configs = initial.payload["subquestion_configs"]
    pinned_config = {
        **initial_configs[0],
        "question_type": "開放式建構反應題",
    }
    pinned_paths = {
        f"subquestion_configs[0].{field}"
        for field in ("question_type", "認知歷程", "learning_content", "learning_performance")
    }
    redraw_payload = {
        **initial.payload,
        "sub_question_count": None,
        "subquestion_configs": [pinned_config, *initial_configs[1:]],
        "drawn": [path for path in initial.drawn if path not in pinned_paths],
    }

    redrawn = resolve(redraw_payload, redraws={"sub_question_count": 1})

    assert redrawn.payload["sub_question_count"] == 6
    assert len(redrawn.payload["subquestion_configs"]) == 6
    assert redrawn.payload["subquestion_configs"][0] == pinned_config
    assert "sub_question_count" in redrawn.drawn
    assert all(
        f"subquestion_configs[{index}].{field}" in redrawn.drawn
        for index in range(1, 6)
        for field in (
            "question_type",
            "認知歷程",
            "learning_content",
            "learning_performance",
        )
    )


def test_resolve_count_edit_reopens_drawn_slots_and_preserves_pinned_rows() -> None:
    initial = resolve(
        {
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
            "sub_question_count": 3,
        }
    )
    initial_configs = initial.payload["subquestion_configs"]
    pinned_config = {
        **initial_configs[0],
        "question_type": "開放式建構反應題",
    }
    pinned_paths = {
        f"subquestion_configs[0].{field}"
        for field in ("question_type", "認知歷程", "learning_content", "learning_performance")
    }
    redraw_payload = {
        **initial.payload,
        "sub_question_count": 5,
        "subquestion_configs": [pinned_config, *initial_configs[1:]],
        "drawn": [path for path in initial.drawn if path not in pinned_paths],
    }

    redrawn = resolve(redraw_payload, redraws={"sub_question_count": 1})

    assert redrawn.payload["sub_question_count"] == 5
    assert len(redrawn.payload["subquestion_configs"]) == 5
    assert redrawn.payload["subquestion_configs"][0] == pinned_config
    assert all(
        f"subquestion_configs[{index}].{field}" in redrawn.drawn
        for index in range(1, 5)
        for field in (
            "question_type",
            "認知歷程",
            "learning_content",
            "learning_performance",
        )
    )


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


def test_resolve_math_group_draws_blank_count_after_set_type_resolution() -> None:
    result = resolve(
        {
            "subject": "math",
            "seed": 1,
            "grade": 8,
            "context": ["個人"],
            "set_type": "",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "learning_content": ["A-7-7"],
            "learning_performance": ["s-IV-12"],
            "math_thinking": ["形成"],
            "core_competency": ["數-J-A2"],
            "content_type": "純文字",
            "sub_question_count": "",
        }
    )

    assert result.payload["set_type"] == "題組題"
    assert 3 <= result.payload["sub_question_count"] <= 7
    assert "sub_question_count" in result.drawn


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


def test_resolve_batch_row_learning_content_narrows_subject_before_the_request_level_pin() -> (
    None
):
    """A row's own 學習內容/學習表現 replaces the request-level pin before

    narrowing 科目 (#834): row 0 keeps the request-level 歷史-admitted code,
    row 1 overrides it with a civic-only code.
    """
    result = resolve(
        {
            "subject": "social_studies",
            "count": 2,
            "seed": 5,
            "grade": 8,
            "context": ["個人"],
            "set_type": "題組題",
            "content_type": "純文字",
            "content_domain": "Civic Institutions and Systems",
            "target_surface": "紙本",
            "core_competency": ["社-J-A1"],
            "learning_content": ["歷Fb-Ⅳ-1"],
            "per_question_params": [
                {},
                {"learning_content": ["公Bn-Ⅳ-3"], "learning_performance": ["社1a-Ⅳ-1"]},
            ],
        }
    )

    rows = result.payload["per_question_params"]
    assert rows[0]["subject_filter"][0] in {"歷史", "跨科"}
    assert rows[1]["subject_filter"][0] in {"公民與社會", "跨科"}


def test_resolve_narrowed_social_subject_and_domain_is_idempotent() -> None:
    payload = {
        "subject": "social_studies",
        "seed": 9,
        "grade": 8,
        "context": ["個人"],
        "set_type": "題組題",
        "content_type": "純文字",
        "target_surface": "紙本",
        "core_competency": ["社-J-A1"],
        "learning_content": ["公Bn-Ⅳ-3"],
        "learning_performance": ["社1a-Ⅳ-1"],
    }

    first = resolve(payload)
    second = resolve(first.payload)

    assert first.payload["subject_filter"] == ["公民與社會"] or first.payload[
        "subject_filter"
    ] == ["跨科"]
    assert first.payload["content_domain"] == "Civic Institutions and Systems"
    assert second.payload == first.payload
    assert second.drawn == []
    assert second.cleared == []


def test_resolve_rejects_multi_valued_subject_with_no_admitting_candidate_and_skips_domain() -> (
    None
):
    """科目 is evaluated before 內容領域 (#835): when 科目 fails, no 內容領域

    error is reported for that 題組, even though 內容領域 is also blank here.
    """
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "seed": 1,
                "grade": 8,
                "context": ["個人"],
                "set_type": "題組題",
                "subject_filter": ["歷史", "地理"],
                "learning_content": ["公Bj-Ⅳ-1"],
            }
        )

    assert exc_info.value.errors == [
        {"field": "learning_content", "code": "no_admitting_parent", "parent": "科目"}
    ]


def test_resolve_rejects_blank_civic_domain_with_an_empty_narrowed_range() -> None:
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "seed": 1,
                "grade": 8,
                "context": ["個人"],
                "set_type": "題組題",
                "subject_filter": ["公民與社會"],
                "learning_content": ["公Aa-Ⅳ-1", "公Ab-Ⅳ-1"],
            }
        )

    assert exc_info.value.errors == [
        {"field": "learning_content", "code": "no_admitting_parent", "parent": "內容領域"}
    ]


def test_resolve_batch_prefixes_no_admitting_parent_errors_per_row() -> None:
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "count": 2,
                "seed": 1,
                "grade": 8,
                "context": ["個人"],
                "set_type": "題組題",
                "content_type": "純文字",
                "target_surface": "紙本",
                "core_competency": ["社-J-A1"],
                "per_question_params": [
                    {
                        "subject_filter": ["公民與社會"],
                        "learning_content": ["公Aa-Ⅳ-1", "公Ab-Ⅳ-1"],
                    },
                    {
                        "subject_filter": ["歷史", "地理"],
                        "learning_content": ["公Bj-Ⅳ-1"],
                    },
                ],
            }
        )

    assert exc_info.value.errors == [
        {
            "field": "per_question_params[0].learning_content",
            "code": "no_admitting_parent",
            "parent": "內容領域",
        }
    ]


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


def test_resolve_parent_edit_clears_and_redraws_invalid_natural_child() -> None:
    result = resolve(
        {
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
        },
        redraws={"情境": 1},
    )

    assert result.payload["sub_context"] == "Management of pollution and air quality"
    assert result.drawn == ["情境子類別"]
    assert result.cleared == ["情境子類別"]


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


def test_resolve_parent_edit_clears_and_redraws_incompatible_civic_learning_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.social_studies import sampler

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
                        "科目": ["公民與社會"],
                        "內容領域": ["Civic Principles"],
                    },
                },
                {
                    "學習階段": "第四學習階段",
                    "科目": "公",
                    "value": "公Synthetic-Ⅳ-2",
                    "admitted_by": {
                        "科目": ["公民與社會"],
                        "內容領域": ["Civic Participation"],
                    },
                },
            ]
        },
    )
    monkeypatch.setattr(
        sampler,
        "_LP_DATA",
        {
            "學習表現": [
                {
                    "學習階段": "第四學習階段",
                    "科目": "社",
                    "value": "社1a-Ⅳ-1",
                    "admitted_by": {"科目": ["歷史", "地理", "公民與社會", "跨科"]},
                }
            ]
        },
    )

    result = resolve(
        {
            "subject": "social_studies",
            "seed": 23,
            "grade": 8,
            "context": ["個人"],
            "set_type": "題組題",
            "subject_filter": ["公民與社會"],
            "content_domain": "Civic Participation",
            "learning_content": ["公Synthetic-Ⅳ-1"],
            "learning_performance": ["社1a-Ⅳ-1"],
        },
        redraws={"內容領域": 1},
    )

    assert result.payload["learning_content"] == ["公Synthetic-Ⅳ-2"]
    assert result.cleared == ["學習內容"]
    assert "學習內容" in result.drawn


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


# ── #836: 各小題配置 學習內容/學習表現 narrow and are checked like ────────
# ── 題組-level codes, for rows within the resolved 小題數 ──────────────────


def test_resolve_row_content_pin_narrows_and_re_resolves_unchanged_across_seeds() -> None:
    for seed in range(200):
        payload = {
            "subject": "social_studies",
            "seed": seed,
            "grade": 8,
            "context": ["個人"],
            "set_type": "題組題",
            "content_type": "純文字",
            "target_surface": "紙本",
            "core_competency": ["社-J-A1"],
            "sub_question_count": 3,
            "subquestion_configs": [{}, {"learning_content": ["公Aa-Ⅳ-1"]}, {}],
        }

        first = resolve(payload)

        assert first.payload["subject_filter"][0] in {"公民與社會", "跨科"}
        assert first.payload["content_domain"] == "Civic Roles and Identities"
        assert (
            first.payload["subquestion_configs"][1]["learning_content"] == ["公Aa-Ⅳ-1"]
        )

        second = resolve(first.payload)

        assert second.payload == first.payload
        assert second.drawn == []
        assert second.cleared == []


def test_resolve_row_beyond_resolved_count_narrows_nothing() -> None:
    base = {
        "subject": "social_studies",
        "seed": 7,
        "grade": 8,
        "context": ["個人"],
        "set_type": "題組題",
        "content_type": "純文字",
        "target_surface": "紙本",
        "core_competency": ["社-J-A1"],
        "sub_question_count": 3,
    }

    with_row = resolve(
        {
            **base,
            "subquestion_configs": [
                {},
                {},
                {},
                {},
                {"learning_content": ["公Aa-Ⅳ-1"]},
            ],
        }
    )
    without_row = resolve({**base, "subquestion_configs": [{}, {}, {}]})

    assert with_row.payload["subject_filter"] == without_row.payload["subject_filter"]
    assert with_row.payload["content_domain"] == without_row.payload["content_domain"]


def test_resolve_reports_both_row_pins_in_an_empty_domain_conflict() -> None:
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "seed": 1,
                "grade": 8,
                "context": ["個人"],
                "set_type": "題組題",
                "subject_filter": ["公民與社會"],
                "sub_question_count": 3,
                "subquestion_configs": [
                    {"learning_content": ["公Aa-Ⅳ-1"]},
                    {"learning_content": ["公Bn-Ⅳ-3"]},
                    {},
                ],
            }
        )

    assert exc_info.value.errors == [
        {
            "field": "subquestion_configs[0].learning_content",
            "code": "no_admitting_parent",
            "parent": "內容領域",
        },
        {
            "field": "subquestion_configs[1].learning_content",
            "code": "no_admitting_parent",
            "parent": "內容領域",
        },
    ]


def test_resolve_reports_question_level_and_row_pin_in_a_mixed_domain_conflict() -> None:
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "seed": 1,
                "grade": 8,
                "context": ["個人"],
                "set_type": "題組題",
                "subject_filter": ["公民與社會"],
                "learning_content": ["公Bn-Ⅳ-3"],
                "sub_question_count": 3,
                "subquestion_configs": [{"learning_content": ["公Aa-Ⅳ-1"]}, {}, {}],
            }
        )

    assert exc_info.value.errors == [
        {"field": "learning_content", "code": "no_admitting_parent", "parent": "內容領域"},
        {
            "field": "subquestion_configs[0].learning_content",
            "code": "no_admitting_parent",
            "parent": "內容領域",
        },
    ]


def test_resolve_row_performance_pin_rejects_incompatible_pinned_subject() -> None:
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "seed": 1,
                "grade": 8,
                "context": ["個人"],
                "set_type": "題組題",
                "subject_filter": ["地理"],
                "sub_question_count": 3,
                "subquestion_configs": [
                    {"learning_performance": ["公1c-Ⅳ-1"]},
                    {},
                    {},
                ],
            }
        )

    assert exc_info.value.errors == [
        {
            "field": "subquestion_configs[0].learning_performance",
            "code": "incompatible_parent",
            "parent": "地理",
        }
    ]


def test_resolve_batch_row_pin_incompatible_with_pinned_domain_is_prefixed() -> None:
    """#836 acceptance: a second question's own row 學習內容 pin, incompatible

    with that question's pinned 內容領域, is rejected with the full nested
    batch + slot path (per_question_params[i].subquestion_configs[j].<field>).
    """
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "count": 2,
                "seed": 1,
                "grade": 8,
                "context": ["個人"],
                "set_type": "題組題",
                "content_type": "純文字",
                "target_surface": "紙本",
                "core_competency": ["社-J-A1"],
                "per_question_params": [
                    {"subject_filter": ["歷史"]},
                    {
                        "subject_filter": ["公民與社會"],
                        "content_domain": "Civic Participation",
                        "sub_question_count": 3,
                        "subquestion_configs": [
                            {"learning_content": ["公Bn-Ⅳ-3"]},
                            {},
                            {},
                        ],
                    },
                ],
            }
        )

    assert exc_info.value.errors == [
        {
            "field": "per_question_params[1].subquestion_configs[0].learning_content",
            "code": "incompatible_parent",
            "parent": "Civic Participation",
        }
    ]


# ── #837: editing 科目 or 內容領域 on 發送前確認 clears 釘選 codes ─────────
# ── that no longer fit, instead of rejecting ──────────────────────────────


def test_resolve_subject_edit_clears_incompatible_content_survives_compatible_performance() -> (
    None
):
    """Acceptance bullet 1 + "compatible children survive": editing 科目 from

    公民與社會 to 地理 with a 科目 重抽 counter clears the now-incompatible
    公Bj-Ⅳ-1 學習內容 pin and redraws it from 地理's admitted pool, while the
    compatible 社1a-Ⅳ-1 學習表現 pin (admitted by every subject) survives
    untouched and is never listed in ``cleared``.
    """
    result = resolve(
        {
            "subject": "social_studies",
            "seed": 11,
            "grade": 7,
            "context": ["個人"],
            "set_type": "題組題",
            "content_type": "純文字",
            "target_surface": "紙本",
            "core_competency": ["社-J-A1"],
            "subject_filter": ["地理"],
            "learning_content": ["公Bj-Ⅳ-1"],
            "learning_performance": ["社1a-Ⅳ-1"],
        },
        redraws={"科目": 1},
    )

    assert result.payload["subject_filter"] == ["地理"]
    assert "公Bj-Ⅳ-1" not in result.payload["learning_content"]
    assert result.payload["learning_content"]
    assert result.payload["learning_performance"] == ["社1a-Ⅳ-1"]
    assert result.cleared == ["學習內容"]
    assert "學習內容" in result.drawn
    assert "學習表現" not in result.drawn

    # The result re-resolves unchanged (equivalent to generation's HTTP gate
    # accepting it: that gate is itself a resolve() call requiring drawn == []
    # — see the Task 3 design note).
    second = resolve(result.payload)
    assert second.payload == result.payload
    assert second.drawn == []
    assert second.cleared == []


def test_resolve_subject_edit_without_a_redraw_counter_still_rejects() -> None:
    """Acceptance bullet 6, 科目 variant: without a 科目 重抽 counter the same

    incompatible payload from the previous test is still rejected, unchanged
    from pre-#837 behavior.
    """
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "seed": 11,
                "grade": 7,
                "context": ["個人"],
                "set_type": "題組題",
                "content_type": "純文字",
                "target_surface": "紙本",
                "core_competency": ["社-J-A1"],
                "subject_filter": ["地理"],
                "learning_content": ["公Bj-Ⅳ-1"],
                "learning_performance": ["社1a-Ⅳ-1"],
            }
        )

    assert exc_info.value.errors == [
        {"field": "learning_content", "code": "incompatible_parent", "parent": "地理"}
    ]


def test_resolve_subject_edit_clears_question_and_row_level_performance_and_row_content() -> (
    None
):
    """Acceptance bullet 2: a 科目 edit clears incompatible 學習表現 at both

    question level and in a 各小題配置 row, and incompatible 學習內容 in a
    different row, while a compatible row 學習表現 pin survives.
    """
    result = resolve(
        {
            "subject": "social_studies",
            "seed": 13,
            "grade": 7,
            "context": ["個人"],
            "set_type": "題組題",
            "content_type": "純文字",
            "target_surface": "紙本",
            "core_competency": ["社-J-A1"],
            "subject_filter": ["地理"],
            "learning_performance": ["公1c-Ⅳ-1"],
            "sub_question_count": 3,
            "subquestion_configs": [
                {"learning_content": ["公Bj-Ⅳ-1"]},
                {"learning_performance": ["社1a-Ⅳ-1"]},
                {},
            ],
        },
        redraws={"科目": 1},
    )

    assert result.cleared == [
        "學習表現",
        "subquestion_configs[0].learning_content",
    ]
    assert "公1c-Ⅳ-1" not in result.payload["learning_performance"]
    assert "公Bj-Ⅳ-1" not in result.payload["subquestion_configs"][0]["learning_content"]
    assert result.payload["subquestion_configs"][1]["learning_performance"] == [
        "社1a-Ⅳ-1"
    ]
    assert "學習表現" in result.drawn
    assert "subquestion_configs[0].learning_content" in result.drawn
    assert "subquestion_configs[1].learning_performance" not in result.drawn

    second = resolve(result.payload)
    assert second.payload == result.payload
    assert second.drawn == []
    assert second.cleared == []


def test_resolve_domain_edit_clears_question_and_row_level_content_but_not_performance() -> (
    None
):
    """Acceptance bullet 3: a 內容領域 edit clears incompatible 學習內容 at

    question level and in a 各小題配置 row, and never touches 學習表現 (which
    has no 內容領域 parent), so it is neither cleared nor redrawn.
    """
    result = resolve(
        {
            "subject": "social_studies",
            "seed": 17,
            "grade": 7,
            "context": ["個人"],
            "set_type": "題組題",
            "content_type": "純文字",
            "target_surface": "紙本",
            "core_competency": ["社-J-A1"],
            "subject_filter": ["公民與社會"],
            "content_domain": "Civic Participation",
            "learning_content": ["公Bn-Ⅳ-3"],
            "learning_performance": ["社1a-Ⅳ-1"],
            "sub_question_count": 3,
            "subquestion_configs": [
                {"learning_content": ["公Bj-Ⅳ-1"]},
                {},
                {},
            ],
        },
        redraws={"內容領域": 1},
    )

    assert result.cleared == [
        "學習內容",
        "subquestion_configs[0].learning_content",
    ]
    assert "學習表現" not in result.cleared
    assert "公Bn-Ⅳ-3" not in result.payload["learning_content"]
    assert (
        "公Bj-Ⅳ-1" not in result.payload["subquestion_configs"][0]["learning_content"]
    )
    assert result.payload["learning_performance"] == ["社1a-Ⅳ-1"]
    assert result.payload["content_domain"] == "Civic Participation"
    assert "學習表現" not in result.drawn

    second = resolve(result.payload)
    assert second.payload == result.payload
    assert second.drawn == []
    assert second.cleared == []


def test_resolve_domain_edit_without_a_redraw_counter_still_rejects_both_levels() -> None:
    """Acceptance bullet 6, 內容領域 variant, with both a question-level and a

    row-level offending field reported (mirrors the previous test's payload).
    """
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "seed": 17,
                "grade": 7,
                "context": ["個人"],
                "set_type": "題組題",
                "content_type": "純文字",
                "target_surface": "紙本",
                "core_competency": ["社-J-A1"],
                "subject_filter": ["公民與社會"],
                "content_domain": "Civic Participation",
                "learning_content": ["公Bn-Ⅳ-3"],
                "learning_performance": ["社1a-Ⅳ-1"],
                "sub_question_count": 3,
                "subquestion_configs": [
                    {"learning_content": ["公Bj-Ⅳ-1"]},
                    {},
                    {},
                ],
            }
        )

    assert exc_info.value.errors == [
        {
            "field": "learning_content",
            "code": "incompatible_parent",
            "parent": "Civic Participation",
        },
        {
            "field": "subquestion_configs[0].learning_content",
            "code": "incompatible_parent",
            "parent": "Civic Participation",
        },
    ]


def test_resolve_batch_content_domain_alias_matches_the_canonical_redraw_key() -> None:
    """Acceptance bullet 5: the request alias ``content_domain`` behaves

    identically to the canonical ``內容領域`` redraw key, including with a
    batch prefix.
    """

    def make_payload() -> dict:
        return {
            "subject": "social_studies",
            "seed": 5,
            "grade": 7,
            "context": ["個人"],
            "set_type": "題組題",
            "content_type": "純文字",
            "target_surface": "紙本",
            "core_competency": ["社-J-A1"],
            "learning_performance": ["社1a-Ⅳ-1"],
            "per_question_params": [
                {
                    "subject_filter": ["公民與社會"],
                    "content_domain": "Civic Participation",
                    "learning_content": ["公Bn-Ⅳ-3"],
                }
            ],
        }

    via_alias = resolve(
        make_payload(), redraws={"per_question_params[0].content_domain": 1}
    )
    via_canonical = resolve(
        make_payload(), redraws={"per_question_params[0].內容領域": 1}
    )

    assert via_alias.payload == via_canonical.payload
    assert (
        via_alias.cleared
        == via_canonical.cleared
        == ["per_question_params[0].學習內容"]
    )


def test_resolve_row_domain_conflict_clears_and_redraws_across_a_civic_edit() -> None:
    """Regression (coordinator finding on Task 3's review): a 內容領域 edit

    whose only 釘選 conflict lives in a 各小題配置 row (not the question-level
    ``learning_content``) must clear that row's field, not crash with an
    unhandled ``IncompatibleContentDomainError``. Live-reproduced payload:
    civic 科目, ``content_domain`` edited to ``Civic Participation`` with a
    single row pinning ``公Bn-Ⅳ-3`` (admitted only by "Civic Institutions and
    Systems").
    """
    result = resolve(
        {
            "subject": "social_studies",
            "subject_filter": ["公民與社會"],
            "content_domain": "Civic Participation",
            "subquestion_configs": [
                {"learning_content": ["公Bn-Ⅳ-3"]},
                {},
                {},
            ],
            "sub_question_count": 3,
            "grade": 7,
            "context": ["個人"],
            "set_type": "題組題",
            "content_type": "純文字",
            "target_surface": "紙本",
            "core_competency": ["社-J-A1"],
            "seed": 19,
        },
        redraws={"內容領域": 1},
    )

    assert result.cleared == ["subquestion_configs[0].learning_content"]
    assert (
        "公Bn-Ⅳ-3" not in result.payload["subquestion_configs"][0]["learning_content"]
    )
    assert result.payload["subquestion_configs"][0]["learning_content"]
    assert "subquestion_configs[0].learning_content" in result.drawn

    second = resolve(result.payload)
    assert second.payload == result.payload
    assert second.drawn == []
    assert second.cleared == []


def test_resolve_row_domain_conflict_without_a_redraw_counter_still_rejects() -> None:
    """Same regression payload, without the 重抽 counter: must raise

    ``ResolveConflictError`` naming the row path — no ``ParentAdmissionError``
    (or any other sampler exception) may escape ``resolve()``.
    """
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(
            {
                "subject": "social_studies",
                "subject_filter": ["公民與社會"],
                "content_domain": "Civic Participation",
                "subquestion_configs": [
                    {"learning_content": ["公Bn-Ⅳ-3"]},
                    {},
                    {},
                ],
                "sub_question_count": 3,
                "grade": 7,
                "context": ["個人"],
                "set_type": "題組題",
                "content_type": "純文字",
                "target_surface": "紙本",
                "core_competency": ["社-J-A1"],
                "seed": 19,
            }
        )

    assert exc_info.value.errors == [
        {
            "field": "subquestion_configs[0].learning_content",
            "code": "incompatible_parent",
            "parent": "Civic Participation",
        }
    ]


# ── #837 regression: chained clearing across two rounds in one resolve() ──


def _chained_clearing_payload() -> dict:
    """Needs two clearing rounds in one ``resolve()`` call.

    ``subject_filter=["公民與社會"]`` is pinned single-valued, and the
    request-level ``learning_content=["地Aa-Ⅳ-1"]`` pin (admitted only by
    歷史/跨科) is incompatible with it — a first-round 科目 conflict. Clearing
    it (a 科目 重抽 counter > 0) drops the top-level 學習內容 pin and
    resamples, which then surfaces a second, independent conflict: the
    pinned ``content_domain="Civic Participation"`` does not admit the
    row-0 ``公Bj-Ⅳ-1`` pin (admitted only by "Civic Institutions and
    Systems") — a 內容領域 conflict that only a second round can clear.
    Verified interactively against ``src/common/admission.py`` before
    writing this fixture (see the fix-wave report for the exact payload).
    """
    return {
        "subject": "social_studies",
        "seed": 23,
        "grade": 7,
        "context": ["個人"],
        "set_type": "題組題",
        "content_type": "純文字",
        "target_surface": "紙本",
        "core_competency": ["社-J-A1"],
        "subject_filter": ["公民與社會"],
        "content_domain": "Civic Participation",
        "learning_content": ["地Aa-Ⅳ-1"],
        "learning_performance": ["社1a-Ⅳ-1"],
        "sub_question_count": 3,
        "subquestion_configs": [
            {"learning_content": ["公Bj-Ⅳ-1"]},
            {},
            {},
        ],
    }


def test_resolve_chains_a_subject_clear_into_a_domain_clear_in_one_call() -> None:
    """Both counters set: the 科目 conflict clears first, the resample's

    fresh 內容領域 conflict clears second, and the fully-resolved payload
    re-resolves identically (idempotent, per the resolver's own contract).
    """
    result = resolve(_chained_clearing_payload(), redraws={"科目": 1, "內容領域": 1})

    assert result.cleared == ["學習內容", "subquestion_configs[0].learning_content"]
    assert "地Aa-Ⅳ-1" not in (result.payload["learning_content"] or [])
    assert result.payload["learning_content"]
    row0 = result.payload["subquestion_configs"][0]
    assert "公Bj-Ⅳ-1" not in (row0.get("learning_content") or [])
    assert row0["learning_content"]

    second = resolve(result.payload)
    assert second.payload == result.payload
    assert second.drawn == []
    assert second.cleared == []


def test_resolve_chained_clearing_with_only_the_subject_counter_still_rejects() -> None:
    """Only the 科目 counter is set: the first round clears fine, but the

    surfaced 內容領域 conflict has no counter to clear it, so ``resolve()``
    raises ``ResolveConflictError`` naming that second conflict (never the
    already-cleared first one).
    """
    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(_chained_clearing_payload(), redraws={"科目": 1})

    assert exc_info.value.errors == [
        {
            "field": "subquestion_configs[0].learning_content",
            "code": "incompatible_parent",
            "parent": "Civic Participation",
        }
    ]


def test_resolve_exhausted_clear_rounds_raises_resolve_conflict_not_parent_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the bounded clearing loop is exhausted before converging,

    ``resolve()`` must still raise ``ResolveConflictError`` — never let the
    sampler's internal ``ParentAdmissionError`` escape unconverted.
    """
    from src.common import resolver as resolver_module

    monkeypatch.setattr(resolver_module, "_MAX_ADMISSION_CLEAR_ROUNDS", 1)

    with pytest.raises(ResolveConflictError) as exc_info:
        resolve(_chained_clearing_payload(), redraws={"科目": 1, "內容領域": 1})

    assert exc_info.value.errors == [
        {
            "field": "subquestion_configs[0].learning_content",
            "code": "incompatible_parent",
            "parent": "Civic Participation",
        }
    ]
