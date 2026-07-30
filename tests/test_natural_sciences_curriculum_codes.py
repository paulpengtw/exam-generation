"""Deterministic 學習內容/學習表現 code validation + repair helpers (issue #92).

Real curriculum facts these tests rely on (data/natural_sciences/curriculum/):
- "Ab-Ⅳ-1" (Unicode Ⅳ) exists, 條目說明 "物質的粒子模型與物質三態。"
- "Aa-Ⅳ-3" (Unicode Ⅳ) exists — the build script normalises all stages to Unicode.
  (Before issue #289 the XLSX had ASCII "Aa-IV-3"; normalisation now produces "Aa-Ⅳ-3".)
  Stage: 第四學習階段.
- "BDa-Ⅴa-1" exists in 學習內容.  Stage: 第五學習階段.
- "tr-Ⅳ-1" exists in 學習表現.  Stage: 第四學習階段.
- "pa-Ⅴa-1" exists in 學習表現.  Stage: 第五學習階段.
- "INc-Ⅳ-1" does NOT exist (INc rows only exist at stages II/III).
- "CJa-Ⅴa-2" (Unicode Ⅴ) is the canonical form for the 第五學習階段 化學 code
  formerly stored as "CJa-Va-2" (ASCII V) in the XLSX (issue #289).
- All 第五學習階段 LC codes in the shipped JSON must use Unicode Ⅴ (issue #289).
"""

from __future__ import annotations

import re

from src.natural_sciences.curriculum_codes import (
    canonical_lc,
    canonical_lp,
    normalize_code,
    repair_lc_refs,
    repair_lp_refs,
    validate_question_codes,
)
from src.natural_sciences.curriculum_loader import (
    load_learning_content,
    load_learning_performance,
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
    # After issue #289 normalisation the build script emits "Aa-Ⅳ-3" (Unicode Ⅳ).
    # Both ASCII and Unicode inputs canonicalize to the Unicode canonical form.
    ref2 = canonical_lc("Aa-Ⅳ-3")
    assert ref2 is not None
    assert ref2.編碼 == "Aa-Ⅳ-3"
    ref3 = canonical_lc("Aa-IV-3")  # ASCII input also resolves to the same entry
    assert ref3 is not None
    assert ref3.編碼 == "Aa-Ⅳ-3"


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
    # "Aa-IV-3" (ASCII input) resolves to "Aa-Ⅳ-3" (Unicode canonical) after #289.
    repaired = repair_lc_refs(refs, ["Ab-Ⅳ-1", "Aa-IV-3"])
    assert [r.編碼 for r in repaired] == ["Ab-Ⅳ-1", "Aa-Ⅳ-3"]


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
# Issue #289: canonical Ⅴ/V roman-numeral spelling invariants
# ---------------------------------------------------------------------------


def test_shipped_json_fifth_stage_lc_codes_use_unicode_v() -> None:
    """All 第五學習階段 學習內容 codes in the shipped JSON must use Unicode Ⅴ, not ASCII V.

    This is the characterisation test for issue #289.  It will be RED until the
    build script is updated and the JSON is regenerated.
    """
    data = load_learning_content()
    fifth_stage = [r for r in data["學習內容"] if r["學習階段"] == "第五學習階段"]
    ascii_v_codes = [r["value"] for r in fifth_stage if re.search(r"-V[a-z]-", r["value"])]
    assert ascii_v_codes == [], (
        f"Found {len(ascii_v_codes)} 第五學習階段 codes with ASCII V: {ascii_v_codes[:5]}"
    )


def test_canonical_lc_ascii_v_input_returns_unicode_v_output() -> None:
    """canonical_lc() on an ASCII-V stage code must return the Unicode-Ⅴ canonical form.

    'CJa-Va-2' (ASCII V) and 'CJa-Ⅴa-2' (Unicode Ⅴ) are the same 108課綱 化學 entry.
    After normalization both spellings canonicalize to the Unicode Ⅴ form stored in JSON.
    """
    ref = canonical_lc("CJa-Va-2")
    assert ref is not None, "CJa-Va-2 must exist in the curriculum"
    assert ref.編碼 == "CJa-Ⅴa-2", (
        f"Expected Unicode Ⅴ canonical form 'CJa-Ⅴa-2', got {ref.編碼!r}"
    )


def test_both_v_spellings_resolve_to_same_canonical_entry() -> None:
    """ASCII Va and Unicode Ⅴa input both resolve to the identical canonical entry.

    This invariant must hold before AND after normalization — it verifies that the
    existing normalization path (normalize_code: Unicode→ASCII) keeps both spellings
    pointing at the same curriculum row.
    """
    ref_ascii = canonical_lc("CJa-Va-2")
    ref_unicode = canonical_lc("CJa-Ⅴa-2")
    assert ref_ascii is not None, "ASCII spelling 'CJa-Va-2' must resolve"
    assert ref_unicode is not None, "Unicode spelling 'CJa-Ⅴa-2' must resolve"
    assert ref_ascii.編碼 == ref_unicode.編碼, (
        f"ASCII and Unicode inputs resolved to different entries: "
        f"{ref_ascii.編碼!r} vs {ref_unicode.編碼!r}"
    )


def test_lp_cross_links_point_to_valid_lc_codes() -> None:
    """Every 對應學習內容 code in learning_performance.json resolves via canonical_lc().

    This guards the cross-link invariant: after normalizing LC codes the LP
    back-references must still resolve (no dangling references).
    """
    lp_data = load_learning_performance()
    dangling: list[tuple[str, str]] = []
    for row in lp_data["學習表現"]:
        lp_code = row["value"]
        for lc_code in row.get("對應學習內容", []):
            if canonical_lc(lc_code) is None:
                dangling.append((lp_code, lc_code))
    assert dangling == [], (
        f"Found {len(dangling)} dangling LP→LC cross-links: {dangling[:5]}"
    )


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
    """In-stage LC codes are kept when learning_stage is specified (issue #287).

    After issue #289, repair_lc_refs canonicalizes ASCII input to the Unicode
    spelling now stored in the JSON — so "Aa-IV-3" (ASCII input) is returned
    as "Aa-Ⅳ-3" (Unicode canonical form).
    """
    refs = [LearningContentRef(編碼="Aa-IV-3", 說明="")]
    repaired = repair_lc_refs(refs, ["BDa-Ⅴa-1"], learning_stage="第四學習階段")
    assert [r.編碼 for r in repaired] == ["Aa-Ⅳ-3"]


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
