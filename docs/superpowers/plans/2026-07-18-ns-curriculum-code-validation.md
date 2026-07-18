# NS Curriculum-Code Validation & Repair (issue #92 remainder) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining gaps of GitHub issue #92 ("Add verifier and corrector rules for PISA Science item types"): deterministically validate that LLM-emitted 學習內容/學習表現 編碼 on natural-sciences questions actually exist in the NS curriculum JSON, repair invalid/missing codes, and cover valid/invalid/missing-metadata cases per PISA item family with unit tests.

**Architecture:** A new module `src/natural_sciences/curriculum_codes.py` builds normalized lookup tables from the NS curriculum JSON (which mixes ASCII `"Aa-IV-3"` and Unicode `"Ab-Ⅳ-1"` roman-numeral spellings — verified: 508 Unicode / 348 ASCII rows, zero collisions after normalization) and exposes canonicalize/repair/validate helpers. Repair happens **at parse time** in `src/natural_sciences/cli.py` (`_parse_subquestion` / `_parse_question`): valid codes are canonicalized (spelling fixed, 說明 filled from curriculum), unknown codes dropped, and an empty result falls back to the sampled pool (`params.學習內容_pool` / `params.學習表現_pool`). The verifier gains a deterministic `[課綱代碼檢核]` check that forces `passed=False` for unknown or missing codes (a reject-only safety net for questions that bypass the parse path). The corrector's metadata freeze stays intact; its only change is that LLM-*added* subquestions (rows with no original counterpart, which today get frozen-to-empty `學習內容=[]`) now parse their raw codes through the same canonicalize-and-drop helpers.

**Design decision — where repair lives (the audit's open question):** Parse-time replacement from the sampled pool, **not** the LLM corrector. Rationale: (1) the pool codes are guaranteed-valid (drawn from the curriculum JSON by `src/natural_sciences/sampler.py`) and are exactly what the prompt instructed the model to use, so substituting them restores the intended constraint deterministically and at zero LLM cost; (2) the corrector has no access to `SampledParams` (the pool is not stored on `ExamQuestion`), so corrector-side pool repair would require threading params through the correction loop — a larger change for no benefit; (3) the corrector's frozen-fields contract (`學習內容/學習表現/科學能力/出題概念/科目/年級`) exists to stop correction drift and is kept: after parse-time repair the frozen originals are always valid, so the freeze *preserves* the guarantee instead of preserving garbage. Invalid codes on questions constructed outside the parse path are **rejected** by the verifier's deterministic check (issue AC: "Invalid curriculum references are rejected or corrected" — corrected in the pipeline, rejected everywhere else).

**Tech Stack:** Python 3.11 + Pydantic v2, pytest (via `uv run pytest`), ruff. No new dependencies.

**Spec:** GitHub issue #92 acceptance criteria, restricted to the 2026-07-18 audit's remaining gaps. Already shipped in commit `03b8c9f` and **out of scope**: 題組題-only enforcement, three-題型 enum enforcement, PISA dimension validation (情境/情境子類別/科學能力 enums), corrector metadata freeze. Also out of scope: the issue's "end-to-end dry-run verifier path" bullet (`--dry-run` returns the prompt before any verifier runs; nothing to change), stage-appropriateness checking (the LLM verifier's stage-filtered prompt covers it), and any math/social-studies changes.

## Global Constraints

- Only the natural-sciences pipeline changes: `src/natural_sciences/*` and tests. **No** edits to `src/verifier.py`, `src/corrector.py`, `src/social_studies/**`, `src/common/**`, or `server/**` (issue AC: "Existing subject verifiers are unaffected").
- **Out of scope** (already shipped in commit `03b8c9f` — do not re-implement or modify): 題組題-only enforcement, three-題型 enum enforcement, PISA dimension validation (情境/情境子類別/科學能力 enums), and the corrector metadata freeze itself. Also out of scope: the issue's "end-to-end dry-run verifier path" bullet (`--dry-run` returns the prompt before any verifier runs; nothing to change), stage-appropriateness checking (the LLM verifier's stage-filtered prompt covers it), and any math/social-studies changes.
- Validation is **existence-based across all 學習階段** of `data/natural_sciences/curriculum/{learning_content,learning_performance}.json`; canonical spelling and 說明 are restored from that JSON. Do not modify the curriculum JSON files.
- Code normalization maps Unicode roman numerals Ⅰ/Ⅱ/Ⅲ/Ⅳ/Ⅴ (U+2160–U+2164) to ASCII `I/II/III/IV/V` and strips surrounding whitespace. Nothing else (case is significant: LC prefixes are uppercase, LP prefixes lowercase).
- Per-小題 explicit web/API selections (`SubQuestionConfig.learning_content` / `learning_performance`) remain **forced verbatim** — repair never rewrites user-pinned codes (documented contract in CLAUDE.md).
- The corrector keeps copying `original.學習內容` / `original.學習表現` verbatim for subquestions that have an original counterpart.
- The verifier's deterministic details marker is exactly `[課綱代碼檢核] ` (parallel to the existing `[誘答分析提醒] ` marker); issue messages are `第{序號}小題：缺少學習內容編碼`, `第{序號}小題：缺少學習表現編碼`, `第{序號}小題：學習內容編碼不存在於課綱：{codes joined by 、}`, `第{序號}小題：學習表現編碼不存在於課綱：{codes joined by 、}`.
- All commands run from `/workspace/exam-generation`. Tests: `uv run pytest …`. The **full** suite includes `tests/server/`, which needs the web extras: run `uv sync --extra web` once before Task 3 Step 5 (whose `tests/test_batch_dedup.py` run includes a server-stream test importing `server.generate.service`) or Task 5, if `uv run python -c "import fastapi"` fails (a plain `uv sync` DROPS the web extras — do not run it).
- Ruff has a pre-existing repo baseline (101 errors in `src/`, 12 in `tests/` — mostly E501 on Chinese prompt strings). Lint **only the files this plan touches** (they are all clean today and must stay clean): `uv run ruff check <touched files>` → `All checks passed!`. Keep new lines ≤ 100 chars (`line-length = 100`).
- Baseline before Task 1: `uv run pytest -q` → `402 passed, 1 skipped`.

