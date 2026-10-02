"""NS _parse_subquestion must force 年級 from sampled params (issue #286).

The LLM's own 年級 emission is ignored — the parser stamps params.grade
onto every sub-question, matching how 科目 is already forced to
["自然科學"].

Reproduction from issue #286: sample_params(grade=11, seed=7); raw 子題
carries 年級=8 (the prompt's hard-coded example value) → output must be
年級=11.
"""

from __future__ import annotations

import pytest

from src.common.generation_core import SubquestionParseError
from src.natural_sciences.cli import _parse_subquestion
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schemas import ScienceCompetency


def _params(grade: int = 11, q_type: str = "Simple multiple-choice"):
    return sample_params(
        grade=grade,
        seed=7,
        q_type=[q_type],
        learning_content=["Ab-Ⅳ-1"],
        learning_performance=["tr-Ⅳ-1"],
    )


def _base_raw(year_grade: int | None = 8) -> dict:
    """Return a minimal valid raw 子題 dict.

    *year_grade* is what the LLM emitted for 年級; pass ``None`` to omit
    the field entirely.
    """
    raw: dict = {
        "序號": 1,
        "題型": "Simple multiple-choice",
        "題目": "Q? (A) 甲 (B) 乙 (C) 丙 (D) 丁",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": "光合作用",
        "科目": ["自然科學"],
        "學習內容": [{"編碼": "Ab-Ⅳ-1", "說明": "粒子模型"}],
        "學習表現": [{"編碼": "tr-Ⅳ-1", "說明": "探究"}],
    }
    if year_grade is not None:
        raw["年級"] = year_grade
    return raw


# ---------------------------------------------------------------------------
# Core acceptance-criteria tests
# ---------------------------------------------------------------------------


def test_parse_subquestion_forces_grade_over_llm_value():
    """Raw 子題 with 年級=8 must parse to 年級=11 when params.grade=11.

    This is the exact reproduction scenario from issue #286:
    sample_params(grade=11, seed=7); raw carries the prompt's example 年級=8.
    """
    raw = _base_raw(year_grade=8)  # LLM hallucinated / prompt-hardcoded grade 8
    params = _params(grade=11)
    sq = _parse_subquestion(raw, "q1", params, 1)
    assert sq is not None
    assert sq.年級 == 11, (
        f"expected 年級=11 (requested grade), got 年級={sq.年級}"
    )


def test_parse_subquestion_forces_grade_when_omitted():
    """A raw 子題 that omits 年級 must still receive params.grade."""
    raw = _base_raw(year_grade=None)  # field absent
    params = _params(grade=10)
    sq = _parse_subquestion(raw, "q1", params, 1)
    assert sq is not None
    assert sq.年級 == 10, (
        f"expected 年級=10 (requested grade), got 年級={sq.年級}"
    )


@pytest.mark.parametrize(
    "q_type,題目,答案,rubric",
    [
        (
            "Simple multiple-choice",
            "Q? (A) 甲 (B) 乙 (C) 丙 (D) 丁",
            "A",
            [],
        ),
        (
            "Complex multiple-choice",
            "請逐項判斷是非：(1)…… (2)……",
            "(1)是 (2)非",
            [],
        ),
        (
            "Constructed response",
            "請解釋光合作用為何需要光。",
            "光反應需要光能供應電子傳遞……",
            [{"code": "2", "規準說明": "完整解釋", "學生作答實例": ["…"]}],
        ),
    ],
    ids=["simple-mc", "complex-mc", "constructed-response"],
)
def test_parse_subquestion_grade_forced_for_all_pisa_types(
    q_type: str,
    題目: str,
    答案: str,
    rubric: list,
) -> None:
    """Grade forcing applies identically across all three PISA 題型 families."""
    raw = _base_raw(year_grade=8)
    raw["題型"] = q_type
    raw["題目"] = 題目
    raw["答案"] = 答案
    raw["評分規準"] = rubric
    params = _params(grade=11, q_type=q_type)
    sq = _parse_subquestion(raw, "q1", params, 1)
    assert sq is not None, f"_parse_subquestion returned None for {q_type}"
    assert sq.年級 == 11, (
        f"{q_type}: expected 年級=11, got 年級={sq.年級}"
    )


def test_parse_subquestion_normalizes_scalar_student_example() -> None:
    raw = _base_raw()
    raw["題型"] = "Constructed response"
    raw["評分規準"] = [
        {"code": "2", "規準說明": "完整說明", "學生作答實例": "學生回答"}
    ]

    sq = _parse_subquestion(
        raw,
        "q1",
        _params(q_type="Constructed response"),
        1,
    )

    assert sq.評分規準[0].學生作答實例 == ["學生回答"]


@pytest.mark.parametrize("invalid", [7, {"private": "response"}])
def test_parse_subquestion_rejects_non_string_scalar_student_example(
    invalid: object,
) -> None:
    raw = _base_raw()
    raw["題型"] = "Constructed response"
    raw["評分規準"] = [
        {"code": "2", "規準說明": "完整說明", "學生作答實例": invalid}
    ]

    with pytest.raises(SubquestionParseError):
        _parse_subquestion(
            raw,
            "q1",
            _params(q_type="Constructed response"),
            1,
        )


def test_parse_subquestion_forces_competency_and_configured_curriculum_pins() -> None:
    competency = list(ScienceCompetency)[1]
    params = sample_params(
        grade=11,
        seed=7,
        q_type=["Simple multiple-choice"],
        science_competency=[competency],
        learning_content=["Ab-Ⅳ-1"],
        learning_performance=["tr-Ⅳ-1"],
        sub_question_count=3,
        subquestion_configs=[
            {
                "learning_content": ["Ab-Ⅳ-1"],
                "learning_performance": ["tr-Ⅳ-1"],
            },
            {},
            {},
        ],
    )
    raw = _base_raw()
    raw["科學能力"] = ["模型自選能力"]
    raw["學習內容"] = [{"編碼": "模型自選內容", "說明": "private"}]
    raw["學習表現"] = [{"編碼": "模型自選表現", "說明": "private"}]

    sq = _parse_subquestion(raw, "q1", params, 1)

    assert sq.年級 == 11
    assert sq.科學能力 == [competency.value]
    assert [ref.編碼 for ref in sq.學習內容] == ["Ab-Ⅳ-1"]
    assert [ref.編碼 for ref in sq.學習表現] == ["tr-Ⅳ-1"]
