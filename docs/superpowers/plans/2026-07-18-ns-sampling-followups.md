# NS Curriculum Sampling Follow-ups (Issue #91) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four remaining gaps of GitHub issue #91 ("Improve natural sciences curriculum sampling and prompt size") found by the 2026-07-18 audit: (1) context-conditional 跨科概念 injection with a safe fallback, (2) an NS sampler determinism unit test with a fixed seed, (3) validity unit tests that every sampled 學習表現/學習內容 code exists in the curriculum JSONs, and (4) grade-aware 學習階段 mapping so grades 10-12 draw from the 第五學習階段 curriculum pool instead of the pinned 第四學習階段.

**Architecture:** All changes live in the natural-sciences pipeline (`src/natural_sciences/`) plus new tests. A new `grade_to_learning_stage(grade)` in `src/natural_sciences/curriculum_loader.py` (mirroring math's `src/sampler.py:52-64`) replaces the schema_meta-pinned `_LEARNING_STAGE` in the sampler and in per-question prompt building. A new `relevant_cross_concepts(rows, lc_codes)` in the same loader narrows the 48-entry 跨科概念 taxonomy to the concept groups matching the sampled 學習內容 code prefixes (full-taxonomy fallback on empty/unknown input). `src/natural_sciences/context_builder.py` gains a public `curriculum_texts(learning_stage, lc_codes)` helper that produces the stage-scoped + concept-narrowed `## 課程綱要參考` JSON blocks; `src/natural_sciences/cli.py::generate_one` threads the grade-derived stage and those texts into `build_text_system_prompt` and `build_subquestion_system_prompt`. The module-level defaults (`_CONTENT_TEXT` / `_PERFORMANCE_TEXT`, pinned to schema_meta's 第四學習階段) are kept unchanged as the no-arg fallback, so `src/natural_sciences/verifier.py` and `corrector.py` (which import them) are untouched.

**Tech Stack:** Python 3.11+, `uv`, pytest, Pydantic v2, ruff (line-length 100). No new dependencies.

**Spec:** GitHub issue #91 acceptance criteria ("Cross-cutting concepts are included only when useful to the selected context"; "Curriculum sampler filters by selected learning stage and grade where available") + verification bullets ("Unit tests for sampler determinism with fixed seed"; "Unit tests that every sampled 學習表現 exists in `learning_performance.json`"; "Unit tests that every sampled 學習內容 exists in `learning_content.json`"), scoped by the 2026-07-18 audit to the four gaps above. Already shipped and **out of scope**: stage filtering of the prompt corpus, 學習表現→學習內容 cross-link derivation, stage-bounded prompt size (commit `03b8c9f`).

## Global Constraints