## Known fixture updates this plan must make (verified against staging)

Three existing test fixtures use the code `INc-Ⅳ-1`, which **does not exist** in the NS curriculum JSON (only `INa/INb/INc-II-*` and `-III-*` rows exist), or omit 學習內容/學習表現 entirely while asserting `passed is True`:

1. `tests/test_natural_sciences_verifier.py` `_ns_question()` (line 60) — `編碼="INc-Ⅳ-1"` → becomes valid `Ab-Ⅳ-1` (Task 2).
2. `tests/test_verifiers_distractor_warnings.py` — the two NS subquestions (lines 73–79 and 113) have empty LC/LP → get valid codes (Task 2).
3. `tests/test_batch_dedup.py` `test_ns_batch_loop_forwards_prior_scopes_to_next_question` (lines 433, 468) — the fake client emits `INc-Ⅳ-{idx}`, and the final assert expects it in the dedup block; parse-time repair would replace it with pool codes → fixture switches to real codes `Ab-Ⅳ-{idx}` (Task 3).

These are fixture modernizations, not behavior changes to what those tests verify (multimodal wiring, distractor warnings, batch dedup).

---

### Task 1: `curriculum_codes` module — normalize, canonicalize, repair, validate

**Files:**
- Create: `src/natural_sciences/curriculum_codes.py`
- Test: `tests/test_natural_sciences_curriculum_codes.py`

