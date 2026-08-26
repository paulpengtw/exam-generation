"""NS sampler regression tests: grade-aware stage, determinism, validity (issue #91)."""

from __future__ import annotations

import pytest

from src.natural_sciences.curriculum_loader import (
    load_learning_content,
    load_learning_performance,
)
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schemas import QuestionContext, QuestionSubContext


def test_sample_params_never_replaces_explicit_sub_context() -> None:
    submitted = QuestionSubContext("Maintenance of health")

    sampled = sample_params(
        context=[QuestionContext("Global")],
        sub_context=submitted,
        seed=42,
    )

    assert sampled.情境子類別 is submitted


def test_sample_params_constrains_context_to_explicit_sub_context_parent() -> None:
    submitted = QuestionSubContext("Maintenance of health")

    sampled = sample_params(sub_context=submitted, seed=42)

    assert sampled.情境 == [QuestionContext("Personal")]
    assert sampled.情境子類別 is submitted


def test_single_admitted_parent_does_not_consume_seeded_rng() -> None:
    sub_context = QuestionSubContext("Maintenance of health")

    sampled = sample_params(
        grade=12,
        sub_context=sub_context,
        seed=42,
    )
    pinned = sample_params(
        grade=12,
        context=[QuestionContext("Personal")],
        sub_context=sub_context,
        seed=42,
    )

    assert sampled.model_dump() == pinned.model_dump()


def test_matching_subcontexts_accepts_any_admitted_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.natural_sciences import sampler

    monkeypatch.setitem(
        sampler._SUB_CONTEXT_ADMITTED_BY,
        "Maintenance of health",
        ["Personal", "Global"],
    )

    assert QuestionSubContext("Maintenance of health") in sampler._matching_subcontexts({"Global"})


def test_multi_admitted_parent_uses_keyed_context_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.natural_sciences import sampler

    monkeypatch.setitem(
        sampler._SUB_CONTEXT_ADMITTED_BY,
        "Maintenance of health",
        ["Personal", "Global"],
    )
    sub_context = QuestionSubContext("Maintenance of health")

    first = sample_params(sub_context=sub_context, seed=42)
    second = sample_params(sub_context=sub_context, seed=42)
    pinned = sample_params(
        context=first.情境,
        sub_context=sub_context,
        seed=42,
    )

    assert first.情境 == second.情境
    assert first.題型 == pinned.題型


def test_sample_params_grade_derives_stage_pools():
    """Grades 7-9 draw 第四學習階段 codes; grades 10-12 draw 第五學習階段 codes."""
    lc_stage = {e["value"]: e["學習階段"] for e in load_learning_content()["學習內容"]}
    lp_stage = {e["value"]: e["學習階段"] for e in load_learning_performance()["學習表現"]}
    cases = (
        (7, "第四學習階段"),
        (9, "第四學習階段"),
        (10, "第五學習階段"),
        (12, "第五學習階段"),
    )
    for grade, expected_stage in cases:
        p = sample_params(grade=grade, seed=42)
        assert p.學習內容_pool, f"grade={grade}: empty 學習內容_pool"
        assert p.學習表現_pool, f"grade={grade}: empty 學習表現_pool"
        for code in p.學習內容_pool:
            assert lc_stage[code] == expected_stage, (
                f"grade={grade}: 學習內容 {code} is {lc_stage[code]}, expected {expected_stage}"
            )
        for code in p.學習表現_pool:
            assert lp_stage[code] == expected_stage, (
                f"grade={grade}: 學習表現 {code} is {lp_stage[code]}, expected {expected_stage}"
            )


def test_sample_params_seeded_deterministic():
    """Mirror of tests/test_math_sampler.py::test_sample_params_seeded_deterministic."""
    p1 = sample_params(seed=42)
    p2 = sample_params(seed=42)
    assert p1.grade == p2.grade
    assert [c.value for c in p1.情境] == [c.value for c in p2.情境]
    assert p1.情境子類別.value == p2.情境子類別.value
    assert p1.題型.value == p2.題型.value
    assert [c.value for c in p1.科學能力] == [c.value for c in p2.科學能力]
    assert p1.題目內容類型 == p2.題目內容類型
    assert p1.學習內容_pool == p2.學習內容_pool
    assert p1.學習表現_pool == p2.學習表現_pool


def test_pinning_natural_sciences_content_type_does_not_shift_other_seeded_draws():
    baseline = sample_params(seed=0, sub_question_count=3)
    pinned = sample_params(seed=0, sub_question_count=3, content_type="純文字")

    assert pinned.題目內容類型 == "純文字"
    baseline_payload = baseline.model_dump()
    pinned_payload = pinned.model_dump()
    baseline_payload.pop("題目內容類型")
    pinned_payload.pop("題目內容類型")
    assert pinned_payload == baseline_payload


