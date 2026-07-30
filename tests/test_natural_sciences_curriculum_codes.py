"""Deterministic 學習內容/學習表現 code validation + repair helpers (issue #92).

Real curriculum facts these tests rely on (data/natural_sciences/curriculum/):
- "Ab-Ⅳ-1" (Unicode Ⅳ) exists, 條目說明 "物質的粒子模型與物質三態。"
- "Aa-IV-3" (ASCII IV) exists — the JSON mixes both spellings.  Stage: 第四學習階段.
- "BDa-Ⅴa-1" exists in 學習內容.  Stage: 第五學習階段.
- "tr-Ⅳ-1" exists in 學習表現.  Stage: 第四學習階段.
- "pa-Ⅴa-1" exists in 學習表現.  Stage: 第五學習階段.
- "INc-Ⅳ-1" does NOT exist (INc rows only exist at stages II/III).
"""

from __future__ import annotations

from src.natural_sciences.curriculum_codes import (
    canonical_lc,
    canonical_lp,
    normalize_code,
    repair_lc_refs,
    repair_lp_refs,
    validate_question_codes,
)
from src.natural_sciences.schemas import (
    ExamQuestion,
    LearningContentRef,
    SubQuestion,
)


def test_normalize_code_maps_unicode_roman_numerals_to_ascii() -> None:
    assert normalize_code("Ab-Ⅳ-1") == "Ab-IV-1"
    assert normalize_code(" tr-Ⅳ-1 ") == "tr-IV-1"
    assert normalize_code("Aa-IV-3") == "Aa-IV-3"


def test_canonical_lc_restores_curriculum_spelling() -> None:
    # Curriculum stores "Ab-Ⅳ-1" (Unicode Ⅳ): ASCII input canonicalizes to it.
    ref = canonical_lc("Ab-IV-1")
    assert ref is not None
    assert ref.編碼 == "Ab-Ⅳ-1"
    assert ref.說明 == "物質的粒子模型與物質三態。"
    # Curriculum stores "Aa-IV-3" (ASCII): Unicode input canonicalizes to it.
    ref2 = canonical_lc("Aa-Ⅳ-3")
    assert ref2 is not None
    assert ref2.編碼 == "Aa-IV-3"


def test_canonical_lc_rejects_unknown_codes() -> None:
    assert canonical_lc("INc-Ⅳ-1") is None  # plausible-looking, not in curriculum
    assert canonical_lc("歷Ka-Ⅳ-1") is None  # social-studies code
    assert canonical_lc("") is None


def test_canonical_lp_looks_up_performance_codes() -> None:
    ref = canonical_lp("tr-IV-1")
    assert ref is not None
    assert ref.編碼 == "tr-Ⅳ-1"
    assert ref.說明  # 說明 filled from curriculum
    assert canonical_lp("Ab-Ⅳ-1") is None  # an LC code is not an LP code


def test_repair_lc_refs_canonicalizes_dedupes_and_drops_unknown() -> None:
    refs = [
        LearningContentRef(編碼="Ab-IV-1", 說明=""),  # wrong spelling → fixed
        LearningContentRef(編碼="INc-Ⅳ-1", 說明="幻覺代碼"),  # unknown → dropped
        LearningContentRef(編碼="Ab-Ⅳ-1", 說明="重複"),  # duplicate → deduped
    ]
    repaired = repair_lc_refs(refs, ["Aa-IV-3"])
    assert [r.編碼 for r in repaired] == ["Ab-Ⅳ-1"]
    assert repaired[0].說明 == "物質的粒子模型與物質三態。"


def test_repair_lc_refs_falls_back_to_pool_when_all_invalid() -> None:
    refs = [LearningContentRef(編碼="INc-Ⅳ-1", 說明="")]
    repaired = repair_lc_refs(refs, ["Ab-Ⅳ-1", "Aa-IV-3"])
    assert [r.編碼 for r in repaired] == ["Ab-Ⅳ-1", "Aa-IV-3"]


def test_repair_lp_refs_falls_back_to_pool_when_empty() -> None:
    repaired = repair_lp_refs([], ["tr-Ⅳ-1"])
    assert [r.編碼 for r in repaired] == ["tr-Ⅳ-1"]
    assert repaired[0].說明  # 說明 filled from curriculum


def test_repair_refs_returns_empty_when_nothing_valid() -> None:
    assert repair_lc_refs([], []) == []
    assert repair_lc_refs([LearningContentRef(編碼="bogus")], ["also-bogus"]) == []


def _question(subquestions: list[SubQuestion]) -> ExamQuestion:
    return ExamQuestion(
        情境=["Personal"],
        題型種類="題組題",
        題型="Simple multiple-choice",
        subquestions=subquestions,
    )


def _sq(lc: list[str], lp: list[str], 序號: int = 1) -> SubQuestion:
    return SubQuestion(
        序號=序號,
        題型="Simple multiple-choice",
        題目="Q? (A) x (B) y (C) z (D) w",
        答案="A",
        學習內容=[LearningContentRef(編碼=c) for c in lc],
        學習表現=[LearningContentRef(編碼=c) for c in lp],
    )