- Run every command from `/workspace/exam-generation` (repo root). Backend tests run with `uv run pytest ...` — never bare `pytest` (`tests/conftest.py` inserts the repo root into `sys.path`; the uv env has the deps).
- Do **not** run plain `uv sync` — it drops the `web` extras that `tests/server/` needs. The env is already synced; if fastapi imports ever fail, run `uv sync --extra web`.
- Baseline before this plan: `uv run pytest -q` → **402 passed, 1 skipped**. `uv run ruff check tests/` has **12 pre-existing errors** in unrelated test files — scope ruff runs to the files this plan touches, as shown in each step.
- ruff line-length is 100. `src/natural_sciences/context_builder.py` has a file-level `# ruff: noqa: E501` (long Chinese prompt strings); new **test** files have no such waiver — keep their lines ≤ 100 chars.
- Curriculum codes mix ASCII and Unicode Roman numerals: stage-4 codes are mostly `Ab-Ⅳ-1` (Unicode `Ⅳ`) but a few are `Aa-IV-3` (ASCII); stage-5 codes use `Ⅴ` (e.g. `BDa-Ⅴa-1`). Copy every code literal in this plan **byte-exactly**.
- The taxonomy uses full-width parentheses: `物質與能量（INa）`. The regex in Task 4 matches `（…）`, not ASCII `(…)`.
- Do not modify anything under `data/` — all four gaps are code/test-only.
- Backward compatibility: the no-arg calls `build_system_prompt()` / `build_text_system_prompt()` must keep producing the schema_meta default (第四學習階段, grades 7-12) except for one deliberate template fix (the hardcoded `- \`年級\`：7、8 或 9` line becomes grade-driven — Task 5 Step 5).
- Chinese field/parameter names (`學習內容_pool`, `情境`, …) are intentional project conventions — keep them.
- Server code (`server/`) needs **no changes**: `server/utility/routes.py` and `server/generate/routes.py` already resolve stage from grade (via math's `src.sampler.grade_to_learning_stage`), and `server/generate/service.py` reaches the fixes through `ns_sample_params` / `ns_generate_with_corrections`.
- **Scope exclusions:** only the four audit gaps in the Goal are in scope. Explicitly out of scope: everything already shipped for #91 in commit `03b8c9f` (stage filtering of the prompt corpus, 學習表現→學習內容 cross-link derivation, stage-bounded prompt size), the verifier/corrector `_CURRICULUM_PREFIX` stage-4 default, `planner.py`'s `learning_stage` default, embedding-similarity dedup, and any web-UI changes — see `## Out of scope` below. Do not "improve" those while in the files.

## Key facts about the data (verified 2026-07-18, staging)

`data/natural_sciences/curriculum/learning_content.json`:

- `學習階段_to_grades`: `{"第二學習階段": [3, 4], "第三學習階段": [5, 6], "第四學習階段": [7, 8, 9], "第五學習階段": [10, 11, 12]}` (no 第一學習階段 — 自然科學 starts at grade 3).
- `跨科概念`: 48 rows `{課題, 跨科概念, 主題, 次主題}`. Codes sit in full-width parens: 7 跨科概念 codes `INa…INg`; 48 次主題 codes `Aa…Nc`. Group sizes: INa=6, INb=5, INc=7, INd=9, INe=13, INf=5, INg=3.
- `學習內容`: 757 rows, unique `value`s. Per stage: 二=55, 三=72, 四=204, 五=426. Code prefixes (before the first `-`): stages 二/三 use the 跨科概念 code (`INa-II-1`); stage 四 uses the 次主題 code (`Ab-Ⅳ-1`); stage 五 prepends a 科目 letter B/C/P/E to the 次主題 (`BDa-Ⅴa-1` → 次主題 `Da`). Beware: `"INa"[1:] == "Na"` is itself a valid 次主題 code — the filter must check 跨科概念 codes **before** stripping letters.

`data/natural_sciences/curriculum/learning_performance.json`: 99 rows, unique `value`s; per stage 二=20, 三=20, 四=20, 五=39. Stage-5 rows (e.g. `pa-Ⅴa-1`) have `對應學習內容` links that all resolve to stage-5 學習內容 codes.

Current defect being fixed (Task 2): `sample_params(grade=10, seed=42)` today returns `學習內容_pool=['Nc-Ⅳ-2']`, `學習表現_pool=['an-Ⅳ-1']` — 第四學習階段 codes for a grade-10 request.

## Out of scope (noted follow-ups, do NOT do here)

- `src/natural_sciences/verifier.py:18` and `corrector.py:17` build `_CURRICULUM_PREFIX` from the module-level `_CONTENT_TEXT`/`_PERFORMANCE_TEXT` defaults, which stay pinned to 第四學習階段. The lenient NS verifier stance makes this acceptable for now; file a follow-up if stage-5 verification quality suffers.
- `src/natural_sciences/planner.py` `learning_stage` default — the server already passes a grade-derived stage.
- Embedding-similarity dedup, web UI changes, and anything shipped in commit `03b8c9f`.

---

### Task 1: NS grade→學習階段 mapping (`grade_to_learning_stage`)

**Files:**
- Modify: `src/natural_sciences/curriculum_loader.py:11` (insert after `_DATA_DIR`)
- Test: `tests/test_natural_sciences_curriculum_stage.py` (new)

**Interfaces:**
- Consumes: nothing new (pure function; `load_learning_content()` already exists in the same module for the consistency test).
- Produces: `grade_to_learning_stage(grade: int) -> str` — raises `ValueError` outside 3-12. Tasks 2, 5, and 6 import it from `src.natural_sciences.curriculum_loader`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_natural_sciences_curriculum_stage.py`:

```python
"""NS grade → 學習階段 mapping (issue #91)."""

from __future__ import annotations

import pytest

from src.natural_sciences.curriculum_loader import (
    grade_to_learning_stage,
    load_learning_content,
)


def test_grade_to_learning_stage_maps_ns_stages():
    assert grade_to_learning_stage(3) == "第二學習階段"
    assert grade_to_learning_stage(4) == "第二學習階段"
    assert grade_to_learning_stage(5) == "第三學習階段"
    assert grade_to_learning_stage(6) == "第三學習階段"
    assert grade_to_learning_stage(7) == "第四學習階段"
    assert grade_to_learning_stage(9) == "第四學習階段"
    assert grade_to_learning_stage(10) == "第五學習階段"
    assert grade_to_learning_stage(12) == "第五學習階段"


def test_grade_to_learning_stage_rejects_grades_without_ns_curriculum():
    for grade in (0, 1, 2, 13):
        with pytest.raises(ValueError):
            grade_to_learning_stage(grade)


def test_grade_to_learning_stage_matches_curriculum_stage_map():
    """Pin the hardcoded mapping against 學習階段_to_grades in the JSON."""
    stage_map = load_learning_content()["學習階段_to_grades"]
    assert stage_map  # data must be present
    for stage, grades in stage_map.items():
        for grade in grades:
            assert grade_to_learning_stage(grade) == stage
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_natural_sciences_curriculum_stage.py -v`
Expected: FAIL (collection error) — `ImportError: cannot import name 'grade_to_learning_stage' from 'src.natural_sciences.curriculum_loader'`.

- [ ] **Step 3: Write the implementation**

In `src/natural_sciences/curriculum_loader.py`, replace:

```python
_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "natural_sciences" / "curriculum"
```

with:

```python
_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "natural_sciences" / "curriculum"


def grade_to_learning_stage(grade: int) -> str:
    """Map a grade (3-12) to its 自然科學 學習階段.

    Mirrors ``src.sampler.grade_to_learning_stage`` (math), but 自然科學 has
    no 第一學習階段 — the subject starts at grade 3 (學習階段_to_grades in the
    curriculum JSON covers stages 二/三/四/五 only).
    """
    if 3 <= grade <= 4:
        return "第二學習階段"
    if 5 <= grade <= 6:
        return "第三學習階段"
    if 7 <= grade <= 9:
        return "第四學習階段"
    if 10 <= grade <= 12:
        return "第五學習階段"
    raise ValueError(f"grade {grade} has no 自然科學 學習階段 (must be 3-12)")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_natural_sciences_curriculum_stage.py -v`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/natural_sciences/curriculum_loader.py tests/test_natural_sciences_curriculum_stage.py
git commit -m "feat(ns): add grade_to_learning_stage for 自然科學 stages (#91)"
```

---

### Task 2: Grade-aware curriculum stage in the NS sampler

**Files:**
- Modify: `src/natural_sciences/sampler.py:8-14` (imports), `:24-26` (module constants), `:50-66` (`_content_from_performance`), `:91` and `:124-149` (`sample_params` pool draws)
- Test: `tests/test_natural_sciences_sampler.py` (new)

**Interfaces:**
- Consumes: `grade_to_learning_stage(grade: int) -> str` from Task 1.
- Produces: `sample_params(...)` (signature unchanged) now draws `學習表現_pool` / `學習內容_pool` from the 學習階段 derived from the sampled grade. Private helper becomes `_content_from_performance(performance_codes: list[str], learning_stage: str) -> list[str]`. The rng call order is unchanged, so existing seeded behavior for grades 7-9 is identical.

- [ ] **Step 1: Write the failing test**

Create `tests/test_natural_sciences_sampler.py`:

```python
"""NS sampler regression tests: grade-aware stage, determinism, validity (issue #91)."""

from __future__ import annotations

from src.natural_sciences.curriculum_loader import (
    load_learning_content,
    load_learning_performance,
)
from src.natural_sciences.sampler import sample_params


def test_sample_params_grade_derives_stage_pools():
    """Grades 7-9 draw 第四學習階段 codes; grades 10-12 draw 第五學習階段 codes."""
    lc_stage = {
        e["value"]: e["學習階段"] for e in load_learning_content()["學習內容"]
    }
    lp_stage = {
        e["value"]: e["學習階段"] for e in load_learning_performance()["學習表現"]
    }
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
                f"grade={grade}: 學習內容 {code} is {lc_stage[code]}, "
                f"expected {expected_stage}"
            )
        for code in p.學習表現_pool:
            assert lp_stage[code] == expected_stage, (
                f"grade={grade}: 學習表現 {code} is {lp_stage[code]}, "
                f"expected {expected_stage}"
            )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_natural_sciences_sampler.py -v`
Expected: FAIL — `AssertionError: grade=10: 學習內容 Nc-Ⅳ-2 is 第四學習階段, expected 第五學習階段` (exact code may differ; the failure must be a 第四/第五 stage mismatch for grade 10).

- [ ] **Step 3: Update the sampler imports and drop the pinned stage**

In `src/natural_sciences/sampler.py`, replace:

```python
from src.natural_sciences.curriculum_loader import (
    allowed_learning_content,
    allowed_learning_performance,
    load_learning_content,
    load_learning_performance,
)
from src.natural_sciences.schema_loader import load_grades, load_learning_stage, load_schemas
```

with:

```python
from src.natural_sciences.curriculum_loader import (
    allowed_learning_content,
    allowed_learning_performance,
    grade_to_learning_stage,
    load_learning_content,
    load_learning_performance,
)
from src.natural_sciences.schema_loader import load_grades, load_schemas
```

Then replace:

```python
_schemas = load_schemas()
_GRADES: list[int] = load_grades(_schemas)
_LEARNING_STAGE: str = load_learning_stage(_schemas)
```

with:

```python
_schemas = load_schemas()
_GRADES: list[int] = load_grades(_schemas)
```

- [ ] **Step 4: Thread the stage through `_content_from_performance`**

Replace:

```python
def _content_from_performance(performance_codes: list[str]) -> list[str]:
    content_by_value = {
        entry["value"]: entry
        for entry in allowed_learning_content(_LC_DATA, _LEARNING_STAGE)
    }
    performance_by_value = {
        entry["value"]: entry
        for entry in allowed_learning_performance(_LP_DATA, _LEARNING_STAGE)
    }
```

with:

```python
def _content_from_performance(
    performance_codes: list[str],
    learning_stage: str,
) -> list[str]:
    content_by_value = {
        entry["value"]: entry
        for entry in allowed_learning_content(_LC_DATA, learning_stage)
    }
    performance_by_value = {
        entry["value"]: entry
        for entry in allowed_learning_performance(_LP_DATA, learning_stage)
    }
```

(The rest of the function body — the `result` / `seen` loop — is unchanged.)

- [ ] **Step 5: Derive the stage from the sampled grade in `sample_params`**

Replace:

```python
    selected_grade = grade if grade is not None else rng.choice(_GRADES)
```

with:

```python
    selected_grade = grade if grade is not None else rng.choice(_GRADES)
    learning_stage = grade_to_learning_stage(selected_grade)
```

Replace:

```python
        lp_entries = allowed_learning_performance(_LP_DATA, _LEARNING_STAGE)
```

with:

```python
        lp_entries = allowed_learning_performance(_LP_DATA, learning_stage)
```

Replace:

```python
        mapped_content = _content_from_performance(selected_lp_pool)
```

with:

```python
        mapped_content = _content_from_performance(selected_lp_pool, learning_stage)
```

Replace:

```python
            lc_entries = allowed_learning_content(_LC_DATA, _LEARNING_STAGE)
```

with:

```python
            lc_entries = allowed_learning_content(_LC_DATA, learning_stage)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_natural_sciences_sampler.py -v`
Expected: PASS — 1 test green.

- [ ] **Step 7: Run the existing NS + full suite to catch regressions**

Run: `uv run pytest -q`
Expected: **406 passed, 1 skipped** (402 baseline + Task 1's 3 tests + this task's 1 new test; no failures).

- [ ] **Step 8: Commit**

```bash
git add src/natural_sciences/sampler.py tests/test_natural_sciences_sampler.py
git commit -m "feat(ns): derive sampler curriculum stage from sampled grade (#91)"
```

---

### Task 3: Sampler determinism + curriculum-code validity regression tests

These are the two missing verification bullets of issue #91 (fixed-seed determinism; every sampled code exists in the curriculum JSONs). The behavior already holds after Task 2 — this task pins it. Tests go in the file Task 2 created.

**Files:**
- Modify: `tests/test_natural_sciences_sampler.py` (append)

**Interfaces:**
- Consumes: `sample_params` (Task 2), `load_learning_content` / `load_learning_performance` from `src.natural_sciences.curriculum_loader`.
- Produces: regression tests only.

- [ ] **Step 1: Add `pytest` to the file's import block**

In `tests/test_natural_sciences_sampler.py`, replace:

```python
from __future__ import annotations

from src.natural_sciences.curriculum_loader import (
```

with:

```python
from __future__ import annotations

import pytest

from src.natural_sciences.curriculum_loader import (
```

- [ ] **Step 2: Append the determinism and validity tests**

Append to the end of `tests/test_natural_sciences_sampler.py` (after `test_sample_params_grade_derives_stage_pools`):

```python
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
            assert code in lc_values, (
                f"seed={seed}: 學習內容 {code} not in learning_content.json"
            )


def test_sample_params_unknown_grade_raises():
    """Mirror of tests/test_math_sampler.py::test_sample_params_unknown_grade_raises."""
    with pytest.raises(ValueError):
        sample_params(grade=99, seed=0)
```

Note: `sample_params(seed=…)` with no `grade` picks a random grade from 7-12, so the 30-seed loops exercise both 第四 and 第五學習階段 pools.

- [ ] **Step 3: Run the tests to verify they pass**

Run: `uv run pytest tests/test_natural_sciences_sampler.py -v`
Expected: PASS — 6 tests green (1 from Task 2 + 5 new).

- [ ] **Step 4: Lint the new test file**

Run: `uv run ruff check tests/test_natural_sciences_sampler.py tests/test_natural_sciences_curriculum_stage.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add tests/test_natural_sciences_sampler.py
git commit -m "test(ns): pin sampler determinism and curriculum-code validity (#91)"
```

---

### Task 4: 跨科概念 relevance filter (`relevant_cross_concepts`)

**Files:**
- Modify: `src/natural_sciences/curriculum_loader.py` (imports + new functions before the trailing `content_instructions` aliases)
- Test: `tests/test_natural_sciences_cross_concepts.py` (new)

**Interfaces:**
- Consumes: the 48-row `跨科概念` list from `load_learning_content()["跨科概念"]` (rows: `{課題, 跨科概念, 主題, 次主題}`).
- Produces: `relevant_cross_concepts(rows: list[dict], lc_codes: Sequence[str]) -> list[dict]` and private `_paren_code(text: str) -> str`. Task 5's `_stage_filtered_content` calls `relevant_cross_concepts`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_natural_sciences_cross_concepts.py`:

```python
"""跨科概念 relevance filter with full-taxonomy fallback (issue #91)."""

from __future__ import annotations

import re

from src.natural_sciences.curriculum_loader import (
    load_learning_content,
    relevant_cross_concepts,
)

_ROWS = load_learning_content()["跨科概念"]


def _concept_codes(rows):
    return {
        m.group(1)
        for row in rows
        if (m := re.search(r"（\s*([A-Za-z]+)\s*）", row["跨科概念"]))
    }


def test_stage4_prefix_narrows_to_parent_concept_group():
    """次主題 Ab belongs to 物質與能量（INa）→ keep the whole 6-row INa group."""
    rows = relevant_cross_concepts(_ROWS, ["Ab-Ⅳ-1"])
    assert _concept_codes(rows) == {"INa"}
    assert len(rows) == 6


def test_stage23_in_prefix_matches_concept_directly():
    rows = relevant_cross_concepts(_ROWS, ["INf-III-1"])
    assert _concept_codes(rows) == {"INf"}
    assert len(rows) == 5


def test_in_prefix_does_not_leak_into_subtheme_na():
    """'INa'[1:] == 'Na' is a real 次主題 code — INa must match the concept only."""
    rows = relevant_cross_concepts(_ROWS, ["INa-II-1"])
    assert _concept_codes(rows) == {"INa"}


def test_stage5_prefix_strips_subject_letter():
    """BDa = B(生物) + 次主題 Da; Da belongs to 構造與功能（INb）→ 5 rows."""
    rows = relevant_cross_concepts(_ROWS, ["BDa-Ⅴa-1"])
    assert _concept_codes(rows) == {"INb"}
    assert len(rows) == 5


def test_multiple_codes_union_their_concept_groups():
    rows = relevant_cross_concepts(_ROWS, ["Ab-Ⅳ-1", "Ka-Ⅳ-1"])
    assert _concept_codes(rows) == {"INa", "INe"}
    assert len(rows) == 19  # 6 INa rows + 13 INe rows


def test_unknown_prefix_falls_back_to_full_taxonomy():
    assert relevant_cross_concepts(_ROWS, ["ZZZ-IV-1"]) == _ROWS


def test_empty_codes_fall_back_to_full_taxonomy():
    assert relevant_cross_concepts(_ROWS, []) == _ROWS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_natural_sciences_cross_concepts.py -v`
Expected: FAIL (collection error) — `ImportError: cannot import name 'relevant_cross_concepts' from 'src.natural_sciences.curriculum_loader'`.

- [ ] **Step 3: Write the implementation**

In `src/natural_sciences/curriculum_loader.py`, replace the import block:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
```

with:

```python
from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
```

Then replace the trailing aliases:

```python
content_instructions = _base.content_instructions
performance_instructions = _base.performance_instructions
```

with:

```python
_PAREN_CODE_RE = re.compile(r"（\s*([A-Za-z]+)\s*）")


def _paren_code(text: str) -> str:
    """Extract the Latin code in full-width parens: '物質與能量（INa）' → 'INa'."""
    m = _PAREN_CODE_RE.search(text or "")
    return m.group(1) if m else ""


def relevant_cross_concepts(rows: list[dict], lc_codes: Sequence[str]) -> list[dict]:
    """Narrow the 跨科概念 taxonomy to concepts related to 學習內容 codes.

    A 學習內容 code's prefix (the part before the first ``-``) locates it in
    the taxonomy:

    - 國小 codes (``INa-II-1``) carry a 跨科概念 code directly (INa–INg);
    - 國中 codes (``Ab-Ⅳ-1``) carry a 次主題 code (Aa–Nc);
    - 高中 codes (``BDa-Ⅴa-1``) prepend a 科目 letter (B/C/P/E) to the 次主題.

    Every matched 次主題 pulls in its whole parent 跨科概念 group so the
    model keeps local taxonomy context. Safe fallback (issue #91): an empty
    ``lc_codes``, or prefixes that match nothing, return ``rows`` unchanged.
    """
    prefixes = {code.split("-", 1)[0] for code in lc_codes if code and "-" in code}
    if not prefixes:
        return rows

    concept_codes: set[str] = set()
    concept_by_sub: dict[str, str] = {}
    for row in rows:
        concept = _paren_code(row.get("跨科概念", ""))
        sub = _paren_code(row.get("次主題", ""))
        if concept:
            concept_codes.add(concept)
        if concept and sub:
            concept_by_sub[sub] = concept

    wanted: set[str] = set()
    for prefix in prefixes:
        if prefix in concept_codes:
            wanted.add(prefix)
        elif prefix in concept_by_sub:
            wanted.add(concept_by_sub[prefix])
        elif len(prefix) == 3 and prefix[1:] in concept_by_sub:
            # 高中 code: strip the leading 科目 letter (B/C/P/E).
            wanted.add(concept_by_sub[prefix[1:]])

    if not wanted:
        return rows
    filtered = [row for row in rows if _paren_code(row.get("跨科概念", "")) in wanted]
    return filtered or rows


content_instructions = _base.content_instructions
performance_instructions = _base.performance_instructions
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_natural_sciences_cross_concepts.py -v`
Expected: PASS — 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/natural_sciences/curriculum_loader.py tests/test_natural_sciences_cross_concepts.py
git commit -m "feat(ns): add 跨科概念 relevance filter with full-taxonomy fallback (#91)"
```

---

### Task 5: Stage-aware, context-conditional curriculum injection in `context_builder`

**Files:**
- Modify: `src/natural_sciences/context_builder.py:21-26` (imports), `:49-57` (`_stage_filtered_content`), `:75-79` (module constants + new `curriculum_texts`), `:147` (年級 template line), `:258-274` (`build_system_prompt`), `:381` (F841 cleanup), `:456-458` (user-prompt stage), `:559-575` (`build_text_system_prompt`), `:812` (subquestion user-prompt stage)
- Test: `tests/test_natural_sciences_curriculum_prompt.py` (new)

**Interfaces:**
- Consumes: `grade_to_learning_stage` (Task 1), `relevant_cross_concepts` (Task 4), existing `_stage_filtered_performance`, `_build_curriculum_section`, `SampledParams`.
- Produces:
  - `curriculum_texts(learning_stage: str, lc_codes: Sequence[str] | None = None) -> tuple[str, str]` — `(content_text, performance_text)` JSON strings; Task 6's `generate_one` calls it.
  - `_stage_filtered_content(data: dict, learning_stage: str, lc_codes: Sequence[str] | None = None) -> dict` (extended signature; existing 2-arg callers unchanged).
  - `_grades_for(grades: list[int] | None, learning_stage: str | None) -> list[int]` (private).
  - `build_user_prompt` / `build_text_user_prompt` now render `{grade}年級（stage derived from params.grade）`; `build_subquestion_user_prompt` likewise. `build_system_prompt()` / `build_text_system_prompt()` **no-arg behavior unchanged**, but when called with `learning_stage=` and no `grades=`, grade names come from `學習階段_to_grades`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_natural_sciences_curriculum_prompt.py`:

```python
"""Stage-aware, context-conditional curriculum injection (issue #91)."""

from __future__ import annotations

import json
import random
from pathlib import Path

from src.natural_sciences.context_builder import (
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_system_prompt,
    build_text_system_prompt,
    build_user_prompt,
    curriculum_texts,
)
from src.natural_sciences.sampler import sample_params


def test_curriculum_texts_scope_stage_and_cross_concepts():
    content_text, performance_text = curriculum_texts("第五學習階段", ["BDa-Ⅴa-1"])
    content = json.loads(content_text)
    performance = json.loads(performance_text)
    assert content["學習內容"] and performance["學習表現"]
    assert all(r["學習階段"] == "第五學習階段" for r in content["學習內容"])
    assert all(r["學習階段"] == "第五學習階段" for r in performance["學習表現"])
    # BDa → 次主題 Da → 構造與功能（INb）group only (5 of 48 rows).
    assert len(content["跨科概念"]) == 5
    assert all("INb" in r["跨科概念"] for r in content["跨科概念"])


def test_curriculum_texts_without_codes_keep_full_taxonomy():
    content_text, _ = curriculum_texts("第四學習階段")
    assert len(json.loads(content_text)["跨科概念"]) == 48


def test_default_system_prompt_unchanged_without_stage():
    """No-arg call keeps the schema_meta default (第四學習階段, grades 7-12)."""
    prompt = build_system_prompt()
    assert "專門為第四學習階段" in prompt
    assert "7年級、8年級、9年級、10年級、11年級、12年級" in prompt


def test_text_system_prompt_stage5_uses_stage_grades():
    content_text, performance_text = curriculum_texts("第五學習階段")
    prompt = build_text_system_prompt(
        learning_stage="第五學習階段",
        content_text=content_text,
        performance_text=performance_text,
    )
    assert "專門為第五學習階段（10年級、11年級、12年級）" in prompt


def test_subquestion_system_prompt_accepts_stage_scoped_texts():
    content_text, performance_text = curriculum_texts("第五學習階段", ["BDa-Ⅴa-1"])
    prompt = build_subquestion_system_prompt(
        learning_stage="第五學習階段",
        content_text=content_text,
        performance_text=performance_text,
    )
    assert "目前學習階段：第五學習階段" in prompt
    assert '"學習階段": "第五學習階段"' in prompt
    assert '"學習階段": "第四學習階段"' not in prompt


def test_user_prompt_stage_follows_grade(tmp_path: Path):
    params = sample_params(grade=11, seed=3)
    prompt, _ = build_user_prompt(params, tmp_path, rng=random.Random(3))
    assert "11年級（第五學習階段）" in prompt


def test_subquestion_user_prompt_stage_follows_grade(tmp_path: Path):
    params = sample_params(grade=10, seed=3)
    plan = {"序號": 1, "題型": params.題型.value, "出題概念": "測試"}
    prompt, _ = build_subquestion_user_prompt(
        核心問題="核心",
        文本="文本",
        取材來源=["來源"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(3),
    )
    assert "10年級（第五學習階段）" in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_natural_sciences_curriculum_prompt.py -v`
Expected: FAIL (collection error) — `ImportError: cannot import name 'curriculum_texts' from 'src.natural_sciences.context_builder'`.

- [ ] **Step 3: Extend the curriculum_loader import in `context_builder.py`**

Replace:

```python
from src.natural_sciences.curriculum_loader import (
    content_instructions,
    load_learning_content,
    load_learning_performance,
    performance_instructions,
)
```

with:

```python
from src.natural_sciences.curriculum_loader import (
    content_instructions,
    grade_to_learning_stage,
    load_learning_content,
    load_learning_performance,
    performance_instructions,
    relevant_cross_concepts,
)
```

- [ ] **Step 4: Extend `_stage_filtered_content` and add `curriculum_texts`**

Replace:

```python
def _stage_filtered_content(data: dict, learning_stage: str) -> dict:
    return {
        "學習階段_to_grades": data.get("學習階段_to_grades", {}),
        "跨科概念": data.get("跨科概念", []),
        "學習內容": [
            row for row in data.get("學習內容", [])
            if row.get("學習階段") == learning_stage
        ],
    }
```

with:

```python
def _stage_filtered_content(
    data: dict,
    learning_stage: str,
    lc_codes: Sequence[str] | None = None,
) -> dict:
    cross_concepts = data.get("跨科概念", [])
    if lc_codes:
        cross_concepts = relevant_cross_concepts(cross_concepts, lc_codes)
    return {
        "學習階段_to_grades": data.get("學習階段_to_grades", {}),
        "跨科概念": cross_concepts,
        "學習內容": [
            row for row in data.get("學習內容", [])
            if row.get("學習階段") == learning_stage
        ],
    }
```

Then replace:

```python
_CONTENT_TEXT: str = json.dumps(
    _stage_filtered_content(_CONTENT_DATA, _LEARNING_STAGE),
    ensure_ascii=False,
    indent=2,
)
```

with:

```python
_CONTENT_TEXT: str = json.dumps(
    _stage_filtered_content(_CONTENT_DATA, _LEARNING_STAGE),
    ensure_ascii=False,
    indent=2,
)
_STAGE_TO_GRADES: dict[str, list[int]] = _CONTENT_DATA.get("學習階段_to_grades", {})


def curriculum_texts(
    learning_stage: str,
    lc_codes: Sequence[str] | None = None,
) -> tuple[str, str]:
    """Return (content_text, performance_text) JSON blocks for one 學習階段.

    `lc_codes` narrows the injected 跨科概念 taxonomy to the concept groups
    related to the sampled 學習內容 codes; empty or unknown codes fall back
    to the full 48-entry taxonomy (issue #91).
    """
    content = json.dumps(
        _stage_filtered_content(_CONTENT_DATA, learning_stage, lc_codes=lc_codes),
        ensure_ascii=False,
        indent=2,
    )
    performance = json.dumps(
        _stage_filtered_performance(_PERFORMANCE_DATA, learning_stage),
        ensure_ascii=False,
        indent=2,
    )
    return content, performance
```

(`Sequence` is already imported at the top of this file from `collections.abc`.)

- [ ] **Step 5: Make the hardcoded 年級 line grade-driven**

In `SYSTEM_PROMPT_TEMPLATE` (the `## 各小題必須標記` section, line 147), replace:

```
- `年級`：7、8 或 9
```

with:

```
- `年級`：{grade_names}其中之一
```

(`.format()` allows reusing the `grade_names` key; `TEXT_SYSTEM_PROMPT_TEMPLATE` is derived from `SYSTEM_PROMPT_TEMPLATE` via `.replace()` of the output-format block only, so it inherits this fix automatically.)

- [ ] **Step 6: Stage-aware grade names in the two system-prompt builders**

Replace:

```python
def build_system_prompt(
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
) -> str:
    g = grades if grades is not None else _GRADES
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    grade_names = "、".join(f"{x}年級" for x in g)
    c_text = content_text if content_text is not None else _CONTENT_TEXT
    p_text = performance_text if performance_text is not None else _PERFORMANCE_TEXT
    curriculum_section = _build_curriculum_section(c_text, p_text)
    return SYSTEM_PROMPT_TEMPLATE.format(
```

with:

```python
def _grades_for(grades: list[int] | None, learning_stage: str | None) -> list[int]:
    """Grade list for system prompts: explicit grades win, then the stage's
    own grades (學習階段_to_grades), then the schema_meta default."""
    if grades is not None:
        return grades
    if learning_stage is not None:
        return _STAGE_TO_GRADES.get(learning_stage, _GRADES)
    return _GRADES


def build_system_prompt(
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
) -> str:
    g = _grades_for(grades, learning_stage)
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    grade_names = "、".join(f"{x}年級" for x in g)
    c_text = content_text if content_text is not None else _CONTENT_TEXT
    p_text = performance_text if performance_text is not None else _PERFORMANCE_TEXT
    curriculum_section = _build_curriculum_section(c_text, p_text)
    return SYSTEM_PROMPT_TEMPLATE.format(
```

Then, in `build_text_system_prompt` (its body is identical except it returns `TEXT_SYSTEM_PROMPT_TEMPLATE.format(`), replace:

```python
    g = grades if grades is not None else _GRADES
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    grade_names = "、".join(f"{x}年級" for x in g)
    c_text = content_text if content_text is not None else _CONTENT_TEXT
    p_text = performance_text if performance_text is not None else _PERFORMANCE_TEXT
    curriculum_section = _build_curriculum_section(c_text, p_text)
    return TEXT_SYSTEM_PROMPT_TEMPLATE.format(
```

with:

```python
    g = _grades_for(grades, learning_stage)
    stage = learning_stage if learning_stage is not None else _LEARNING_STAGE
    grade_names = "、".join(f"{x}年級" for x in g)
    c_text = content_text if content_text is not None else _CONTENT_TEXT
    p_text = performance_text if performance_text is not None else _PERFORMANCE_TEXT
    curriculum_section = _build_curriculum_section(c_text, p_text)
    return TEXT_SYSTEM_PROMPT_TEMPLATE.format(
```

- [ ] **Step 7: Derive the stage from `params.grade` in both user-prompt builders**

In `build_user_prompt` (line ~456), replace:

```python
    text = USER_PROMPT_TEMPLATE.format(
        grade=params.grade,
        learning_stage=_LEARNING_STAGE,
```

with:

```python
    text = USER_PROMPT_TEMPLATE.format(
        grade=params.grade,
        learning_stage=grade_to_learning_stage(params.grade),
```

In `build_subquestion_user_prompt` (the f-string at line ~812), replace:

```python
- **年級重心**：{params.grade}年級（{_LEARNING_STAGE}）
```

with:

```python
- **年級重心**：{params.grade}年級（{grade_to_learning_stage(params.grade)}）
```

- [ ] **Step 8: Remove the pre-existing F841 dead variable (line 381)**

While in this file, delete the unused assignment ruff already flags (leftover from an earlier refactor; only `has_structural_config` is used afterwards). Replace:

```python
        has_config = has_structural_config or bool(cfg.text_word_limit)
        if cfg.question_type:
```

with:

```python
        if cfg.question_type:
```

- [ ] **Step 9: Run the new tests, the existing NS tests, and lint**

Run: `uv run pytest tests/test_natural_sciences_curriculum_prompt.py tests/test_natural_sciences_context_builder.py tests/test_natural_sciences_context_builder_difficulty.py tests/test_natural_sciences_distractor_prompt.py -v`
Expected: PASS — 7 new tests + all existing tests green.

Run: `uv run ruff check src/natural_sciences/ tests/test_natural_sciences_curriculum_prompt.py`
Expected: `All checks passed!` (the F841 baseline error is gone).

- [ ] **Step 10: Commit**

```bash
git add src/natural_sciences/context_builder.py tests/test_natural_sciences_curriculum_prompt.py
git commit -m "feat(ns): stage-aware prompts + context-conditional 跨科概念 injection (#91)"
```

---

### Task 6: CLI wiring, docs, and full-suite verification

**Files:**
- Modify: `src/natural_sciences/cli.py:18-27` (imports), `:389-391` (dry-run branch), `:413` (real path), `:438` (subquestion system prompt)
- Modify: `CLAUDE.md` (3 Key Files rows + NS sampler-constraints paragraph)
- Test: `tests/test_natural_sciences_cli_stage.py` (new)

**Interfaces:**
- Consumes: `grade_to_learning_stage` (Task 1), `curriculum_texts` (Task 5), existing `build_text_system_prompt` / `build_subquestion_system_prompt` keyword overrides (`learning_stage=`, `content_text=`, `performance_text=`).
- Produces: `generate_one` (signature unchanged) computes `learning_stage = grade_to_learning_stage(params.grade)` and `content_text, performance_text = curriculum_texts(learning_stage, params.學習內容_pool)` once, and passes them to both pipeline stages. The `_LEARNING_STAGE` import is removed from `cli.py`. The server path (`server/generate/service.py` → `ns_generate_with_corrections`) inherits this automatically.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_natural_sciences_cli_stage.py`:

```python
"""generate_one threads the grade-derived stage into both stages (issue #91)."""

from __future__ import annotations

from pathlib import Path

import src.natural_sciences.cli as ns_cli
from src.config import Config
from src.natural_sciences.sampler import sample_params


class _FakeTextClient:
    """Non-LLMClient fake → cli uses the embedded-subquestions path."""

    def get_observer(self):
        return None

    def generate_json(self, *_args, **_kwargs):
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試"],
            "subquestions": [
                {
                    "序號": 1,
                    "題型": "Simple multiple-choice",
                    "出題概念": "測試",
                    "題目": "題目？",
                    "答案": "A",
                    "答案解析": "解析",
                },
            ],
        }


def test_dry_run_prompts_use_grade_derived_stage():
    config = Config(data_dir=Path("data"))
    params = sample_params(grade=10, seed=7)
    out = ns_cli.generate_one(config, None, params, "ns_test_001", dry_run=True)
    assert isinstance(out, str)
    assert "專門為第五學習階段（10年級、11年級、12年級）" in out
    assert "10年級（第五學習階段）" in out


def test_generate_one_passes_grade_stage_to_sub_system(tmp_path, monkeypatch):
    captured: dict = {}
    real = ns_cli.build_subquestion_system_prompt

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(ns_cli, "build_subquestion_system_prompt", spy)
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(grade=11, seed=2)
    question = ns_cli.generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="ns_test_002",
        skip_verify=True,
    )
    assert not isinstance(question, str)
    assert captured["learning_stage"] == "第五學習階段"
    assert '"學習階段": "第五學習階段"' in captured["content_text"]
    assert '"學習階段": "第四學習階段"' not in captured["content_text"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_natural_sciences_cli_stage.py -v`
Expected: FAIL — test 1: `AssertionError` (dry-run output says `專門為第四學習階段` today); test 2: `AssertionError` on `captured["learning_stage"]` — today's call passes `learning_stage="第四學習階段"`, not `第五學習階段`.

- [ ] **Step 3: Update the cli imports**

In `src/natural_sciences/cli.py`, replace:

```python
from src.natural_sciences.context_builder import (
    _LEARNING_STAGE,
    LC_INSTRUCTIONS,
    LP_INSTRUCTIONS,
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
)
from src.natural_sciences.corrector import correct_question
```

with:

```python
from src.natural_sciences.context_builder import (
    LC_INSTRUCTIONS,
    LP_INSTRUCTIONS,
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
    curriculum_texts,
)
from src.natural_sciences.corrector import correct_question
from src.natural_sciences.curriculum_loader import grade_to_learning_stage
```

- [ ] **Step 4: Compute the stage once and pass it to both pipeline stages**

In `generate_one`, replace:

```python
    params = _with_text_word_limit(params, text_word_limit)
    if dry_run:
        text_system = build_text_system_prompt()
```

with:

```python
    params = _with_text_word_limit(params, text_word_limit)
    learning_stage = grade_to_learning_stage(params.grade)
    content_text, performance_text = curriculum_texts(learning_stage, params.學習內容_pool)
    if dry_run:
        text_system = build_text_system_prompt(
            learning_stage=learning_stage,
            content_text=content_text,
            performance_text=performance_text,
        )
```

Replace (the non-dry-run path):

```python
    print(f"  Generating question {question_id}...", file=sys.stderr)

    text_system = build_text_system_prompt()
```

with:

```python
    print(f"  Generating question {question_id}...", file=sys.stderr)

    text_system = build_text_system_prompt(
        learning_stage=learning_stage,
        content_text=content_text,
        performance_text=performance_text,
    )
```

Replace:

```python
    sub_system = build_subquestion_system_prompt(learning_stage=_LEARNING_STAGE)
```

with:

```python
    sub_system = build_subquestion_system_prompt(
        learning_stage=learning_stage,
        content_text=content_text,
        performance_text=performance_text,
    )
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_natural_sciences_cli_stage.py -v`
Expected: PASS — 2 tests green.

- [ ] **Step 6: Update `CLAUDE.md` (4 surgical edits)**

Edit 1 — in the Key Files table, replace:

```
| `src/natural_sciences/curriculum_loader.py` | Thin shim over `src.common.curriculum_loader`; overrides `allowed_learning_content` / `allowed_learning_performance` to skip subject filtering (科目 is fixed as 自然科學) |
```

with:

```
| `src/natural_sciences/curriculum_loader.py` | Thin shim over `src.common.curriculum_loader`; overrides `allowed_learning_content` / `allowed_learning_performance` to skip subject filtering (科目 is fixed as 自然科學). Owns `grade_to_learning_stage` (grades 3-12 → 學習階段 二/三/四/五; NS has no 第一 stage) and `relevant_cross_concepts` (narrows the 48-entry 跨科概念 taxonomy to the concept groups matching 學習內容-code prefixes; full-taxonomy fallback on empty/unknown codes) |
```

Edit 2 — in the `src/natural_sciences/sampler.py` row, replace the fragment:

```
PISA-Science sampler: picks grade, 情境 + 情境子類別 (parent-child constrained), 題型,
```

with:

```
PISA-Science sampler: picks grade (學習階段 derived per-question via `grade_to_learning_stage`, so grades 10-12 draw 第五學習階段 pools), 情境 + 情境子類別 (parent-child constrained), 題型,
```

Edit 3 — in the `src/natural_sciences/context_builder.py` row, replace the fragment:

```
PISA-Science prompt assembly; injects `跨科概念` taxonomy + `## 課程綱要參考` block (學習內容 + 學習表現 + 跨科概念) into system prompt;
```

with:

```
PISA-Science prompt assembly; `curriculum_texts(learning_stage, lc_codes)` builds the `## 課程綱要參考` block (學習內容 + 學習表現 filtered to the grade-derived 學習階段; 跨科概念 narrowed to the sampled codes' concept groups with full-taxonomy fallback), injected into the system prompt;
```

Edit 4 — in the "Sampler Constraints" natural-sciences paragraph, replace the fragment:

```
**學習表現_pool** (1–2 codes from `learning_performance.json` filtered by 學習階段), **學習內容_pool**
```

with:

```
**學習表現_pool** (1–2 codes from `learning_performance.json` filtered by the 學習階段 derived from the sampled grade via `grade_to_learning_stage` — grades 7-9 → 第四學習階段, 10-12 → 第五學習階段), **學習內容_pool**
```

- [ ] **Step 7: Full-suite verification**

Run: `uv run pytest -q`
Expected: **427 passed, 1 skipped** (402 baseline + 25 new tests: 3 + 1 + 5 + 7 + 7 + 2). Zero failures.

Run: `uv run ruff check src/natural_sciences/ tests/test_natural_sciences_curriculum_stage.py tests/test_natural_sciences_sampler.py tests/test_natural_sciences_cross_concepts.py tests/test_natural_sciences_curriculum_prompt.py tests/test_natural_sciences_cli_stage.py`
Expected: `All checks passed!`

- [ ] **Step 8: Manual dry-run sanity check (no API key needed)**

Run: `uv run python -m src.natural_sciences.cli generate --grade 11 --seed 5 --dry-run 2>/dev/null | head -5`
Expected: the first system-prompt line contains `專門為第五學習階段（10年級、11年級、12年級）`.

Run: `uv run python -m src.natural_sciences.cli generate --grade 8 --seed 5 --dry-run 2>/dev/null | grep -c "8年級（第四學習階段）"`
Expected: `1` (the `- **年級重心**：8年級（第四學習階段）` line of the user prompt).

- [ ] **Step 9: Commit**

```bash
git add src/natural_sciences/cli.py tests/test_natural_sciences_cli_stage.py CLAUDE.md
git commit -m "feat(ns): thread grade-derived stage through generate_one; update docs (#91)"
```
