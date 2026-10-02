"""SS _parse_subquestion must force 年級 from sampled params (issue #290).

The LLM's own 年級 emission is ignored — the parser stamps params.grade
onto every sub-question, matching how 科目 is already forced to
params.科目.value.

Reproduction from issue #290: sample_params(grade=9, seed=7); raw 子題
carries 年級=7 (a different grade in the 7-9 range the LLM may copy from
the prompt's JSON example) → output must be 年級=9.
"""

from __future__ import annotations

import pytest

from src.common.generation_core import SubquestionParseError
from src.social_studies.cli import _parse_subquestion
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import CoreCompetency, QuestionType


def _params(grade: int = 9, q_type: str = "選擇題"):
    return sample_params(
        grade=grade,
        seed=7,
        q_type=[QuestionType(q_type)],
        learning_content=["歷A-Ⅳ-1"],
        learning_performance=["歷1a-Ⅳ-1"],
    )


def _base_raw(year_grade: int | None = 7) -> dict:
    """Return a minimal valid raw 子題 dict.

    *year_grade* is what the LLM emitted for 年級; pass ``None`` to omit
    the field entirely.
    """
    raw: dict = {
        "序號": 1,
        "題型": "選擇題",
        "題目": "Q? (A) 甲 (B) 乙 (C) 丙 (D) 丁",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": "歷史事件脈絡",
        "科目": ["歷史"],
        "學習內容": [{"編碼": "歷A-Ⅳ-1", "說明": "臺灣早期歷史"}],
        "學習表現": [{"編碼": "歷1a-Ⅳ-1", "說明": "分析史料"}],
    }
    if year_grade is not None:
        raw["年級"] = year_grade
    return raw


# ---------------------------------------------------------------------------
# Core acceptance-criteria tests
# ---------------------------------------------------------------------------


def test_parse_subquestion_forces_grade_over_llm_value():
    """Raw 子題 with 年級=7 must parse to 年級=9 when params.grade=9.

    This is the exact reproduction scenario from issue #290:
    sample_params(grade=9, seed=7); raw carries a different in-range grade (7).
    """
    raw = _base_raw(year_grade=7)  # LLM emitted a different grade in the pool
    params = _params(grade=9)
    sq = _parse_subquestion(raw, "q1", params, 1)
    assert sq is not None
    assert sq.年級 == 9, (
        f"expected 年級=9 (requested grade), got 年級={sq.年級}"
    )


def test_parse_subquestion_forces_grade_when_omitted():
    """A raw 子題 that omits 年級 must still receive params.grade."""
    raw = _base_raw(year_grade=None)  # field absent
    params = _params(grade=8)
    sq = _parse_subquestion(raw, "q1", params, 1)
    assert sq is not None
    assert sq.年級 == 8, (
        f"expected 年級=8 (requested grade), got 年級={sq.年級}"
    )


@pytest.mark.parametrize(
    "q_type,題目,答案,rubric",
    [
        (
            "選擇題",
            "Q? (A) 甲 (B) 乙 (C) 丙 (D) 丁",
            "A",
            [],
        ),
        (
            "開放式建構反應題",
            "請說明該歷史事件的影響。",
            "該事件造成社會結構改變……",
            [{"code": "2", "規準說明": "完整說明因果", "學生作答實例": ["…"]}],
        ),
    ],
    ids=["選擇題", "開放式建構反應題"],
)
def test_parse_subquestion_grade_forced_for_all_ss_types(
    q_type: str,
    題目: str,
    答案: str,
    rubric: list,
) -> None:
    """Grade forcing applies identically across all three 社會領域 題型 families."""
    raw = _base_raw(year_grade=7)
    raw["題型"] = q_type
    raw["題目"] = 題目
    raw["答案"] = 答案
    raw["評分規準"] = rubric
    params = _params(grade=9, q_type=q_type)
    sq = _parse_subquestion(raw, "q1", params, 1)
    assert sq is not None, f"_parse_subquestion returned None for {q_type}"
    assert sq.年級 == 9, (
        f"{q_type}: expected 年級=9, got 年級={sq.年級}"
    )


def test_parse_subquestion_normalizes_scalar_student_example() -> None:
    raw = _base_raw()
    raw["題型"] = "開放式建構反應題"
    raw["評分規準"] = [
        {"code": "2", "規準說明": "完整說明", "學生作答實例": "學生回答"}
    ]

    sq = _parse_subquestion(
        raw,
        "q1",
        _params(q_type="開放式建構反應題"),
        1,
    )

    assert sq.評分規準[0].學生作答實例 == ["學生回答"]


@pytest.mark.parametrize("invalid", [7, {"private": "response"}])
def test_parse_subquestion_rejects_non_string_scalar_student_example(
    invalid: object,
) -> None:
    raw = _base_raw()
    raw["題型"] = "開放式建構反應題"
    raw["評分規準"] = [
        {"code": "2", "規準說明": "完整說明", "學生作答實例": invalid}
    ]

    with pytest.raises(SubquestionParseError):
        _parse_subquestion(
            raw,
            "q1",
            _params(q_type="開放式建構反應題"),
            1,
        )


def test_parse_subquestion_forces_competency_and_configured_curriculum_pins() -> None:
    competency = next(iter(CoreCompetency))
    params = sample_params(
        grade=9,
        seed=7,
        q_type=[QuestionType("選擇題")],
        core_competency=[competency],
        learning_content=["歷A-Ⅳ-1"],
        learning_performance=["歷1a-Ⅳ-1"],
        sub_question_count=3,
        subquestion_configs=[
            {
                "learning_content": ["歷A-Ⅳ-1"],
                "learning_performance": ["歷1a-Ⅳ-1"],
            },
            {},
            {},
        ],
    )
    raw = _base_raw()
    raw["核心素養"] = ["模型自選素養"]
    raw["學習內容"] = [{"編碼": "模型自選內容", "說明": "private"}]
    raw["學習表現"] = [{"編碼": "模型自選表現", "說明": "private"}]

    sq = _parse_subquestion(raw, "q1", params, 1)

    assert sq.年級 == 9
    assert sq.核心素養 == [competency.value]
    assert [ref.編碼 for ref in sq.學習內容] == ["歷A-Ⅳ-1"]
    assert [ref.編碼 for ref in sq.學習表現] == ["歷1a-Ⅳ-1"]