**Interfaces:**
- Consumes: `load_learning_content()` / `load_learning_performance()` from `src/natural_sciences/curriculum_loader.py` (no-arg call returns the full curriculum dict, honoring the `NATURAL_SCIENCES_LEARNING_*_PATH` env overrides); `LearningContentRef`, `ExamQuestion` from `src/natural_sciences/schemas.py`.
- Produces (used by Tasks 2–4):
  - `normalize_code(code: str) -> str`
  - `canonical_lc(code: str) -> LearningContentRef | None` — canonical 編碼 + curriculum 條目說明, or None if unknown.
  - `canonical_lp(code: str) -> LearningContentRef | None` — canonical 編碼 + curriculum 說明, or None.
  - `repair_lc_refs(refs: list[LearningContentRef], fallback_codes: list[str]) -> list[LearningContentRef]`
  - `repair_lp_refs(refs: list[LearningContentRef], fallback_codes: list[str]) -> list[LearningContentRef]`
  - `validate_question_codes(question: ExamQuestion) -> list[str]` — deterministic issue strings, `[]` when clean.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_natural_sciences_curriculum_codes.py`:

```python
"""Deterministic 學習內容/學習表現 code validation + repair helpers (issue #92).

Real curriculum facts these tests rely on (data/natural_sciences/curriculum/):
- "Ab-Ⅳ-1" (Unicode Ⅳ) exists, 條目說明 "物質的粒子模型與物質三態。"
- "Aa-IV-3" (ASCII IV) exists — the JSON mixes both spellings.
- "tr-Ⅳ-1" exists in 學習表現.
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_natural_sciences_curriculum_codes.py -v`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'src.natural_sciences.curriculum_codes'`.

- [ ] **Step 3: Write the implementation**

Create `src/natural_sciences/curriculum_codes.py`:

```python
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
```

Note: the module loads its own copy of the curriculum JSON at import time — the same pattern `src/natural_sciences/sampler.py` (`_LC_DATA`/`_LP_DATA`) and `context_builder.py` already use.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_natural_sciences_curriculum_codes.py -v`
Expected: PASS — 12 tests green.

- [ ] **Step 5: Lint the new files**

Run: `uv run ruff check src/natural_sciences/curriculum_codes.py tests/test_natural_sciences_curriculum_codes.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/natural_sciences/curriculum_codes.py tests/test_natural_sciences_curriculum_codes.py
git commit -m "feat(ns): add deterministic curriculum-code validation helpers (#92)"
```

---

### Task 2: Verifier — deterministic `[課綱代碼檢核]` reject

**Files:**
- Modify: `src/natural_sciences/verifier.py` (import block lines 10–16; result assembly lines 163–180)
- Modify: `tests/test_natural_sciences_verifier.py` (fixture line 60 + new tests)
- Modify: `tests/test_verifiers_distractor_warnings.py` (NS fixtures, lines 71–80 and 108–114)

**Interfaces:**
- Consumes: `validate_question_codes(question) -> list[str]` from Task 1.
- Produces: `verify_question(...)` now returns `passed=False` whenever any subquestion carries an unknown or empty 學習內容/學習表現, with the issues appended to `details` under the `[課綱代碼檢核] ` marker. Unlike the advisory `[誘答分析提醒]`, this check DOES flip `passed`.

- [ ] **Step 1: Update the two NS fixtures in `tests/test_verifiers_distractor_warnings.py`**

In `test_ns_verifier_appends_distractor_warning` (line 66), extend the imports and give the subquestion valid codes. Replace the whole function body's question construction:

```python
def test_ns_verifier_appends_distractor_warning() -> None:
    from src.natural_sciences.schemas import ExamQuestion as NSExamQuestion
    from src.natural_sciences.schemas import LearningContentRef, SubQuestion
    from src.natural_sciences.verifier import verify_question

    q = NSExamQuestion(
        情境=["Personal"], 題型種類="題組題", 題型="Simple multiple-choice",
        subquestions=[
            SubQuestion(
                序號=1, 題型="Simple multiple-choice",
                題目="Q? (A) x (B) y (C) z (D) w",
                答案="A", 誘答分析={"A": "正確答案：x。"},
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1")],
            ),
        ],
    )
    client = _FakeVerifierClient(_passed_payload())
    result = verify_question(client, q)
    assert result.passed is True
    assert "誘答分析提醒" in result.details
```

And in `test_verifier_leaves_details_unchanged_when_no_warnings`, replace the `else:` (ns) branch:

```python
    else:
        from src.natural_sciences.schemas import ExamQuestion as NSQ
        from src.natural_sciences.schemas import LearningContentRef, SubQuestion
        from src.natural_sciences.verifier import verify_question
        q = NSQ(
            情境=["Personal"], 題型種類="題組題", 題型="Simple multiple-choice",
            subquestions=[
                SubQuestion(
                    序號=1, 題型="Simple multiple-choice", 題目="Q?", 答案="A",
                    學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1")],
                    學習表現=[LearningContentRef(編碼="tr-Ⅳ-1")],
                ),
            ],
        )
```

(Reason: these fixtures previously carried empty LC/LP and asserted `passed is True`; the new deterministic check makes empty metadata a failure, so the fixtures now carry valid codes. What each test verifies — distractor-warning behavior — is unchanged.)

- [ ] **Step 2: Fix the invalid code in the `_ns_question` fixture**

In `tests/test_natural_sciences_verifier.py` line 60, replace:

```python
                學習內容=[LearningContentRef(編碼="INc-Ⅳ-1", 說明="範例學習內容")],
```

with:

```python
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="範例學習內容")],
```

(`INc-Ⅳ-1` does not exist in the curriculum JSON; `Ab-Ⅳ-1` does. `tr-Ⅳ-1` on the next line is already valid.)

- [ ] **Step 3: Write the failing verifier tests**

Append to `tests/test_natural_sciences_verifier.py` (also add `import pytest` and extend the schemas import at the top of the file with `RubricEntry`):

```python
def _passing_payload() -> dict:
    return {
        "my_answer": "A",
        "provided_answer": "A",
        "answer_match": True,
        "passed": True,
        "details": "審核通過。",
    }


def test_ns_verifier_fails_deterministically_on_unknown_curriculum_code() -> None:
    """Unknown 編碼 forces passed=False even when the LLM verdict is passed=True."""
    q = _ns_question()
    q.subquestions[0].學習內容 = [LearningContentRef(編碼="INc-Ⅳ-1", 說明="不存在的代碼")]
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is False
    assert "[課綱代碼檢核]" in result.details
    assert "INc-Ⅳ-1" in result.details


def test_ns_verifier_fails_deterministically_on_missing_learning_performance() -> None:
    q = _ns_question()
    q.subquestions[0].學習表現 = []
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is False
    assert "缺少學習表現編碼" in result.details


def test_ns_verifier_accepts_either_roman_numeral_spelling() -> None:
    q = _ns_question()
    q.subquestions[0].學習內容 = [LearningContentRef(編碼="Ab-IV-1")]  # ASCII spelling
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is True
    assert "[課綱代碼檢核]" not in result.details


# --- issue #92 unit-test matrix: one valid + one invalid case per item family ---

_FAMILY_CASES = [
    pytest.param(
        "Simple multiple-choice",
        "下列何者正確？(A) 甲 (B) 乙 (C) 丙 (D) 丁",
        "A",
        [],
        id="simple-mc",
    ),
    pytest.param(
        "Complex multiple-choice",
        "請逐項判斷下列敘述是非：(1)…… (2)…… (3)……",
        "(1)是 (2)非 (3)是",
        [],
        id="complex-mc",
    ),
    pytest.param(
        "Constructed response",
        "請說明水溫上升如何影響水中溶氧量，並舉一例。",
        "水溫上升使溶氧量下降，例如夏季魚群浮頭。",
        [
            RubricEntry(code="2", 規準說明="完整說明趨勢並舉例", 學生作答實例=["溶氧下降，夏季魚群浮頭"]),
            RubricEntry(code="0", 規準說明="無法說明趨勢", 學生作答實例=["不知道"]),
        ],
        id="constructed-response",
    ),
]


def _family_question(q_type, 題目, 答案, rubric, lc_code, lp_code):
    return ExamQuestion(
        id="ns-family",
        核心問題="測試核心問題",
        文本="測試文本素材……",
        情境=["Personal"],
        題型種類="題組題",
        題型=q_type,
        subquestions=[
            SubQuestion(
                序號=1,
                年級=8,
                科目=["自然科學"],
                題型=q_type,
                題目=題目,
                答案=答案,
                答案解析="解析。",
                評分規準=rubric,
                學習內容=[LearningContentRef(編碼=lc_code)],
                學習表現=[LearningContentRef(編碼=lp_code)],
            )
        ],
    )


@pytest.mark.parametrize("q_type,題目,答案,rubric", _FAMILY_CASES)
def test_ns_verifier_valid_codes_pass_per_item_family(q_type, 題目, 答案, rubric) -> None:
    q = _family_question(q_type, 題目, 答案, rubric, "Ab-Ⅳ-1", "tr-Ⅳ-1")
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is True
    assert "[課綱代碼檢核]" not in result.details


@pytest.mark.parametrize("q_type,題目,答案,rubric", _FAMILY_CASES)
def test_ns_verifier_unknown_codes_fail_per_item_family(q_type, 題目, 答案, rubric) -> None:
    q = _family_question(q_type, 題目, 答案, rubric, "Ab-Ⅳ-1", "xx-Ⅳ-99")
    result = verify_question(FakeClient(_passing_payload()), q)
    assert result.passed is False
    assert "[課綱代碼檢核]" in result.details
    assert "xx-Ⅳ-99" in result.details
```

Top-of-file import block becomes:

```python
import json

import pytest

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.natural_sciences.schemas import (
    ExamQuestion,
    LearningContentRef,
    RubricEntry,
    SubQuestion,
)
from src.natural_sciences.verifier import VERIFICATION_SYSTEM_PROMPT, verify_question
```

- [ ] **Step 4: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_natural_sciences_verifier.py -v`
Expected: 12 items collected; the 3 pre-existing tests PASS, and of the 9 new items the 4 valid-codes ones (`accepts_either_roman_numeral_spelling` + `valid_codes_pass_per_item_family[×3]`) already PASS by construction, while the 5 deterministic-reject items (`unknown_curriculum_code`, `missing_learning_performance`, `unknown_codes_fail_per_item_family[×3]`) FAIL — `assert result.passed is False` fails (verifier still returns True).

- [ ] **Step 5: Implement the verifier check**

In `src/natural_sciences/verifier.py`, add the import after the `context_builder` import block (i.e. between current lines 15 and 16):

```python
from src.natural_sciences.curriculum_codes import validate_question_codes
```

Then replace the result-assembly block (current lines 163–180, from `all_warnings: list[str] = []` through the `return VerificationResult(...)`) with:

```python
        all_warnings: list[str] = []
        for sq in question.subquestions:
            warnings = validate_distractor_keys(sq.題目, sq.誘答分析)
            for w in warnings:
                all_warnings.append(f"第{sq.序號}題：{w}")
        details = result.get("details", "")
        if all_warnings:
            details = details.rstrip()
            details += "\n\n[誘答分析提醒] " + "；".join(all_warnings)

        # Issue #92: deterministic curriculum-code check. Unlike the advisory
        # distractor warnings above, unknown or missing 學習內容/學習表現
        # codes are a hard reject — the LLM's lenient verdict cannot
        # overrule the curriculum JSON.
        code_issues = validate_question_codes(question)
        if code_issues:
            details = details.rstrip()
            details += "\n\n[課綱代碼檢核] " + "；".join(code_issues)

        return VerificationResult(
            passed=result.get("passed", False) and not code_issues,
            answer_match=result.get("answer_match", False),
            details=details,
            my_answer=result.get("my_answer", ""),
            provided_answer=result.get("provided_answer", ""),
            chart_verification=chart_verif,
        )
```

- [ ] **Step 6: Run the verifier-adjacent suites to verify green**

Run: `uv run pytest tests/test_natural_sciences_verifier.py tests/test_verifiers_distractor_warnings.py tests/test_verifiers_mention_difficulty.py tests/test_natural_sciences_curriculum_codes.py -v`
Expected: PASS — 12 + 6 + 3 + 12 = 33 items green. (`test_verifiers_mention_difficulty` NS case has an empty `subquestions` list, which the check deliberately ignores.)

- [ ] **Step 7: Lint the touched files**

Run: `uv run ruff check src/natural_sciences/verifier.py tests/test_natural_sciences_verifier.py tests/test_verifiers_distractor_warnings.py`
Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add src/natural_sciences/verifier.py tests/test_natural_sciences_verifier.py tests/test_verifiers_distractor_warnings.py
git commit -m "feat(ns): verifier deterministically rejects unknown/missing curriculum codes (#92)"
```

---

### Task 3: Parse-time repair in the CLI parse path

**Files:**
- Modify: `src/natural_sciences/cli.py` (imports ~line 27; `_parse_question` lines 185–194; `_parse_subquestion` lines 258–278)
- Modify: `tests/test_batch_dedup.py` (lines 433 and 468 — fixture code swap, see "Known fixture updates")
- Test: `tests/test_natural_sciences_cli.py` (new file)

**Interfaces:**
- Consumes: `repair_lc_refs(refs, fallback_codes)` / `repair_lp_refs(refs, fallback_codes)` from Task 1; `params.學習內容_pool` / `params.學習表現_pool` on `SampledParams`.
- Produces: `_parse_subquestion(sq_raw, question_id, params, i) -> SubQuestion | None` and `_parse_question(raw, question_id, params, model) -> ExamQuestion` now guarantee every parsed subquestion's 學習內容/學習表現 codes exist in the curriculum JSON (canonical spelling, curriculum 說明) whenever the sampled pool is non-empty. The cfg-pinned path (`SubQuestionConfig.learning_content/learning_performance`) stays verbatim. Both the CLI and the web server (`server/generate/service.py` imports `ns_generate_with_corrections` → `generate_one` → `_parse_subquestion`) flow through this single choke point; `generate_one`'s embedded-subquestions test path also calls `_parse_subquestion`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_natural_sciences_cli.py`:

```python
"""Parse-time repair of LLM-emitted 學習內容/學習表現 codes in the NS CLI (issue #92).

Pools are pinned via sample_params(learning_content=..., learning_performance=...)
so fallback expectations are deterministic. Real curriculum facts used:
"Ab-Ⅳ-1" / "Aa-IV-3" / "Ka-Ⅳ-1" are LC codes; "tr-Ⅳ-1" / "pa-Ⅳ-1" are LP
codes; "INc-Ⅳ-1" and "xx-Ⅳ-99" do not exist.
"""

from __future__ import annotations

import pytest

from src.natural_sciences.cli import _parse_question, _parse_subquestion
from src.natural_sciences.sampler import sample_params


def _params(q_type: str = "Simple multiple-choice", **kwargs):
    return sample_params(
        seed=1,
        q_type=[q_type],
        learning_content=["Ab-Ⅳ-1"],
        learning_performance=["tr-Ⅳ-1"],
        **kwargs,
    )


_FAMILIES = [
    pytest.param(
        "Simple multiple-choice",
        "Q? (A) 甲 (B) 乙 (C) 丙 (D) 丁",
        "A",
        [],
        id="simple-mc",
    ),
    pytest.param(
        "Complex multiple-choice",
        "請逐項判斷是非：(1)…… (2)……",
        "(1)是 (2)非",
        [],
        id="complex-mc",
    ),
    pytest.param(
        "Constructed response",
        "請解釋光合作用為何需要光。",
        "光反應需要光能供應電子傳遞……",
        [{"code": "2", "規準說明": "完整解釋", "學生作答實例": ["…"]}],
        id="constructed-response",
    ),
]


def _sq_raw(q_type, 題目, 答案, rubric, lc, lp):
    return {
        "序號": 1,
        "題型": q_type,
        "題目": 題目,
        "答案": 答案,
        "答案解析": "解析",
        "出題概念": "概念",
        "科目": ["自然科學"],
        "評分規準": rubric,
        "學習內容": [{"編碼": c, "說明": "LLM 說明"} for c in lc],
        "學習表現": [{"編碼": c, "說明": "LLM 說明"} for c in lp],
    }


@pytest.mark.parametrize("q_type,題目,答案,rubric", _FAMILIES)
def test_parse_subquestion_keeps_valid_codes_per_family(q_type, 題目, 答案, rubric) -> None:
    raw = _sq_raw(q_type, 題目, 答案, rubric, ["Aa-IV-3"], ["pa-Ⅳ-1"])
    sq = _parse_subquestion(raw, "q1", _params(q_type), 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Aa-IV-3"]  # kept, not pool-replaced
    assert [r.編碼 for r in sq.學習表現] == ["pa-Ⅳ-1"]


@pytest.mark.parametrize("q_type,題目,答案,rubric", _FAMILIES)
def test_parse_subquestion_replaces_unknown_codes_from_pool_per_family(
    q_type, 題目, 答案, rubric
) -> None:
    raw = _sq_raw(q_type, 題目, 答案, rubric, ["INc-Ⅳ-1"], ["xx-Ⅳ-99"])
    sq = _parse_subquestion(raw, "q1", _params(q_type), 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Ab-Ⅳ-1"]  # sampled pool fallback
    assert [r.編碼 for r in sq.學習表現] == ["tr-Ⅳ-1"]


def test_parse_subquestion_canonicalizes_spelling_and_fills_說明() -> None:
    raw = _sq_raw(
        "Simple multiple-choice", "Q? (A) x (B) y", "A", [],
        ["Ab-IV-1"], ["tr-IV-1"],  # ASCII spellings of Unicode-canonical codes
    )
    sq = _parse_subquestion(raw, "q1", _params(), 1)
    assert sq is not None
    assert sq.學習內容[0].編碼 == "Ab-Ⅳ-1"
    assert sq.學習內容[0].說明 == "物質的粒子模型與物質三態。"  # curriculum, not "LLM 說明"
    assert sq.學習表現[0].編碼 == "tr-Ⅳ-1"


def test_parse_subquestion_falls_back_to_pool_when_metadata_missing() -> None:
    raw = _sq_raw("Simple multiple-choice", "Q? (A) x (B) y", "A", [], [], [])
    del raw["學習內容"], raw["學習表現"]
    sq = _parse_subquestion(raw, "q1", _params(), 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Ab-Ⅳ-1"]
    assert [r.編碼 for r in sq.學習表現] == ["tr-Ⅳ-1"]


def test_parse_subquestion_drops_only_invalid_codes_when_mixed() -> None:
    raw = _sq_raw(
        "Simple multiple-choice", "Q? (A) x (B) y", "A", [],
        ["Aa-IV-3", "INc-Ⅳ-1"], ["pa-Ⅳ-1", "xx-Ⅳ-99"],
    )
    sq = _parse_subquestion(raw, "q1", _params(), 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Aa-IV-3"]  # invalid dropped, no fallback
    assert [r.編碼 for r in sq.學習表現] == ["pa-Ⅳ-1"]


def test_parse_subquestion_cfg_codes_stay_verbatim() -> None:
    """Explicit per-小題 web/API selections are forced verbatim — never repaired."""
    params = _params(
        subquestion_configs=[
            {"learning_content": ["Ka-Ⅳ-1"], "learning_performance": ["pa-Ⅳ-1"]}
        ],
    )
    raw = _sq_raw(
        "Simple multiple-choice", "Q? (A) x (B) y", "A", [],
        ["INc-Ⅳ-1"], ["xx-Ⅳ-99"],
    )
    sq = _parse_subquestion(raw, "q1", params, 1)
    assert sq is not None
    assert [r.編碼 for r in sq.學習內容] == ["Ka-Ⅳ-1"]
    assert [r.編碼 for r in sq.學習表現] == ["pa-Ⅳ-1"]


def test_parse_question_repairs_subquestion_codes() -> None:
    raw = {
        "核心問題": "測試核心問題",
        "文本": "測試文本",
        "取材來源": [],
        "subquestions": [
            {
                "序號": 1,
                "題型": "Simple multiple-choice",
                "題目": "Q? (A) 甲 (B) 乙",
                "答案": "A",
                "答案解析": "解析",
                "學習內容": [{"編碼": "INc-Ⅳ-1", "說明": "幻覺"}],
                "學習表現": [{"編碼": "tr-IV-1", "說明": ""}],
            }
        ],
        "題目": ["文本", "Q?"],
        "正確解題分析": ["A"],
    }
    question = _parse_question(raw, "ns_test_001", _params(), "test-model")
    assert [r.編碼 for r in question.subquestions[0].學習內容] == ["Ab-Ⅳ-1"]  # pool
    assert [r.編碼 for r in question.subquestions[0].學習表現] == ["tr-Ⅳ-1"]  # canonicalized
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_natural_sciences_cli.py -v`
Expected: 11 items collected; the two `keeps_valid` / `cfg_codes_stay_verbatim` groups PASS (they pin existing behavior); the rest FAIL — e.g. `assert ['INc-Ⅳ-1'] == ['Ab-Ⅳ-1']` (codes are still accepted verbatim).

- [ ] **Step 3: Implement parse-time repair**

In `src/natural_sciences/cli.py`:

(a) Add the import after `from src.natural_sciences.corrector import correct_question` (line 27):

```python
from src.natural_sciences.curriculum_codes import repair_lc_refs, repair_lp_refs
```

(b) In `_parse_subquestion`, replace the cfg-override block (current lines 269–278) so both `if` branches gain an `else` that repairs:

```python
        if cfg and cfg.learning_content:
            lc_refs = [
                LearningContentRef(編碼=code, 說明=LC_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_content
            ]
        else:
            # Issue #92: canonicalize LLM-emitted codes; unknown codes are
            # dropped and an empty result falls back to the sampled pool.
            lc_refs = repair_lc_refs(lc_refs, params.學習內容_pool)
        if cfg and cfg.learning_performance:
            lp_refs = [
                LearningContentRef(編碼=code, 說明=LP_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_performance
            ]
        else:
            lp_refs = repair_lp_refs(lp_refs, params.學習表現_pool)
```

(c) In `_parse_question`, directly after the `lp_refs = [...]` list comprehension (current lines 190–194) and before the `rubric = [...]` block, insert:

```python
            lc_refs = repair_lc_refs(lc_refs, params.學習內容_pool)
            lp_refs = repair_lp_refs(lp_refs, params.學習表現_pool)
```

- [ ] **Step 4: Update the batch-dedup fixture that emits a nonexistent code**

In `tests/test_batch_dedup.py`, `test_ns_batch_loop_forwards_prior_scopes_to_next_question`:

Line 433 — replace:

```python
                        "學習內容": [{"編碼": f"INc-Ⅳ-{idx}", "說明": "測試"}],
```

with:

```python
                        "學習內容": [{"編碼": f"Ab-Ⅳ-{idx}", "說明": "測試"}],
```

Line 468 — replace:

```python
    assert "1. 核心問題：科學核心問題 1；學習內容：INc-Ⅳ-1" in text_prompts[0]
```

with:

```python
    assert "1. 核心問題：科學核心問題 1；學習內容：Ab-Ⅳ-1" in text_prompts[0]
```

(`Ab-Ⅳ-1` and `Ab-Ⅳ-2` both exist in the curriculum, so parse-time repair keeps them and the dedup block still carries them. The other NS dedup test, `test_ns_build_text_user_prompt_renders_prior_scopes_block`, constructs `PriorScope` directly and never touches the parse path — leave it alone.)

- [ ] **Step 5: Run the affected suites to verify green**

Run: `uv run pytest tests/test_natural_sciences_cli.py tests/test_batch_dedup.py tests/test_natural_sciences_distractor_prompt.py tests/test_per_subquestion_lc_lp_output.py -v`
Expected: PASS — all items green (11 new + existing; `test_ns_parse_subquestion_populates_and_defaults_distractor_analysis` doesn't assert LC/LP so pool-filling doesn't affect it).

- [ ] **Step 6: Lint the touched files**

Run: `uv run ruff check src/natural_sciences/cli.py tests/test_natural_sciences_cli.py tests/test_batch_dedup.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/natural_sciences/cli.py tests/test_natural_sciences_cli.py tests/test_batch_dedup.py
git commit -m "feat(ns): repair LLM-emitted curriculum codes at parse time from sampled pool (#92)"
```

---

### Task 4: Corrector — canonicalize codes on LLM-added subquestions

**Files:**
- Modify: `src/natural_sciences/corrector.py` (imports lines 8–14; new helper; SubQuestion rebuild lines 143–144)
- Test: `tests/test_natural_sciences_corrector_codes.py` (new file)

**Interfaces:**
- Consumes: `repair_lc_refs` / `repair_lp_refs` from Task 1 (with `fallback_codes=[]` — the corrector has no `SampledParams`, hence no pool; see the header design decision).
- Produces: `correct_question(client, question, verification, chart_image_path=None) -> ExamQuestion` still freezes 學習內容/學習表現 on subquestions that have an original counterpart; for LLM-**added** rows (index ≥ original count, which today are frozen to `學習內容=[]`) it now parses the raw codes through the canonical helpers, so the corrector can never introduce invalid metadata. All-invalid added rows end up with empty lists, which the Task 2 verifier check rejects on re-verify.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_natural_sciences_corrector_codes.py`:

```python
"""NS corrector: frozen originals stay verbatim; LLM-added subquestions get
their 學習內容/學習表現 codes canonicalized deterministically (issue #92)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.natural_sciences.corrector import correct_question
from src.natural_sciences.curriculum_codes import validate_question_codes
from src.natural_sciences.schemas import (
    ExamQuestion,
    LearningContentRef,
    SubQuestion,
    VerificationResult,
)


def _base_question() -> ExamQuestion:
    return ExamQuestion(
        id="ns1",
        情境=["Personal"],
        題型種類="題組題",
        題型="Simple multiple-choice",
        subquestions=[
            SubQuestion(
                id="sq1", 序號=1, 題型="Simple multiple-choice",
                題目="Q? (A) x (B) y", 答案="A",
                學習內容=[LearningContentRef(編碼="Ab-Ⅳ-1", 說明="物質的粒子模型與物質三態。")],
                學習表現=[LearningContentRef(編碼="tr-Ⅳ-1", 說明="說明")],
            ),
        ],
    )


def _client(payload: dict) -> MagicMock:
    client = MagicMock()
    client.generate_json.return_value = payload
    return client


_VERIFICATION = VerificationResult(passed=False, answer_match=False, details="需修正")


def test_corrector_freezes_valid_original_codes() -> None:
    """Rows with an original counterpart keep the original codes verbatim."""
    payload = {
        "subquestions": [{
            "序號": 1, "題型": "Simple multiple-choice",
            "題目": "Q? (A) x (B) y", "答案": "B", "答案解析": "改正",
            "學習內容": [{"編碼": "INc-Ⅳ-1", "說明": "LLM 亂改"}],
            "學習表現": [{"編碼": "xx-Ⅳ-99", "說明": "LLM 亂改"}],
        }],
    }
    corrected = correct_question(_client(payload), _base_question(), _VERIFICATION)
    assert [r.編碼 for r in corrected.subquestions[0].學習內容] == ["Ab-Ⅳ-1"]
    assert [r.編碼 for r in corrected.subquestions[0].學習表現] == ["tr-Ⅳ-1"]


def test_corrector_canonicalizes_codes_on_llm_added_subquestion() -> None:
    payload = {
        "subquestions": [
            {
                "序號": 1, "題型": "Simple multiple-choice",
                "題目": "Q? (A) x (B) y", "答案": "A", "答案解析": "原題",
            },
            {
                "序號": 2, "題型": "Simple multiple-choice",
                "題目": "新增題 (A) 甲 (B) 乙", "答案": "B", "答案解析": "新增",
                "學習內容": [
                    {"編碼": "Ab-IV-2", "說明": ""},       # ASCII → canonical Ab-Ⅳ-2
                    {"編碼": "bogus-code", "說明": ""},    # unknown → dropped
                ],
                "學習表現": [{"編碼": "tr-IV-1", "說明": ""}],
            },
        ],
    }
    corrected = correct_question(_client(payload), _base_question(), _VERIFICATION)
    assert len(corrected.subquestions) == 2
    added = corrected.subquestions[1]
    assert [r.編碼 for r in added.學習內容] == ["Ab-Ⅳ-2"]
    assert added.學習內容[0].說明  # 說明 filled from curriculum
    assert [r.編碼 for r in added.學習表現] == ["tr-Ⅳ-1"]
    assert validate_question_codes(corrected) == []


def test_corrector_drops_all_invalid_codes_on_llm_added_subquestion() -> None:
    """No pool in the corrector: an all-invalid added row ends up empty and
    is rejected by the verifier's deterministic check on re-verify."""
    payload = {
        "subquestions": [
            {
                "序號": 1, "題型": "Simple multiple-choice",
                "題目": "Q? (A) x (B) y", "答案": "A", "答案解析": "原題",
            },
            {
                "序號": 2, "題型": "Simple multiple-choice",
                "題目": "新增題", "答案": "B", "答案解析": "新增",
                "學習內容": [{"編碼": "bogus-code", "說明": ""}],
                "學習表現": [{"編碼": "xx-Ⅳ-99", "說明": ""}],
            },
        ],
    }
    corrected = correct_question(_client(payload), _base_question(), _VERIFICATION)
    added = corrected.subquestions[1]
    assert added.學習內容 == []
    assert added.學習表現 == []
    issues = validate_question_codes(corrected)
    assert "第2小題：缺少學習內容編碼" in issues
    assert "第2小題：缺少學習表現編碼" in issues
```

- [ ] **Step 2: Run tests to verify the middle one fails**

Run: `uv run pytest tests/test_natural_sciences_corrector_codes.py -v`
Expected: 3 items; `test_corrector_freezes_valid_original_codes` and `test_corrector_drops_all_invalid_codes_on_llm_added_subquestion` PASS (they pin the existing freeze / frozen-to-empty behavior); `test_corrector_canonicalizes_codes_on_llm_added_subquestion` FAILS with `assert [] == ['Ab-Ⅳ-2']` (added rows currently get `學習內容=[]`).

- [ ] **Step 3: Implement the corrector change**

In `src/natural_sciences/corrector.py`:

(a) Replace the import block (current lines 8–14) with:

```python
from src.llm_client import LLMClient, extract_json
from src.natural_sciences.context_builder import (
    _CONTENT_TEXT,
    _PERFORMANCE_TEXT,
    _build_curriculum_section,
)
from src.natural_sciences.curriculum_codes import repair_lc_refs, repair_lp_refs
from src.natural_sciences.schemas import (
    ExamQuestion,
    ImageSpec,
    LearningContentRef,
    VerificationResult,
)
```

(b) Add a module-level helper directly above `def correct_question(` (current line 56):

```python
def _refs_from_raw(raw: object) -> list[LearningContentRef]:
    """Best-effort parse of a raw LLM 學習內容/學習表現 list into refs."""
    if not isinstance(raw, list):
        return []
    return [
        LearningContentRef(編碼=r.get("編碼", ""), 說明=r.get("說明", ""))
        for r in raw
        if isinstance(r, dict) and r.get("編碼")
    ]
```

(c) In the SubQuestion rebuild inside `correct_question`, replace the two frozen lines (current lines 143–144):

```python
                    學習內容=original.學習內容 if original else [],
                    學習表現=original.學習表現 if original else [],
```

with:

```python
                    # Frozen when an original exists (post issue-#92 parse
                    # repair the originals are always valid); LLM-added rows
                    # get deterministic canonicalization instead (no pool
                    # here, so unknown codes are dropped, not replaced).
                    學習內容=(
                        original.學習內容
                        if original
                        else repair_lc_refs(_refs_from_raw(sq_raw.get("學習內容")), [])
                    ),
                    學習表現=(
                        original.學習表現
                        if original
                        else repair_lp_refs(_refs_from_raw(sq_raw.get("學習表現")), [])
                    ),
```

- [ ] **Step 4: Run the corrector suites to verify green**

Run: `uv run pytest tests/test_natural_sciences_corrector_codes.py tests/test_correctors_freeze_difficulty.py tests/test_correctors_distractor_mutation.py -v`
Expected: PASS — 3 new + all existing corrector tests green.

- [ ] **Step 5: Lint the touched files**

Run: `uv run ruff check src/natural_sciences/corrector.py tests/test_natural_sciences_corrector_codes.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/natural_sciences/corrector.py tests/test_natural_sciences_corrector_codes.py
git commit -m "feat(ns): corrector canonicalizes curriculum codes on LLM-added subquestions (#92)"
```

---

### Task 5: Full-suite regression + documentation

**Files:**
- Modify: `CLAUDE.md` (Key Files table, around line 162)

**Interfaces:**
- Consumes: everything above.
- Produces: green full suite; CLAUDE.md documents the new module and the verifier/corrector/parse-path behavior for future sessions.

- [ ] **Step 1: Ensure web extras are present, then run the full suite**

```bash
uv run python -c "import fastapi" 2>/dev/null || uv sync --extra web
uv run pytest -q
```

Expected: `437 passed, 1 skipped` (402 baseline + 12 from Task 1 + 9 from Task 2 + 11 from Task 3 + 3 from Task 4). No failures anywhere else — Tasks 2–4 already updated every fixture that the new checks interact with.

- [ ] **Step 2: Lint all touched files together**

Run:

```bash
uv run ruff check src/natural_sciences/curriculum_codes.py src/natural_sciences/verifier.py \
  src/natural_sciences/cli.py src/natural_sciences/corrector.py \
  tests/test_natural_sciences_curriculum_codes.py tests/test_natural_sciences_verifier.py \
  tests/test_verifiers_distractor_warnings.py tests/test_natural_sciences_cli.py \
  tests/test_batch_dedup.py tests/test_natural_sciences_corrector_codes.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Document in CLAUDE.md**

In the Key Files table, directly **above** the row `| \`src/natural_sciences/verifier.py\` | Explicit "寬鬆通過、只攔重大問題" stance …` (line 162), insert:

```markdown
| `src/natural_sciences/curriculum_codes.py` | Deterministic 學習內容/學習表現 code validation (issue #92): normalized lookup over the NS curriculum JSON (Unicode Ⅰ–Ⅴ ↔ ASCII roman-numeral spellings), `canonical_lc/lp`, `repair_lc/lp_refs` (canonicalize valid codes, drop unknown, fall back to the sampled pool), `validate_question_codes`. Parse-time repair runs in `cli.py` `_parse_subquestion`/`_parse_question` (cfg-pinned per-小題 codes stay verbatim); the verifier appends `[課綱代碼檢核]` issues to details and forces `passed=False` on unknown/missing codes; the corrector keeps its metadata freeze but canonicalizes codes on LLM-added subquestions. |
```

And in the same table, extend the `src/natural_sciences/verifier.py` row's description by appending before its closing `|`:

```markdown
 Deterministic `[課綱代碼檢核]` check (issue #92) rejects unknown/missing 學習內容/學習表現 codes regardless of the LLM verdict. 
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document NS curriculum-code validation and repair paths (#92)"
```

---

## Verification against issue #92 acceptance criteria (remaining scope only)

| AC | Where |
|---|---|
| Invalid curriculum references are rejected or corrected | Corrected: Task 3 parse-time repair (pool fallback). Rejected: Task 2 verifier `[課綱代碼檢核]` forces `passed=False`. |
| Corrector can repair missing or invalid NS metadata | Task 3 repairs at generation/parse time (the decided repair point); Task 4 makes the corrector canonicalize LLM-added rows so it never introduces invalid metadata; freeze retained for originals. |
| Unit tests: valid + invalid per item family | Task 2 (`_FAMILY_CASES` ×2 in the verifier) and Task 3 (`_FAMILIES` ×2 in the parse path) cover Simple multiple-choice / Complex multiple-choice / Constructed response. |
| Unit tests: invalid 學習內容 / invalid 學習表現 / missing metadata | Task 1 (`validate_question_codes` unknown + missing), Task 2 (verifier reject on unknown LC, missing LP), Task 3 (missing keys → pool fallback), Task 4 (all-invalid added row → flagged). |
| Existing subject verifiers unaffected | Global constraint: no math/SS/common file is touched; Task 5 full suite proves it. |