def test_natural_sciences_slot_redraw_uses_its_indexed_reporting_scale_stream():
    configs = [SubQuestionConfig(), SubQuestionConfig(), SubQuestionConfig()]
    baseline = sample_params(seed=17, sub_question_count=3, subquestion_configs=configs)
    redrawn = sample_params(
        seed=17,
        sub_question_count=3,
        subquestion_configs=configs,
        redraws={"subquestion_configs[2].reporting_scale": 1},
    )
    replay = sample_params(
        seed=17,
        sub_question_count=3,
        subquestion_configs=configs,
        redraws={"subquestion_configs[2].reporting_scale": 1},
    )

    assert redrawn.subquestion_configs[2].reporting_scale != (
        baseline.subquestion_configs[2].reporting_scale
    )
    assert redrawn.subquestion_configs[:2] == baseline.subquestion_configs[:2]
    baseline_payload = baseline.model_dump()
    redrawn_payload = redrawn.model_dump()
    baseline_payload["subquestion_configs"][2]["reporting_scale"] = None
    redrawn_payload["subquestion_configs"][2]["reporting_scale"] = None
    assert redrawn_payload == baseline_payload
    assert replay.model_dump_json() == redrawn.model_dump_json()


def test_pinning_one_natural_sciences_slot_does_not_shift_other_slot_draws():
    baseline = sample_params(
        seed=0,
        sub_question_count=3,
        subquestion_configs=[{}, {}, {}],
    )
    pinned = sample_params(
        seed=0,
        sub_question_count=3,
        subquestion_configs=[{"question_type": "Complex multiple-choice"}, {}, {}],
    )

    assert pinned.subquestion_configs[0].question_type.value == "Complex multiple-choice"
    assert pinned.subquestion_configs[1:] == baseline.subquestion_configs[1:]


def test_sample_params_identical_across_repeats_many_seeds():
    for seed in range(20):
        assert sample_params(seed=seed).model_dump() == sample_params(seed=seed).model_dump()


def test_sampled_learning_performance_codes_exist_in_curriculum():
    """Issue #91: every sampled 學習表現 code exists in learning_performance.json."""
    lp_values = {e["value"] for e in load_learning_performance()["學習表現"]}
    for seed in range(30):
        p = sample_params(seed=seed)
        assert p.學習表現_pool, f"seed={seed}: empty 學習表現_pool"
        for code in p.學習表現_pool:
            assert code in lp_values, (
                f"seed={seed}: 學習表現 {code} not in learning_performance.json"
            )


def test_sampled_learning_content_codes_exist_in_curriculum():
    """Issue #91: every sampled 學習內容 code exists in learning_content.json."""
    lc_values = {e["value"] for e in load_learning_content()["學習內容"]}
    for seed in range(30):
        p = sample_params(seed=seed)
        assert p.學習內容_pool, f"seed={seed}: empty 學習內容_pool"
        for code in p.學習內容_pool:
            assert code in lc_values, f"seed={seed}: 學習內容 {code} not in learning_content.json"


def test_sample_params_unknown_grade_raises():
    """Mirror of tests/test_math_sampler.py::test_sample_params_unknown_grade_raises."""
    with pytest.raises(ValueError):
        sample_params(grade=99, seed=0)


# ── Issue #279: 題組-level Reporting Scale inheritance ────────────────────────

from src.natural_sciences.schemas import SubQuestionConfig  # noqa: E402


def test_reporting_scale_request_level_propagates_to_all_subquestions() -> None:
    """Slice 1: request naming level '4' → all three 小題 resolve to '4'."""
    p = sample_params(
        seed=1,
        reporting_scale="4",
        sub_question_count=3,
    )
    assert [cfg.reporting_scale for cfg in p.subquestion_configs] == ["4", "4", "4"]


def test_reporting_scale_explicit_per_subquestion_wins_over_request_level() -> None:
    """Slice 2: per-小題 explicit value wins; blank siblings inherit 題組-level."""
    configs = [
        SubQuestionConfig(reporting_scale="6"),
        SubQuestionConfig(),
        SubQuestionConfig(),
    ]
    p = sample_params(
        seed=1,
        reporting_scale="4",
        sub_question_count=3,
        subquestion_configs=configs,
    )
    assert p.subquestion_configs[0].reporting_scale == "6"
    assert p.subquestion_configs[1].reporting_scale == "4"
    assert p.subquestion_configs[2].reporting_scale == "4"


def test_reporting_scale_absent_uses_independent_rng_scatter() -> None:
    """Slice 3: no 題組-level → each slot draws its own keyed scale stream.

    Literal expected values for keyed streams:
        sample_params(seed=99, sub_question_count=3, subquestion_configs=[3×empty])
        → ['5', '3', '4']
    """
    configs = [SubQuestionConfig(), SubQuestionConfig(), SubQuestionConfig()]
    p = sample_params(seed=99, sub_question_count=3, subquestion_configs=configs)
    assert [cfg.reporting_scale for cfg in p.subquestion_configs] == ["5", "3", "4"]
