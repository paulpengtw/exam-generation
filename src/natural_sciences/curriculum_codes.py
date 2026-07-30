"""Deterministic validation & repair of 學習內容/學習表現 codes (issue #92, #287).

The NS curriculum JSON mixes ASCII roman numerals ("Aa-IV-3") and Unicode
numerals ("Ab-Ⅳ-1"); LLM output drifts between the two spellings and
sometimes invents codes that do not exist at all. All lookups here run on
a normalized form (Unicode Ⅰ–Ⅴ → ASCII, whitespace stripped), and the
canonical spelling + 說明 from the curriculum JSON is restored on the way
out.

When ``learning_stage`` is supplied the check is stage-aware (issue #287):
codes that exist in the curriculum but belong to a different 學習階段 are
treated as invalid — repair drops them and falls back to the sampled pool,
and validation emits a distinct "屬於其他學習階段" issue.  Without
``learning_stage`` the old existence-only behaviour is preserved.

Legacy flat questions (題目-only, no subquestions) are not validated.
"""

from __future__ import annotations

from collections.abc import Callable

from src.natural_sciences.curriculum_loader import (
    load_learning_content,
    load_learning_performance,
)
from src.natural_sciences.schemas import ExamQuestion, LearningContentRef

_ROMAN_TO_ASCII = str.maketrans({"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V"})


def normalize_code(code: str) -> str:
    """Trim whitespace and rewrite Unicode roman numerals to ASCII."""
    return code.strip().translate(_ROMAN_TO_ASCII)


_CONTENT_DATA: dict = load_learning_content()
_PERFORMANCE_DATA: dict = load_learning_performance()

# normalized code -> (canonical curriculum value, 說明)
_LC_LOOKUP: dict[str, tuple[str, str]] = {
    normalize_code(row["value"]): (row["value"], row.get("條目說明", ""))
    for row in _CONTENT_DATA["學習內容"]
}
_LP_LOOKUP: dict[str, tuple[str, str]] = {
    normalize_code(row["value"]): (row["value"], row.get("說明", ""))
    for row in _PERFORMANCE_DATA["學習表現"]
}

# normalized code -> 學習階段 (for stage-aware checks, issue #287)
_LC_STAGE: dict[str, str] = {
    normalize_code(row["value"]): row["學習階段"]
    for row in _CONTENT_DATA["學習內容"]
}
_LP_STAGE: dict[str, str] = {
    normalize_code(row["value"]): row["學習階段"]
    for row in _PERFORMANCE_DATA["學習表現"]
}


def canonical_lc(code: str) -> LearningContentRef | None:
    """Return the canonical 學習內容 ref for ``code``, or None if unknown."""
    hit = _LC_LOOKUP.get(normalize_code(code))
    if hit is None:
        return None
    return LearningContentRef(編碼=hit[0], 說明=hit[1])


def canonical_lp(code: str) -> LearningContentRef | None:
    """Return the canonical 學習表現 ref for ``code``, or None if unknown."""
    hit = _LP_LOOKUP.get(normalize_code(code))
    if hit is None:
        return None
    return LearningContentRef(編碼=hit[0], 說明=hit[1])


