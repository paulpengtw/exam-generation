"""Social studies sampler fixed-learning-stage regression tests (issue #192)."""

from __future__ import annotations

from collections import Counter

from src.social_studies import sampler
from src.social_studies.curriculum_loader import load_learning_performance
from src.social_studies.schema_loader import load_grades, load_learning_stage, load_schemas
from src.social_studies.schemas import QuestionSubject


def test_sample_params_uses_module_learning_stage_for_every_legal_grade(monkeypatch) -> None:
    schemas = load_schemas()
    assert sampler._LEARNING_STAGE == load_learning_stage(schemas)
    grades = load_grades(schemas)
    assert grades == [7, 8, 9]

    module_stage = "第二學習階段"
    grade_stage = "第四學習階段"
    learning_content = {
        "學習內容": [
            {"value": "歷Test-Ⅱ-1", "學習階段": module_stage, "科目": "歷"},
            {"value": "歷Test-Ⅳ-1", "學習階段": grade_stage, "科目": "歷"},
        ]
    }
    learning_performance = {
        "學習表現": [
            {"value": "歷Test-Ⅱ-1", "學習階段": module_stage, "科目": "歷"},
            {"value": "歷Test-Ⅳ-1", "學習階段": grade_stage, "科目": "歷"},
        ]
    }
    content_stages = {row["value"]: row["學習階段"] for row in learning_content["學習內容"]}
    performance_stages = {
        row["value"]: row["學習階段"] for row in learning_performance["學習表現"]
    }
    monkeypatch.setattr(sampler, "_LEARNING_STAGE", module_stage)
    monkeypatch.setattr(sampler, "_LC_DATA", learning_content)
    monkeypatch.setattr(sampler, "_LP_DATA", learning_performance)

    for grade in grades:
        params = sampler.sample_params(
            grade=grade,
            subject=[QuestionSubject("歷史")],
            seed=42,
        )

        assert params.grade == grade
        assert {content_stages[code] for code in params.學習內容_pool} == {module_stage}, (
            f"grade={grade}: 學習內容_pool did not use the module-level 學習階段"
        )
        assert {performance_stages[code] for code in params.學習表現_pool} == {module_stage}, (
            f"grade={grade}: 學習表現_pool did not use the module-level 學習階段"
        )


def test_shipped_learning_performance_only_covers_fixed_schema_stage() -> None:
    schema_stage = load_learning_stage(load_schemas())
    entries = load_learning_performance()["學習表現"]

    # If this guard fails, read README "Natural sciences vs social studies differences"
    # and issue #192. Revisit the fixed-stage decision; do not just update this expectation.
    assert Counter(entry["學習階段"] for entry in entries) == Counter({schema_stage: 26})
