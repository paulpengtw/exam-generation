"""Deterministic validation & repair of 學習內容/學習表現 codes (issue #92).

The NS curriculum JSON mixes ASCII roman numerals ("Aa-IV-3") and Unicode
numerals ("Ab-Ⅳ-1"); LLM output drifts between the two spellings and
sometimes invents codes that do not exist at all. All lookups here run on
a normalized form (Unicode Ⅰ–Ⅴ → ASCII, whitespace stripped), and the
canonical spelling + 說明 from the curriculum JSON is restored on the way
out.

Validation is existence-based across all 學習階段: "is this a real 108課綱
code" is the deterministic guarantee. Stage-appropriateness stays a
judgement call for the LLM verifier, whose prompt only contains the
stage-filtered curriculum.

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
) -> list[LearningContentRef]:
    """Canonicalize valid refs, drop unknown ones, dedupe; fall back to pool.

    When every emitted ref is unknown (or refs is empty), the sampled-pool
    codes are substituted — they were drawn from the curriculum JSON, so
    they are valid by construction (still guarded through ``canonical``).
    Returns [] only when both refs and fallback yield nothing valid.
    """
    repaired: list[LearningContentRef] = []
    seen: set[str] = set()
    for ref in refs:
        fixed = canonical(ref.編碼)
        if fixed is None or fixed.編碼 in seen:
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
) -> list[LearningContentRef]:
    """Repair LLM-emitted 學習內容 refs against the curriculum + pool."""
    return _repair_refs(refs, fallback_codes, canonical_lc)


def repair_lp_refs(
    refs: list[LearningContentRef],
    fallback_codes: list[str],
) -> list[LearningContentRef]:
    """Repair LLM-emitted 學習表現 refs against the curriculum + pool."""
    return _repair_refs(refs, fallback_codes, canonical_lp)


def validate_question_codes(question: ExamQuestion) -> list[str]:
    """Return deterministic issues for unknown or missing LC/LP codes."""
    issues: list[str] = []
    for sq in question.subquestions:
        label = f"第{sq.序號}小題"
        if not sq.學習內容:
            issues.append(f"{label}：缺少學習內容編碼")
        else:
            unknown = [r.編碼 for r in sq.學習內容 if canonical_lc(r.編碼) is None]
            if unknown:
                issues.append(f"{label}：學習內容編碼不存在於課綱：{'、'.join(unknown)}")
        if not sq.學習表現:
            issues.append(f"{label}：缺少學習表現編碼")
        else:
            unknown = [r.編碼 for r in sq.學習表現 if canonical_lp(r.編碼) is None]
            if unknown:
                issues.append(f"{label}：學習表現編碼不存在於課綱：{'、'.join(unknown)}")
    return issues