def _repair_refs(
    refs: list[LearningContentRef],
    fallback_codes: list[str],
    canonical: Callable[[str], LearningContentRef | None],
    stage_lookup: dict[str, str] | None = None,
    learning_stage: str | None = None,
) -> list[LearningContentRef]:
    """Canonicalize valid refs, drop unknown/off-stage ones, dedupe; fall back to pool.

    When every emitted ref is unknown (or refs is empty), the sampled-pool
    codes are substituted — they were drawn from the curriculum JSON, so
    they are valid by construction (still guarded through ``canonical``).
    Returns [] only when both refs and fallback yield nothing valid.

    When *learning_stage* and *stage_lookup* are both provided (issue #287),
    codes that exist in the curriculum but belong to a different 學習階段 are
    treated as invalid and dropped (same path as unknown codes).
    """
    check_stage = stage_lookup is not None and learning_stage is not None

    repaired: list[LearningContentRef] = []
    seen: set[str] = set()
    for ref in refs:
        fixed = canonical(ref.編碼)
        if fixed is None or fixed.編碼 in seen:
            continue
        # Issue #287: drop real codes that belong to a different stage.
        if check_stage and stage_lookup.get(normalize_code(fixed.編碼)) != learning_stage:  # type: ignore[union-attr]
            continue
        if not fixed.說明 and ref.說明:
            fixed = fixed.model_copy(update={"說明": ref.說明})
        seen.add(fixed.編碼)
        repaired.append(fixed)
    if repaired:
        return repaired
    fallback: list[LearningContentRef] = []
    for code in fallback_codes:
        fixed = canonical(code)
        if fixed is not None and fixed.編碼 not in seen:
            seen.add(fixed.編碼)
            fallback.append(fixed)
    return fallback


def repair_lc_refs(
    refs: list[LearningContentRef],
    fallback_codes: list[str],
    learning_stage: str | None = None,
) -> list[LearningContentRef]:
    """Repair LLM-emitted 學習內容 refs against the curriculum + pool.

    When *learning_stage* is provided, off-stage codes are dropped (issue #287).
    """
    return _repair_refs(refs, fallback_codes, canonical_lc, _LC_STAGE, learning_stage)


def repair_lp_refs(
    refs: list[LearningContentRef],
    fallback_codes: list[str],
    learning_stage: str | None = None,
) -> list[LearningContentRef]:
    """Repair LLM-emitted 學習表現 refs against the curriculum + pool.

    When *learning_stage* is provided, off-stage codes are dropped (issue #287).
    """
    return _repair_refs(refs, fallback_codes, canonical_lp, _LP_STAGE, learning_stage)


def validate_question_codes(
    question: ExamQuestion,
    learning_stage: str | None = None,
) -> list[str]:
    """Return deterministic issues for unknown, missing, or off-stage LC/LP codes.

    When *learning_stage* is provided (issue #287), codes that exist in the
    curriculum but belong to a different 學習階段 are reported as off-stage
    rather than just unknown — the distinction appears in the issue message so
    the corrector and operator can tell them apart.
    """
    issues: list[str] = []
    check_stage = learning_stage is not None

    for sq in question.subquestions:
        label = f"第{sq.序號}小題"
        if not sq.學習內容:
            issues.append(f"{label}：缺少學習內容編碼")
        else:
            unknown = []
            off_stage = []
            for r in sq.學習內容:
                canon = canonical_lc(r.編碼)
                if canon is None:
                    unknown.append(r.編碼)
                elif check_stage and _LC_STAGE.get(normalize_code(canon.編碼)) != learning_stage:
                    off_stage.append(r.編碼)
            if unknown:
                issues.append(f"{label}：學習內容編碼不存在於課綱：{'、'.join(unknown)}")
            if off_stage:
                issues.append(
                    f"{label}：學習內容編碼屬於其他學習階段"
                    f"（預期{learning_stage}）：{'、'.join(off_stage)}"
                )

        if not sq.學習表現:
            issues.append(f"{label}：缺少學習表現編碼")
        else:
            unknown = []
            off_stage = []
            for r in sq.學習表現:
                canon = canonical_lp(r.編碼)
                if canon is None:
                    unknown.append(r.編碼)
                elif check_stage and _LP_STAGE.get(normalize_code(canon.編碼)) != learning_stage:
                    off_stage.append(r.編碼)
            if unknown:
                issues.append(f"{label}：學習表現編碼不存在於課綱：{'、'.join(unknown)}")
            if off_stage:
                issues.append(
                    f"{label}：學習表現編碼屬於其他學習階段"
                    f"（預期{learning_stage}）：{'、'.join(off_stage)}"
                )
    return issues