def test_validate_question_codes_passes_valid_codes_in_both_spellings() -> None:
    q = _question([_sq(["Ab-Ⅳ-1", "Aa-Ⅳ-3"], ["tr-IV-1"])])
    assert validate_question_codes(q) == []


def test_validate_question_codes_flags_unknown_codes_with_小題_number() -> None:
    q = _question([_sq(["INc-Ⅳ-1"], ["tr-Ⅳ-1"], 序號=2)])
    issues = validate_question_codes(q)
    assert len(issues) == 1
    assert "第2小題" in issues[0]
    assert "INc-Ⅳ-1" in issues[0]
    assert "學習內容" in issues[0]


def test_validate_question_codes_flags_missing_metadata() -> None:
    q = _question([_sq([], [])])
    assert validate_question_codes(q) == [
        "第1小題：缺少學習內容編碼",
        "第1小題：缺少學習表現編碼",
    ]


def test_validate_question_codes_ignores_legacy_flat_questions() -> None:
    # Legacy 題目-only questions have no subquestions: nothing to validate.
    assert validate_question_codes(_question([])) == []


# ---------------------------------------------------------------------------
# Stage-aware repair and validation (issue #287)
# ---------------------------------------------------------------------------


def test_repair_lc_drops_off_stage_code_falls_back_to_pool() -> None:
    """repair_lc_refs treats a real-but-off-stage code as invalid (issue #287).

    "Aa-IV-3" is 第四學習階段; requesting 第五 must drop it and use the pool.
    """
    refs = [LearningContentRef(編碼="Aa-IV-3", 說明="")]
    repaired = repair_lc_refs(refs, ["BDa-Ⅴa-1"], learning_stage="第五學習階段")
    assert [r.編碼 for r in repaired] == ["BDa-Ⅴa-1"]


def test_repair_lp_drops_off_stage_code_falls_back_to_pool() -> None:
    """repair_lp_refs treats a real-but-off-stage code as invalid (issue #287).

    "tr-Ⅳ-1" is 第四學習階段; requesting 第五 must drop it and use the pool.
    """
    refs = [LearningContentRef(編碼="tr-Ⅳ-1", 說明="")]
    repaired = repair_lp_refs(refs, ["pa-Ⅴa-1"], learning_stage="第五學習階段")
    assert [r.編碼 for r in repaired] == ["pa-Ⅴa-1"]


def test_repair_lc_keeps_in_stage_code_when_stage_specified() -> None:
    """In-stage LC codes are kept when learning_stage is specified (issue #287)."""
    refs = [LearningContentRef(編碼="Aa-IV-3", 說明="")]
    repaired = repair_lc_refs(refs, ["BDa-Ⅴa-1"], learning_stage="第四學習階段")
    assert [r.編碼 for r in repaired] == ["Aa-IV-3"]


def test_repair_lp_keeps_in_stage_code_when_stage_specified() -> None:
    """In-stage LP codes are kept when learning_stage is specified (issue #287)."""
    refs = [LearningContentRef(編碼="tr-IV-1", 說明="")]  # ASCII spelling
    repaired = repair_lp_refs(refs, ["pa-Ⅴa-1"], learning_stage="第四學習階段")
    assert [r.編碼 for r in repaired] == ["tr-Ⅳ-1"]  # canonical Unicode spelling


def test_validate_flags_off_stage_lc_with_learning_stage() -> None:
    """validate_question_codes with learning_stage flags off-stage LC codes (issue #287).

    "Aa-IV-3" (第四) on a 第五學習階段 question must be reported.
    """
    q = _question([_sq(["Aa-IV-3"], ["pa-Ⅴa-1"])])
    issues = validate_question_codes(q, learning_stage="第五學習階段")
    assert len(issues) == 1
    assert "學習內容" in issues[0]
    # The reported code may use either the submitted spelling or the canonical one.
    assert "Aa-IV-3" in issues[0] or "Aa-Ⅳ-3" in issues[0]


def test_validate_flags_off_stage_lp_with_learning_stage() -> None:
    """validate_question_codes with learning_stage flags off-stage LP codes (issue #287).

    "tr-Ⅳ-1" (第四) on a 第五學習階段 question must be reported.
    """
    q = _question([_sq(["BDa-Ⅴa-1"], ["tr-Ⅳ-1"])])
    issues = validate_question_codes(q, learning_stage="第五學習階段")
    assert len(issues) == 1
    assert "學習表現" in issues[0]
    assert "tr-Ⅳ-1" in issues[0] or "tr-IV-1" in issues[0]


def test_validate_passes_in_stage_codes_with_learning_stage() -> None:
    """All codes from the expected stage produce no issues (issue #287)."""
    q = _question([_sq(["Aa-IV-3"], ["tr-Ⅳ-1"])])
    assert validate_question_codes(q, learning_stage="第四學習階段") == []


def test_validate_without_learning_stage_accepts_real_cross_stage_codes() -> None:
    """Old existence-only behavior preserved when no learning_stage given (issue #287)."""
    q = _question([_sq(["Aa-IV-3"], ["tr-Ⅳ-1"])])
    assert validate_question_codes(q) == []
