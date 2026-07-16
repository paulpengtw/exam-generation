# Batch-level Scope Dedup in Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a batch generates `count > 1` questions, feed each new generation a short summary of its already-accepted siblings (核心問題 / 出題概念 + 學習內容 codes) so the LLM varies angle/題材 across the batch (GitHub issue #111).

**Architecture:** A subject-agnostic helper module `src/common/batch_dedup.py` defines the `PriorScope` model, per-subject extractors, and a formatter that renders the `## 已生成題目（請避免相似範圍）` block. Each subject's user-prompt builder (`src/context_builder.build_user_prompt` for math, `src/social_studies/context_builder.build_text_user_prompt` for SS, `src/natural_sciences/context_builder.build_text_user_prompt` for NS) grows an optional `prior_scopes` argument; `generate_with_corrections` and `generate_one` in each subject's CLI thread it through. The math/SS/NS CLI `main()` loops and the server's `generate_question_stream` worker accumulate a shared `list[PriorScope]` — sequentially in the three CLI mains, and via a `threading.Lock`-guarded shared list in the server (best-effort under concurrent `run_in_executor` workers).

**Tech Stack:** Python 3.11+, Pydantic v2, pytest via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-07-15-batch-dedup-design.md`

## Global Constraints

- Prompt-level dedup only. Embedding-similarity retry (Phase 2) is out of scope for this plan.
- Applies to all three subjects: math, social studies, natural sciences.
- `PriorScope` shape: `{summary: str, codes: list[str]}`. `summary` is the 社會/自然 `核心問題` when non-empty, otherwise the math `出題概念` (both are strings).
- `codes` is the deduplicated list of `學習內容[*].編碼` values — from `ExamQuestion.學習內容` for math, from `subquestions[*].學習內容` aggregated across all 小題 for SS/NS.
- Prompt injection points: math's `build_user_prompt`; SS's `build_text_user_prompt`; NS's `build_text_user_prompt`. 子題產生器 prompts (`build_subquestion_user_prompt` on SS/NS) are NOT changed.
- Cap the rendered block at the most recent 10 entries (`_PRIOR_SCOPES_CAP = 10`). Older entries are dropped from the rendered block only, not from the accumulator.
- When `prior_scopes` is empty or `None`, the section is omitted entirely and the emitted prompt is byte-identical to today. This is the count=1 regression guarantee.
- Extraction failures (missing fields, unexpected types) return `None` and log via `logging.getLogger(__name__).debug(...)`; the caller skips that entry.
- Sampling-level coordination (which codes get scheduled across a batch) is issue #112's `BatchSampler` — not touched here.
- The rendered block format is:
  ```
  ## 已生成題目（請避免相似範圍）

  1. 核心問題：<summary>；學習內容：<code>, <code>, …
  2. …
  ```
  When `codes` is empty for an entry, the entry renders `學習內容：（無）`.

---

### Task 1: Shared `PriorScope` helper module

**Files:**
- Create: `src/common/batch_dedup.py`
- Create: `tests/test_batch_dedup.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `PriorScope(BaseModel)` with fields `summary: str`, `codes: list[str]`.
  - `_PRIOR_SCOPES_CAP: int = 10` (module-level constant).
  - `extract_math_prior_scope(question) -> PriorScope | None`.
  - `extract_ss_prior_scope(question) -> PriorScope | None`.
  - `extract_ns_prior_scope(question) -> PriorScope | None`.
  - `format_prior_scopes_block(scopes: Sequence[PriorScope]) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_batch_dedup.py`:

```python
"""Unit tests for the batch-level prior-scope helper (issue #111)."""

from __future__ import annotations

import logging

from src.common.batch_dedup import (
    PriorScope,
    _PRIOR_SCOPES_CAP,
    extract_math_prior_scope,
    extract_ns_prior_scope,
    extract_ss_prior_scope,
    format_prior_scopes_block,
)


def test_format_returns_empty_string_when_no_scopes() -> None:
    assert format_prior_scopes_block([]) == ""


def test_format_renders_summary_and_codes() -> None:
    scopes = [
        PriorScope(summary="人口老化如何影響社區資源？", codes=["歷Ka-Ⅳ-1", "地Ab-Ⅳ-2"]),
        PriorScope(summary="能源轉型的取捨", codes=["自Nc-Ⅳ-3"]),
    ]
    block = format_prior_scopes_block(scopes)
    assert "## 已生成題目（請避免相似範圍）" in block
    assert "1. 核心問題：人口老化如何影響社區資源？；學習內容：歷Ka-Ⅳ-1, 地Ab-Ⅳ-2" in block
    assert "2. 核心問題：能源轉型的取捨；學習內容：自Nc-Ⅳ-3" in block


def test_format_renders_empty_codes_as_placeholder() -> None:
    block = format_prior_scopes_block([PriorScope(summary="測試主題", codes=[])])
    assert "1. 核心問題：測試主題；學習內容：（無）" in block


def test_format_caps_at_ten_most_recent_entries() -> None:
    scopes = [
        PriorScope(summary=f"主題{i}", codes=[f"X-{i}"]) for i in range(1, 13)
    ]
    assert _PRIOR_SCOPES_CAP == 10
    block = format_prior_scopes_block(scopes)
    # Oldest two dropped; the surviving ten start with 主題3 and end with 主題12.
    assert "主題1；" not in block
    assert "主題2；" not in block
    assert "1. 核心問題：主題3；" in block
    assert "10. 核心問題：主題12；" in block


def test_extract_math_uses_出題概念_and_學習內容_codes() -> None:
    from src.schemas import ExamQuestion, LearningContentItem

    question = ExamQuestion.model_construct(
        id="q_test",
        情境=[],
        題型種類="單一題",
        題型="選擇題",
        數學思考=[],
        學習內容=[
            LearningContentItem(編碼="N-7-1", 說明="整數運算"),
            LearningContentItem(編碼="N-7-2", 說明="有理數"),
            LearningContentItem(編碼="N-7-1", 說明="整數運算"),  # duplicate
        ],
        題目=[],
        正確解題分析=[],
        出題概念="評量學生能否比較有理數大小",
    )
    scope = extract_math_prior_scope(question)
    assert scope is not None
    assert scope.summary == "評量學生能否比較有理數大小"
    assert scope.codes == ["N-7-1", "N-7-2"]  # order preserved, deduped


def test_extract_math_returns_none_when_both_summary_and_codes_missing(caplog) -> None:
    from src.schemas import ExamQuestion

    question = ExamQuestion.model_construct(
        id="q_empty",
        情境=[],
        題型種類="單一題",
        題型="選擇題",
        數學思考=[],
        學習內容=[],
        題目=[],
        正確解題分析=[],
        出題概念="",
    )
    with caplog.at_level(logging.DEBUG, logger="src.common.batch_dedup"):
        scope = extract_math_prior_scope(question)
    assert scope is None
    assert any("skipping prior scope" in rec.message for rec in caplog.records)


def test_extract_ss_uses_核心問題_and_aggregated_subquestion_codes() -> None:
    from src.social_studies.schemas import (
        ExamQuestion,
        LearningContentRef,
        SubQuestion,
    )

    question = ExamQuestion.model_construct(
        id="ss_test",
        核心問題="工業革命如何改變勞動條件？",
        文本="…",
        取材來源=[],
        subquestions=[
            SubQuestion.model_construct(
                id="ss_test-01",
                序號=1,
                年級=8,
                科目=["歷史"],
                核心素養=[],
                學習內容=[LearningContentRef(編碼="歷Ka-Ⅳ-1", 說明="工業革命")],
                學習表現=[],
                題型="選擇題",
                題目="…",
            ),
            SubQuestion.model_construct(
                id="ss_test-02",
                序號=2,
                年級=8,
                科目=["公民與社會"],
                核心素養=[],
                學習內容=[
                    LearningContentRef(編碼="公Ab-Ⅳ-2", 說明="勞動權益"),
                    LearningContentRef(編碼="歷Ka-Ⅳ-1", 說明="工業革命"),
                ],
                學習表現=[],
                題型="選擇題",
                題目="…",
            ),
        ],
        情境=[],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=[],
        文本形式="連續文本",
    )
    scope = extract_ss_prior_scope(question)
    assert scope is not None
    assert scope.summary == "工業革命如何改變勞動條件？"
    assert scope.codes == ["歷Ka-Ⅳ-1", "公Ab-Ⅳ-2"]


def test_extract_ns_uses_核心問題_and_aggregated_subquestion_codes() -> None:
    from src.natural_sciences.schemas import (
        ExamQuestion,
        LearningContentRef,
        SubQuestion,
    )

    question = ExamQuestion.model_construct(
        id="ns_test",
        核心問題="海洋酸化對生態的影響",
        文本="…",
        取材來源=[],
        subquestions=[
            SubQuestion.model_construct(
                id="ns_test-01",
                序號=1,
                年級=8,
                科目=["自然科學"],
                科學能力=["能力一"],
                核心素養=[],
                學習內容=[LearningContentRef(編碼="INc-Ⅳ-1", 說明="…")],
                學習表現=[],
                題型="Simple-multiple-choice",
                題目="…",
            ),
        ],
        情境=[],
        情境子類別="Environment",
        題型種類="題組題",
        題型="Simple-multiple-choice",
        科學能力=["能力一"],
    )
    scope = extract_ns_prior_scope(question)
    assert scope is not None
    assert scope.summary == "海洋酸化對生態的影響"
    assert scope.codes == ["INc-Ⅳ-1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_batch_dedup.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.common.batch_dedup'`.

- [ ] **Step 3: Write the module**

Create `src/common/batch_dedup.py`:

```python
"""Batch-level scope dedup helper for issue #111.

Each subject's batch loop accumulates a list of `PriorScope` — a small summary
of already-accepted siblings — and passes it to the next question's user prompt
so the LLM can vary angle/題材 even when learning-content codes overlap.

Prompt-level only. Embedding-similarity retry is a separate future issue.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover — import guard for type hints only
    from src.natural_sciences.schemas import ExamQuestion as NSExamQuestion
    from src.schemas import ExamQuestion as MathExamQuestion
    from src.social_studies.schemas import ExamQuestion as SSExamQuestion

logger = logging.getLogger(__name__)

_PRIOR_SCOPES_CAP: int = 10


class PriorScope(BaseModel):
    """A one-line summary of an already-accepted batch sibling."""

    summary: str = ""
    codes: list[str] = Field(default_factory=list)


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def extract_math_prior_scope(question: "MathExamQuestion") -> PriorScope | None:
    """Extract a PriorScope from a completed math ExamQuestion."""
    try:
        summary = (getattr(question, "出題概念", "") or "").strip()
        raw_codes = [
            (item.編碼 or "").strip()
            for item in getattr(question, "學習內容", []) or []
        ]
        codes = _dedup_preserve_order(raw_codes)
    except Exception as exc:
        logger.debug("skipping prior scope for math question: %s", exc)
        return None
    if not summary and not codes:
        logger.debug("skipping prior scope for math question: both summary and codes empty")
        return None
    return PriorScope(summary=summary, codes=codes)


def extract_ss_prior_scope(question: "SSExamQuestion") -> PriorScope | None:
    """Extract a PriorScope from a completed social-studies ExamQuestion."""
    try:
        summary = (getattr(question, "核心問題", "") or "").strip()
        raw_codes: list[str] = []
        for sub in getattr(question, "subquestions", []) or []:
            for ref in getattr(sub, "學習內容", []) or []:
                raw_codes.append((ref.編碼 or "").strip())
        codes = _dedup_preserve_order(raw_codes)
    except Exception as exc:
        logger.debug("skipping prior scope for social-studies question: %s", exc)
        return None
    if not summary and not codes:
        logger.debug(
            "skipping prior scope for social-studies question: both summary and codes empty"
        )
        return None
    return PriorScope(summary=summary, codes=codes)


def extract_ns_prior_scope(question: "NSExamQuestion") -> PriorScope | None:
    """Extract a PriorScope from a completed natural-sciences ExamQuestion."""
    try:
        summary = (getattr(question, "核心問題", "") or "").strip()
        raw_codes: list[str] = []
        for sub in getattr(question, "subquestions", []) or []:
            for ref in getattr(sub, "學習內容", []) or []:
                raw_codes.append((ref.編碼 or "").strip())
        codes = _dedup_preserve_order(raw_codes)
    except Exception as exc:
        logger.debug("skipping prior scope for natural-sciences question: %s", exc)
        return None
    if not summary and not codes:
        logger.debug(
            "skipping prior scope for natural-sciences question: both summary and codes empty"
        )
        return None
    return PriorScope(summary=summary, codes=codes)


def format_prior_scopes_block(scopes: Sequence[PriorScope]) -> str:
    """Render the `## 已生成題目（請避免相似範圍）` block for the user prompt.

    Returns an empty string when the input list is empty — the count=1
    regression guarantee. Only the most recent `_PRIOR_SCOPES_CAP` entries
    appear in the rendered block.
    """
    if not scopes:
        return ""
    recent = list(scopes)[-_PRIOR_SCOPES_CAP:]
    lines = ["## 已生成題目（請避免相似範圍）", ""]
    for i, scope in enumerate(recent, start=1):
        codes_str = ", ".join(scope.codes) if scope.codes else "（無）"
        lines.append(f"{i}. 核心問題：{scope.summary}；學習內容：{codes_str}")
    return "\n".join(lines) + "\n"
```

Also ensure `src/common/__init__.py` exists (it should already — the subject-agnostic loaders live there). If missing, create an empty file:

Run: `test -f /workspace/exam-generation/src/common/__init__.py || touch /workspace/exam-generation/src/common/__init__.py`

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch_dedup.py -q`
Expected: PASS — all 8 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/common/batch_dedup.py tests/test_batch_dedup.py
git commit -m "feat(batch-dedup): add PriorScope helper for batch-level prompt dedup (#111)"
```

---

### Task 2: Wire `prior_scopes` into math `build_user_prompt`

**Files:**
- Modify: `src/context_builder.py` (`build_user_prompt` signature + template)
- Modify: `tests/test_batch_dedup.py` (append prompt-level test)

**Interfaces:**
- Consumes: `PriorScope`, `format_prior_scopes_block` from `src.common.batch_dedup` (Task 1).
- Produces: `build_user_prompt(..., prior_scopes: Sequence[PriorScope] | None = None) -> tuple[str, list[Path]]`. When `prior_scopes` is None or empty, the returned string is byte-identical to today.

- [ ] **Step 1: Write the failing test — append to `tests/test_batch_dedup.py`**

Append to `tests/test_batch_dedup.py`:

```python
def test_math_build_user_prompt_no_scopes_is_byte_identical(tmp_path) -> None:
    import random

    from src.common.batch_dedup import PriorScope
    from src.context_builder import build_user_prompt
    from src.sampler import sample_params

    grade_content = {g: [] for g in [7, 8, 9]}
    params = sample_params(grade_content=grade_content, seed=1)

    baseline, _ = build_user_prompt(params, tmp_path, rng=random.Random(2))
    with_none, _ = build_user_prompt(
        params, tmp_path, rng=random.Random(2), prior_scopes=None,
    )
    with_empty, _ = build_user_prompt(
        params, tmp_path, rng=random.Random(2), prior_scopes=[],
    )
    assert baseline == with_none == with_empty
    assert "已生成題目" not in baseline


def test_math_build_user_prompt_renders_prior_scopes_block(tmp_path) -> None:
    import random

    from src.common.batch_dedup import PriorScope
    from src.context_builder import build_user_prompt
    from src.sampler import sample_params

    grade_content = {g: [] for g in [7, 8, 9]}
    params = sample_params(grade_content=grade_content, seed=1)
    scopes = [PriorScope(summary="比較有理數大小", codes=["N-7-1", "N-7-2"])]

    prompt, _ = build_user_prompt(
        params, tmp_path, rng=random.Random(2), prior_scopes=scopes,
    )
    assert "## 已生成題目（請避免相似範圍）" in prompt
    assert "1. 核心問題：比較有理數大小；學習內容：N-7-1, N-7-2" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_batch_dedup.py -q`
Expected: FAIL — the two new tests fail because `build_user_prompt` does not accept `prior_scopes`.

- [ ] **Step 3: Update `build_user_prompt` in `src/context_builder.py`**

At the top of `src/context_builder.py`, add the import near the other `src.common.*` imports (around line 8):

```python
from src.common.batch_dedup import PriorScope, format_prior_scopes_block
```

Update `USER_PROMPT_TEMPLATE` — right after the closing `{user_materials}` line and before `## 參考範例`, insert a `{prior_scopes_block}` placeholder. Replace the block from lines 158-166 (existing template top) with:

```python
USER_PROMPT_TEMPLATE = """\
請根據以下條件生成一道數學考試題目：

## 指定條件

- **年級重心**：{grade}年級
- **科目焦點**：{subject_filter}
- **情境**（題目輸出的 `情境` 欄位必須完全使用以下這幾個列舉值）：{context}
- **題型種類**：{set_type}
- **題型**：{q_type}
- **數學思考**：{thinking}
- **題目內容類型**：{content_type}
- **核心素養（限定使用）**：{core_competencies}
- **必須涵蓋的學習內容**：
{content_list}
{lp_pool_lines}{param_instructions}
## 題目風格

{style_instruction}
{user_materials}{prior_scopes_block}
## 參考範例

以下是符合類似風格的範例題目，供你參考格式和難度水準：

{few_shot_examples}

## 重要提醒

1. 不要複製範例題目，必須原創。
2. 確保答案正確，解題過程完整。
3. 學習內容可以跨年級整合（{grade_range}範圍內），但核心考點應以指定的學習內容為主。
4. 選項的誘答設計應針對常見錯誤概念。
5. 題目的 `核心素養` 欄位**必須只從指定條件中的核心素養代號選擇**。
6. 題目的 `情境` 欄位**必須完全使用「指定條件 → 情境」中列出的列舉值之一**（合法值僅為：個人 / 社會時事 / 科學 / 職業 / 建築與藝術 / 數學文字情境），不可改寫成題目主題、場景描述、或情境名稱。題目主題若需呈現，請放入題目內文，而不是 `情境` 欄位。
7. 維持單題輸出結構（不是題組）：不要產生 `subquestions`、`核心問題`、`文本`、`評分規準` 等題組欄位。
8. 只輸出 JSON 格式的結果。
"""
```

Change the `build_user_prompt` signature (currently at line 231) and body:

```python
def build_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
    *,
    user_topic: str = "",
    user_passage: str = "",
    user_options: list[str] | None = None,
    user_core_question: str = "",
    prior_scopes: "Sequence[PriorScope] | None" = None,
) -> tuple[str, list[Path]]:
```

And at the top of the function file (or near the other imports), add:

```python
from collections.abc import Sequence
```

Inside the function, right before the final `text = USER_PROMPT_TEMPLATE.format(...)` call, compute the block:

```python
    prior_scopes_block = (
        "\n" + format_prior_scopes_block(prior_scopes) if prior_scopes else ""
    )
```

Then add `prior_scopes_block=prior_scopes_block,` to the `.format(...)` call's keyword arguments.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch_dedup.py -q`
Expected: PASS — all tests green including the two new prompt-level tests.

- [ ] **Step 5: Regression check — existing math tests still pass**

Run: `uv run pytest tests/test_math_sampler.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/context_builder.py tests/test_batch_dedup.py
git commit -m "feat(math): render prior_scopes block in build_user_prompt (#111)"
```

---

### Task 3: Thread `prior_scopes` through math `generate_one` / `generate_with_corrections` and math batch loop

**Files:**
- Modify: `src/cli.py` (`generate_one`, `generate_with_corrections`, `main` loop)
- Modify: `tests/test_batch_dedup.py` (batch-loop test with fake client)

**Interfaces:**
- Consumes: `PriorScope`, `extract_math_prior_scope` from Task 1; `build_user_prompt(..., prior_scopes=...)` from Task 2.
- Produces: `generate_one(..., prior_scopes=...)`, `generate_with_corrections(..., prior_scopes=...)` and a `main()` loop that accumulates scopes across the batch.

- [ ] **Step 1: Write the failing test — append to `tests/test_batch_dedup.py`**

```python
def test_math_batch_loop_forwards_prior_scopes_to_next_question(tmp_path) -> None:
    """After question 1 completes, question 2's user prompt sees question 1's scope."""
    from pathlib import Path

    from src.cli import generate_with_corrections
    from src.common.batch_dedup import PriorScope, extract_math_prior_scope
    from src.config import Config
    from src.sampler import sample_params

    class _RecordingClient:
        def __init__(self) -> None:
            self.user_prompts: list[str] = []

        def get_observer(self):
            return None

        def generate_json(self, _system, user, *_args, **_kwargs):
            self.user_prompts.append(user)
            idx = len(self.user_prompts)
            return {
                "情境": ["個人"],
                "題型種類": "單一題",
                "題型": "選擇題",
                "數學思考": ["運用"],
                "學習內容": [{"編碼": f"N-7-{idx}", "說明": "測試"}],
                "題目": [f"題 {idx}"],
                "正確解題分析": [f"解 {idx}"],
                "出題概念": f"評量概念 {idx}",
            }

    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    grade_content = {g: [] for g in [7, 8, 9]}
    client = _RecordingClient()

    prior_scopes: list[PriorScope] = []
    for i in range(2):
        params = sample_params(grade_content=grade_content, seed=100 + i)
        result = generate_with_corrections(
            config=config,
            client=client,
            curriculum=[],
            performance={},
            intro_text="",
            grade_content=grade_content,
            params=params,
            question_id=f"q_test_{i+1:03d}",
            max_retries=0,
            skip_verify=True,
            prior_scopes=list(prior_scopes),
        )
        scope = extract_math_prior_scope(result)
        assert scope is not None
        prior_scopes.append(scope)

    # First prompt has no dedup block; second must show question 1's summary + code.
    assert "已生成題目" not in client.user_prompts[0]
    assert "1. 核心問題：評量概念 1；學習內容：N-7-1" in client.user_prompts[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_batch_dedup.py::test_math_batch_loop_forwards_prior_scopes_to_next_question -q`
Expected: FAIL — `generate_with_corrections` does not accept `prior_scopes`.

- [ ] **Step 3: Extend `generate_one` / `generate_with_corrections` in `src/cli.py`**

At the top of `src/cli.py`, near the other `src.*` imports (around line 13), add:

```python
from collections.abc import Sequence

from src.common.batch_dedup import PriorScope, extract_math_prior_scope
```

Change `generate_one`'s signature (line 143) — add `prior_scopes` keyword:

```python
def generate_one(
    config: Config,
    client: LLMClient | None,
    curriculum: list[dict],
    performance: dict,
    intro_text: str,
    grade_content: dict[int, list[LearningContentItem]],
    params: SampledParams,
    question_id: str,
    dry_run: bool = False,
    skip_verify: bool = False,
    html_renderer: PlaywrightRenderer | None = None,
    image_generation_mode: str = "html",
    user_topic: str = "",
    user_passage: str = "",
    user_options: list[str] | None = None,
    user_core_question: str = "",
    on_question_update: QuestionUpdateCallback | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> ExamQuestion | str:
```

Inside `generate_one`, change the existing `build_user_prompt(...)` call (line 171-178) to:

```python
    user_prompt, few_shot_images = build_user_prompt(
        params,
        config.data_dir / "few_shot",
        user_topic=user_topic,
        user_passage=user_passage,
        user_options=user_options,
        user_core_question=user_core_question,
        prior_scopes=prior_scopes,
    )
```

Change `generate_with_corrections` (line 238) — add the same keyword after `on_question_update`:

```python
    on_question_update: QuestionUpdateCallback | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> ExamQuestion | str:
```

Inside `generate_with_corrections`, add `prior_scopes=prior_scopes` to the delegated `generate_one(...)` call (line 264-282):

```python
    question = generate_one(
        config=config,
        client=client,
        curriculum=curriculum,
        performance=performance,
        intro_text=intro_text,
        grade_content=grade_content,
        params=params,
        question_id=question_id,
        dry_run=dry_run,
        skip_verify=skip_verify,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_topic=user_topic,
        user_passage=user_passage,
        user_options=user_options,
        user_core_question=user_core_question,
        on_question_update=on_question_update,
        prior_scopes=prior_scopes,
    )
```

Correction passes do NOT resend `prior_scopes` — corrector is minimal-targeted-fix only (per CLAUDE.md), and dedup is a generation-time concern.

- [ ] **Step 4: Accumulate `prior_scopes` in `main()`'s batch loop**

In `src/cli.py`, `main()` around line 517-573, replace the `results = []` block up to `# Write individual JSON` with:

```python
    # Generate questions
    results = []
    prior_scopes: list[PriorScope] = []
    base_seed = args.seed
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
            question_id = f"q_{timestamp}_{i+1:03d}"

            params = sample_params(
                grade_content=grade_content,
                grade=args.grade,
                style=style_override,
                context=context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                seed=seed,
                core_competency=core_competency_override,
                learning_content=learning_content_override,
                learning_performance=learning_performance_override,
                content_type=content_type_override,
                subject_filter=subject_filter_override,
            )

            print(f"\n[{i+1}/{args.count}] Sampled: grade={params.grade}, "
                  f"style={params.style.value}, 情境={'、'.join(c.value for c in params.情境)}, "
                  f"題型={params.題型.value}", file=sys.stderr)
            print(f"  學習內容: {', '.join(c.編碼 for c in params.學習內容)}", file=sys.stderr)

            result = generate_with_corrections(
                config=config,
                client=client,
                curriculum=curriculum,
                performance=performance,
                intro_text=intro_text,
                grade_content=grade_content,
                params=params,
                question_id=question_id,
                max_retries=max_retries,
                skip_verify=args.no_verify,
                html_renderer=html_renderer,
                dry_run=args.dry_run,
                image_generation_mode=args.image_generation_mode,
                user_topic=args.topic or "",
                user_passage=args.passage or "",
                user_options=args.options,
                user_core_question=args.core_question or "",
                prior_scopes=list(prior_scopes),
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)

            results.append(question)

            scope = extract_math_prior_scope(question)
            if scope is not None:
                prior_scopes.append(scope)

            # Write individual JSON (unless batch mode)
            if not args.batch:
                out_path = config.output_dir / f"{question_id}.json"
                out_path.write_text(
                    question.model_dump_json(indent=2, exclude_none=True),
                    encoding="utf-8",
                )
                print(f"  Saved: {out_path}", file=sys.stderr)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch_dedup.py -q`
Expected: PASS — all tests including the new batch-loop test.

- [ ] **Step 6: Regression check — math sampler tests still pass**

Run: `uv run pytest tests/test_math_sampler.py tests/test_batch_dedup.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/cli.py tests/test_batch_dedup.py
git commit -m "feat(math): accumulate PriorScope across batch loop (#111)"
```

---

### Task 4: Wire `prior_scopes` into social-studies `build_text_user_prompt`

**Files:**
- Modify: `src/social_studies/context_builder.py` (`build_user_prompt` + `build_text_user_prompt`)
- Modify: `tests/test_batch_dedup.py` (append SS prompt-level tests)

**Interfaces:**
- Consumes: `PriorScope`, `format_prior_scopes_block` from Task 1.
- Produces: `build_text_user_prompt(..., prior_scopes: Sequence[PriorScope] | None = None)`. The 子題產生器 builder (`build_subquestion_user_prompt`) is **not** changed.

- [ ] **Step 1: Write the failing tests — append to `tests/test_batch_dedup.py`**

```python
def test_ss_build_text_user_prompt_no_scopes_is_byte_identical(tmp_path) -> None:
    from src.common.batch_dedup import PriorScope
    from src.social_studies.context_builder import build_text_user_prompt
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=5)

    baseline, _ = build_text_user_prompt(params, tmp_path)
    with_none, _ = build_text_user_prompt(params, tmp_path, prior_scopes=None)
    with_empty, _ = build_text_user_prompt(params, tmp_path, prior_scopes=[])
    assert baseline == with_none == with_empty
    assert "已生成題目" not in baseline


def test_ss_build_text_user_prompt_renders_prior_scopes_block(tmp_path) -> None:
    from src.common.batch_dedup import PriorScope
    from src.social_studies.context_builder import build_text_user_prompt
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=5)
    scopes = [
        PriorScope(summary="工業革命如何改變勞動條件？", codes=["歷Ka-Ⅳ-1", "公Ab-Ⅳ-2"]),
    ]

    prompt, _ = build_text_user_prompt(params, tmp_path, prior_scopes=scopes)
    assert "## 已生成題目（請避免相似範圍）" in prompt
    assert "1. 核心問題：工業革命如何改變勞動條件？；學習內容：歷Ka-Ⅳ-1, 公Ab-Ⅳ-2" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_batch_dedup.py -q`
Expected: FAIL — `build_text_user_prompt` does not accept `prior_scopes`.

- [ ] **Step 3: Update the SS context builder**

At the top of `src/social_studies/context_builder.py`, near the other imports (around line 8), add:

```python
from collections.abc import Sequence

from src.common.batch_dedup import PriorScope, format_prior_scopes_block
```

Extend `build_user_prompt` (line 277) — add `prior_scopes` keyword and render the block just before the final `text = USER_PROMPT_TEMPLATE.format(...)` call:

```python
def build_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    disable_reference_fewshot: bool = False,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> tuple[str, list[Path]]:
```

Inside the function, right before the closing `text = USER_PROMPT_TEMPLATE.format(...)` call (line 506), append the block to `user_materials`:

```python
    if prior_scopes:
        prior_scopes_text = format_prior_scopes_block(prior_scopes)
        user_materials = (user_materials or "\n") + "\n" + prior_scopes_text
```

Then extend `build_text_user_prompt` (line 882) so it forwards the argument to `build_user_prompt`:

```python
def build_text_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    disable_reference_fewshot: bool = False,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> tuple[str, list[Path]]:
    text, image_paths = build_user_prompt(
        params=params,
        few_shot_dir=few_shot_dir,
        rng=rng,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        disable_reference_fewshot=disable_reference_fewshot,
        prior_scopes=prior_scopes,
    )
```

(The rest of `build_text_user_prompt`'s body — the two `.replace(...)` calls and the text_word_limit branch — is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch_dedup.py tests/test_social_studies_context_builder.py -q`
Expected: PASS — including the two new SS prompt-level tests and the pre-existing SS context-builder tests.

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/context_builder.py tests/test_batch_dedup.py
git commit -m "feat(social-studies): render prior_scopes block in build_text_user_prompt (#111)"
```

---

### Task 5: Thread `prior_scopes` through social-studies CLI and batch loop

**Files:**
- Modify: `src/social_studies/cli.py` (`generate_one`, `generate_with_corrections`, `main` loop)
- Modify: `tests/test_batch_dedup.py` (SS batch-loop test)

**Interfaces:**
- Consumes: `extract_ss_prior_scope` from Task 1; `build_text_user_prompt(..., prior_scopes=...)` from Task 4.
- Produces: `ss_generate_with_corrections(..., prior_scopes=...)` and a `main()` loop that accumulates SS scopes.

- [ ] **Step 1: Write the failing test — append to `tests/test_batch_dedup.py`**

```python
def test_ss_batch_loop_forwards_prior_scopes_to_next_question(tmp_path) -> None:
    from pathlib import Path

    from src.common.batch_dedup import PriorScope, extract_ss_prior_scope
    from src.config import Config
    from src.social_studies.cli import generate_with_corrections
    from src.social_studies.sampler import sample_params

    class _RecordingSSClient:
        def __init__(self) -> None:
            self.user_prompts: list[str] = []

        def get_observer(self):
            return None

        def generate_json(self, _system, user, *_args, **_kwargs):
            self.user_prompts.append(user)
            idx = len(self.user_prompts)
            return {
                "核心問題": f"社會核心問題 {idx}",
                "文本": "測試文本",
                "取材來源": [],
                "subquestions": [
                    {
                        "序號": 1,
                        "年級": 8,
                        "科目": ["歷史"],
                        "核心素養": ["社-J-A2"],
                        "學習內容": [{"編碼": f"歷Ka-Ⅳ-{idx}", "說明": "測試"}],
                        "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "測試"}],
                        "出題概念": "測試",
                        "題型": "選擇題",
                        "題目": "測試題目",
                        "答案": "A",
                        "答案解析": "測試",
                        "評分規準": [],
                    }
                ],
                "題目": ["文本", "測試"],
                "正確解題分析": ["A"],
            }

    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    client = _RecordingSSClient()

    prior_scopes: list[PriorScope] = []
    for i in range(2):
        params = sample_params(seed=200 + i)
        result = generate_with_corrections(
            config=config,
            client=client,
            params=params,
            question_id=f"ss_test_{i+1:03d}",
            max_retries=0,
            skip_verify=True,
            prior_scopes=list(prior_scopes),
        )
        scope = extract_ss_prior_scope(result)
        assert scope is not None
        prior_scopes.append(scope)

    # `_RecordingSSClient` is used for both the 文本生成器 call and the sub_generator
    # calls. The first captured prompt (index 0) is the 文本生成器 prompt for question 1;
    # locate the 文本生成器 prompt for question 2 — the first prompt captured AFTER
    # question 1 finished — and confirm it carries the dedup block.
    text_prompts = [p for p in client.user_prompts if "## 已生成題目" in p]
    assert text_prompts, "expected at least one prompt to carry the dedup block"
    assert "1. 核心問題：社會核心問題 1；學習內容：歷Ka-Ⅳ-1" in text_prompts[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_batch_dedup.py::test_ss_batch_loop_forwards_prior_scopes_to_next_question -q`
Expected: FAIL — `generate_with_corrections` does not accept `prior_scopes`.

- [ ] **Step 3: Extend `generate_one` / `generate_with_corrections` in `src/social_studies/cli.py`**

At the top of `src/social_studies/cli.py`, near the other imports (around line 8), add:

```python
from collections.abc import Sequence

from src.common.batch_dedup import PriorScope, extract_ss_prior_scope
```

Change `generate_one` (line 534) — add `prior_scopes` keyword at the end of the signature:

```python
    on_question_update: QuestionUpdateCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> ExamQuestion | str:
```

Inside `generate_one`, update both call sites of `build_text_user_prompt` (line 557 and line 578) to forward `prior_scopes=prior_scopes` as a keyword argument:

```python
        text_user, text_images = build_text_user_prompt(
            params,
            few_shot_dir,
            image_generation_mode=image_generation_mode,
            user_passage=user_passage,
            user_options=user_options,
            user_topic=user_topic,
            user_core_question=user_core_question,
            disable_reference_fewshot=disable_reference_fewshot,
            prior_scopes=prior_scopes,
        )
```

The 子題產生器 call (`build_subquestion_user_prompt`) is unchanged — dedup is only injected into the 文本生成器 stage.

Change `generate_with_corrections` (line 718) — add `prior_scopes` keyword at the end of the signature and pass it to the `generate_one(...)` call:

```python
    on_question_update: QuestionUpdateCallback | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> ExamQuestion | str:
    """generate_one followed by up to max_retries correction passes."""
    question = generate_one(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        dry_run=dry_run,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        text_word_limit=text_word_limit,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        on_question_update=on_question_update,
        prior_scopes=prior_scopes,
    )
```

- [ ] **Step 4: Accumulate `prior_scopes` in the SS `main()` batch loop**

In `src/social_studies/cli.py` `main()` around line 858-914, replace the `results = []` block with:

```python
    results = []
    prior_scopes: list[PriorScope] = []
    base_seed = args.seed
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
            question_id = f"ss_{timestamp}_{i+1:03d}"

            params = sample_params(
                grade=args.grade,
                context=context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                subject=subject_override,
                core_competency=core_competency_override,
                learning_content=learning_content_override,
                learning_performance=learning_performance_override,
                content_type=content_type_override,
                seed=seed,
            )

            print(f"\n[{i+1}/{args.count}] Sampled: grade={params.grade}, "
                  f"科目={params.科目.value}, "
                  f"情境={'、'.join(c.value for c in params.情境)}, "
                  f"題型={'、'.join(t.value for t in params.題型)}, 閱讀歷程={'、'.join(p.value for p in params.閱讀歷程)}, "
                  f"文本形式={params.文本形式.value}, "
                  f"題目內容類型={params.題目內容類型}, "
                  f"核心素養={'、'.join(c.value for c in params.核心素養)}", file=sys.stderr)

            result = generate_with_corrections(
                config=config,
                client=client,
                params=params,
                question_id=question_id,
                max_retries=max_retries,
                skip_verify=args.no_verify,
                html_renderer=html_renderer,
                image_generation_mode=args.image_generation_mode,
                dry_run=args.dry_run,
                prior_scopes=list(prior_scopes),
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)
            results.append(question)

            scope = extract_ss_prior_scope(question)
            if scope is not None:
                prior_scopes.append(scope)

            if not args.batch:
                out_path = config.output_dir / f"{question_id}.json"
                out_path.write_text(
                    question.model_dump_json(indent=2, exclude_none=True),
                    encoding="utf-8",
                )
                print(f"  Saved: {out_path}", file=sys.stderr)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch_dedup.py tests/test_social_studies_context_builder.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/social_studies/cli.py tests/test_batch_dedup.py
git commit -m "feat(social-studies): accumulate PriorScope across batch loop (#111)"
```

---

### Task 6: Wire `prior_scopes` into natural-sciences `build_text_user_prompt`

**Files:**
- Modify: `src/natural_sciences/context_builder.py`
- Modify: `tests/test_batch_dedup.py` (append NS prompt-level tests)

**Interfaces:**
- Consumes: `PriorScope`, `format_prior_scopes_block` from Task 1.
- Produces: `build_text_user_prompt(..., prior_scopes: Sequence[PriorScope] | None = None)` in the NS package.

- [ ] **Step 1: Write the failing tests — append to `tests/test_batch_dedup.py`**

```python
def test_ns_build_text_user_prompt_no_scopes_is_byte_identical(tmp_path) -> None:
    from src.common.batch_dedup import PriorScope
    from src.natural_sciences.context_builder import build_text_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=7)

    baseline, _ = build_text_user_prompt(params, tmp_path)
    with_none, _ = build_text_user_prompt(params, tmp_path, prior_scopes=None)
    with_empty, _ = build_text_user_prompt(params, tmp_path, prior_scopes=[])
    assert baseline == with_none == with_empty
    assert "已生成題目" not in baseline


def test_ns_build_text_user_prompt_renders_prior_scopes_block(tmp_path) -> None:
    from src.common.batch_dedup import PriorScope
    from src.natural_sciences.context_builder import build_text_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=7)
    scopes = [PriorScope(summary="海洋酸化對生態的影響", codes=["INc-Ⅳ-1"])]

    prompt, _ = build_text_user_prompt(params, tmp_path, prior_scopes=scopes)
    assert "## 已生成題目（請避免相似範圍）" in prompt
    assert "1. 核心問題：海洋酸化對生態的影響；學習內容：INc-Ⅳ-1" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_batch_dedup.py -q`
Expected: FAIL — the two new NS prompt tests fail.

- [ ] **Step 3: Update the NS context builder**

At the top of `src/natural_sciences/context_builder.py`, near the other imports (around line 4), add:

```python
from collections.abc import Sequence

from src.common.batch_dedup import PriorScope, format_prior_scopes_block
```

Extend `build_user_prompt` (line 244):

```python
def build_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    disable_reference_fewshot: bool = False,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> tuple[str, list[Path]]:
```

Inside the function, right before the final `text = USER_PROMPT_TEMPLATE.format(...)` call (line 416), append the block to `user_materials`:

```python
    if prior_scopes:
        prior_scopes_text = format_prior_scopes_block(prior_scopes)
        user_materials = (user_materials or "\n") + "\n" + prior_scopes_text
```

Extend `build_text_user_prompt` (line 537) so it forwards the keyword to `build_user_prompt`:

```python
def build_text_user_prompt(
    params: SampledParams,
    few_shot_dir: Path,
    rng: random.Random | None = None,
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    disable_reference_fewshot: bool = False,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> tuple[str, list[Path]]:
    text, image_paths = build_user_prompt(
        params=params,
        few_shot_dir=few_shot_dir,
        rng=rng,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        disable_reference_fewshot=disable_reference_fewshot,
        prior_scopes=prior_scopes,
    )
```

(The rest of `build_text_user_prompt` — the `.replace(...)` calls and `text_word_limit` branch — is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch_dedup.py tests/test_natural_sciences_context_builder.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/natural_sciences/context_builder.py tests/test_batch_dedup.py
git commit -m "feat(natural-sciences): render prior_scopes block in build_text_user_prompt (#111)"
```

---

### Task 7: Thread `prior_scopes` through natural-sciences CLI and batch loop

**Files:**
- Modify: `src/natural_sciences/cli.py` (`generate_one`, `generate_with_corrections`, `main` loop)
- Modify: `tests/test_batch_dedup.py` (NS batch-loop test)

**Interfaces:**
- Consumes: `extract_ns_prior_scope` from Task 1; `build_text_user_prompt(..., prior_scopes=...)` from Task 6.
- Produces: `ns_generate_with_corrections(..., prior_scopes=...)` and a `main()` loop that accumulates NS scopes.

- [ ] **Step 1: Write the failing test — append to `tests/test_batch_dedup.py`**

```python
def test_ns_batch_loop_forwards_prior_scopes_to_next_question(tmp_path) -> None:
    from pathlib import Path

    from src.common.batch_dedup import PriorScope, extract_ns_prior_scope
    from src.config import Config
    from src.natural_sciences.cli import generate_with_corrections
    from src.natural_sciences.sampler import sample_params

    class _RecordingNSClient:
        def __init__(self) -> None:
            self.user_prompts: list[str] = []

        def get_observer(self):
            return None

        def generate_json(self, _system, user, *_args, **_kwargs):
            self.user_prompts.append(user)
            idx = len(self.user_prompts)
            return {
                "核心問題": f"科學核心問題 {idx}",
                "文本": "科學測試文本",
                "取材來源": [],
                "subquestions": [
                    {
                        "序號": 1,
                        "年級": 8,
                        "科目": ["自然科學"],
                        "科學能力": ["能力一"],
                        "核心素養": [],
                        "學習內容": [{"編碼": f"INc-Ⅳ-{idx}", "說明": "測試"}],
                        "學習表現": [{"編碼": "tr-Ⅳ-1", "說明": "測試"}],
                        "出題概念": "測試",
                        "題型": "Simple-multiple-choice",
                        "題目": "測試題目",
                        "答案": "A",
                        "答案解析": "測試",
                        "評分規準": [],
                    }
                ],
                "題目": ["文本", "測試"],
                "正確解題分析": ["A"],
            }

    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    client = _RecordingNSClient()

    prior_scopes: list[PriorScope] = []
    for i in range(2):
        params = sample_params(seed=300 + i)
        result = generate_with_corrections(
            config=config,
            client=client,
            params=params,
            question_id=f"ns_test_{i+1:03d}",
            max_retries=0,
            skip_verify=True,
            prior_scopes=list(prior_scopes),
        )
        scope = extract_ns_prior_scope(result)
        assert scope is not None
        prior_scopes.append(scope)

    text_prompts = [p for p in client.user_prompts if "## 已生成題目" in p]
    assert text_prompts, "expected at least one prompt to carry the dedup block"
    assert "1. 核心問題：科學核心問題 1；學習內容：INc-Ⅳ-1" in text_prompts[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_batch_dedup.py::test_ns_batch_loop_forwards_prior_scopes_to_next_question -q`
Expected: FAIL — `ns_generate_with_corrections` does not accept `prior_scopes`.

- [ ] **Step 3: Extend `generate_one` / `generate_with_corrections` in `src/natural_sciences/cli.py`**

At the top of `src/natural_sciences/cli.py`, near the other imports (around line 8), add:

```python
from collections.abc import Sequence

from src.common.batch_dedup import PriorScope, extract_ns_prior_scope
```

Change `generate_one` (line 353) — add `prior_scopes` keyword at the end of the signature:

```python
    on_question_update: QuestionUpdateCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> ExamQuestion | str:
```

Inside `generate_one`, update both call sites of `build_text_user_prompt` (line 375 and line 396) to forward `prior_scopes=prior_scopes`:

```python
        text_user, text_images = build_text_user_prompt(
            params,
            config.data_dir / "natural_sciences" / "few_shot",
            user_passage=user_passage,
            user_options=user_options,
            user_topic=user_topic,
            user_core_question=user_core_question,
            image_generation_mode=image_generation_mode,
            disable_reference_fewshot=disable_reference_fewshot,
            prior_scopes=prior_scopes,
        )
```

The 子題產生器 call (`build_subquestion_user_prompt`) is unchanged.

Change `generate_with_corrections` (line 512) — add `prior_scopes` keyword at the end of the signature and pass it to `generate_one(...)`:

```python
    on_question_update: QuestionUpdateCallback | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
) -> ExamQuestion | str:
    """generate_one followed by up to max_retries correction passes."""
    question = generate_one(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        dry_run=dry_run,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        text_word_limit=text_word_limit,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        on_question_update=on_question_update,
        prior_scopes=prior_scopes,
    )
```

- [ ] **Step 4: Accumulate `prior_scopes` in the NS `main()` batch loop**

In `src/natural_sciences/cli.py` `main()` around line 659-717, replace the `results = []` block with:

```python
    results = []
    prior_scopes: list[PriorScope] = []
    base_seed = args.seed
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
            question_id = f"ns_{timestamp}_{i+1:03d}"

            params = sample_params(
                grade=args.grade,
                context=context_override,
                sub_context=sub_context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                science_competency=science_competency_override,
                learning_content=learning_content_override,
                learning_performance=learning_performance_override,
                content_type=content_type_override,
                seed=seed,
            )

            print(
                f"\n[{i + 1}/{args.count}] Sampled: grade={params.grade}, "
                f"情境={'、'.join(c.value for c in params.情境)}, "
                f"情境子類別={params.情境子類別.value}, "
                f"題型={params.題型.value}, "
                f"科學能力={'、'.join(c.value for c in params.科學能力)}, "
                f"題目內容類型={params.題目內容類型}",
                file=sys.stderr,
            )

            result = generate_with_corrections(
                config=config,
                client=client,
                params=params,
                question_id=question_id,
                max_retries=max_retries,
                skip_verify=args.no_verify,
                html_renderer=html_renderer,
                image_generation_mode=args.image_generation_mode,
                dry_run=args.dry_run,
                prior_scopes=list(prior_scopes),
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)
            results.append(question)

            scope = extract_ns_prior_scope(question)
            if scope is not None:
                prior_scopes.append(scope)

            if not args.batch:
                out_path = config.output_dir / f"{question_id}.json"
                out_path.write_text(
                    question.model_dump_json(indent=2, exclude_none=True),
                    encoding="utf-8",
                )
                print(f"  Saved: {out_path}", file=sys.stderr)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch_dedup.py tests/test_natural_sciences_context_builder.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/natural_sciences/cli.py tests/test_batch_dedup.py
git commit -m "feat(natural-sciences): accumulate PriorScope across batch loop (#111)"
```

---

### Task 8: Server `generate_question_stream` — best-effort shared accumulator across all three subject branches

**Files:**
- Modify: `server/generate/service.py` (`generate_question_stream`, `worker_one`)
- Modify: `tests/test_batch_dedup.py` (server-level integration test)

**Interfaces:**
- Consumes: `PriorScope`, `extract_math_prior_scope`, `extract_ss_prior_scope`, `extract_ns_prior_scope` from Task 1; `prior_scopes` kwarg on all three `*_generate_with_corrections` from Tasks 3/5/7.
- Produces: `generate_question_stream` maintains a `threading.Lock`-guarded `list[PriorScope]` shared across concurrent `worker_one` invocations. Each worker takes a snapshot of the current list before calling the subject's `generate_with_corrections`, then appends its own scope under the lock after that call returns. Under simultaneous `run_in_executor` dispatch, early workers see an empty snapshot; later-completing workers see whatever finished before them. This is best-effort dedup consistent with the concurrent worker design.

- [ ] **Step 1: Write the failing test — append to `tests/test_batch_dedup.py`**

```python
def test_server_generate_stream_accumulates_prior_scopes_across_math_workers(tmp_path) -> None:
    """Two sequentially-completing math workers: the second must receive scope 1."""
    import asyncio
    import threading
    import types
    from pathlib import Path

    from server.config import ServerConfig
    from server.generate import service
    from server.generate.models import GenerateParams
    from src.common.batch_dedup import PriorScope

    captured: dict[int, list[PriorScope] | None] = {}
    order_lock = threading.Lock()
    counter = {"n": 0}

    def fake_math_gwc(**kwargs):
        idx = kwargs.get("question_id", "")
        prior = kwargs.get("prior_scopes")
        with order_lock:
            counter["n"] += 1
            captured[counter["n"]] = list(prior) if prior is not None else None
        # Serialize workers by waiting a moment so the second worker starts
        # after the first has appended its scope.
        import time
        time.sleep(0.05 * counter["n"])
        from src.schemas import ExamQuestion, LearningContentItem, QuestionMetadata
        return ExamQuestion.model_construct(
            id=idx,
            情境=[],
            題型種類="單一題",
            題型="選擇題",
            數學思考=[],
            學習內容=[LearningContentItem(編碼=f"N-7-{counter['n']}", 說明="測試")],
            題目=[],
            正確解題分析=[],
            出題概念=f"概念 {counter['n']}",
            metadata=None,
        )

    original = service.math_generate_with_corrections
    service.math_generate_with_corrections = fake_math_gwc  # type: ignore[assignment]

    app_state = types.SimpleNamespace(
        renderer_pool=None,
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={7: [], 8: [], 9: []},
    )
    config = ServerConfig(
        output_dir=tmp_path,
        data_dir=Path("data"),
        api_key="x",
        base_url="http://x",
        model_plan="p",
        model_execute="e",
        log_truncate=200,
        max_retries=0,
        subgen_max_concurrency=1,
    )
    params = GenerateParams(subject="math", count=2, skip_verify=True, seed=42)

    async def _drive() -> list[dict]:
        events: list[dict] = []
        async for evt in service.generate_question_stream(params, config, app_state):
            events.append(evt)
        return events

    try:
        events = asyncio.run(_drive())
    finally:
        service.math_generate_with_corrections = original  # type: ignore[assignment]

    # 2 workers ran; both should have been captured. At least one worker must
    # have observed a non-empty prior_scopes list.
    assert len(captured) == 2
    assert any(scopes for scopes in captured.values() if scopes), (
        "at least one worker must see prior_scopes",
        captured,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_batch_dedup.py::test_server_generate_stream_accumulates_prior_scopes_across_math_workers -q`
Expected: FAIL — `prior_scopes` argument is not being passed by the server.

- [ ] **Step 3: Wire the shared accumulator into `generate_question_stream`**

At the top of `server/generate/service.py`, near the other imports (line 7-14), add:

```python
import threading

from src.common.batch_dedup import (
    PriorScope,
    extract_math_prior_scope,
    extract_ns_prior_scope,
    extract_ss_prior_scope,
)
```

Inside `generate_question_stream` (around line 196, just before the `_EVENT_TYPE_MAP` block), add the shared accumulator:

```python
    prior_scopes: list[PriorScope] = []
    prior_scopes_lock = threading.Lock()
```

Inside `worker_one` (starting around line 248), before the `try:` block, snapshot the current list under the lock:

```python
    def worker_one(i: int, question_client: LLMClient) -> None:
        seed = (base_seed + i) if base_seed is not None else None
        question_client.set_observer(_make_queue_observer(loop, queue))
        emit_question_update = _make_question_update_emitter(i)
        _emit_pipeline("question_start", index=i, total=count)
        with prior_scopes_lock:
            prior_snapshot = list(prior_scopes)
        try:
```

Update each of the three subject branches inside `worker_one` to pass `prior_scopes=prior_snapshot` to `*_generate_with_corrections`:

- SS branch (line 272-288) — add `prior_scopes=prior_snapshot,` before the closing `)`.
- NS branch (line 309-325) — same.
- Math branch (line 346-364) — same.

After each subject branch's `question = *_generate_with_corrections(...)` line returns (i.e., before the `assert isinstance(question, ...)` at line 365), append the scope under the lock:

```python
            if is_social_studies:
                new_scope = extract_ss_prior_scope(question)
            elif is_natural_sciences:
                new_scope = extract_ns_prior_scope(question)
            else:
                new_scope = extract_math_prior_scope(question)
            if new_scope is not None:
                with prior_scopes_lock:
                    prior_scopes.append(new_scope)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_batch_dedup.py -q`
Expected: PASS — server-level integration test passes; earlier tests still pass.

- [ ] **Step 5: Regression check — existing server route tests still pass**

Run: `uv run pytest tests/server/test_generate_routes.py tests/test_batch_dedup.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/generate/service.py tests/test_batch_dedup.py
git commit -m "feat(server): accumulate PriorScope across concurrent workers in generate stream (#111)"
```

---

### Task 9: Full-suite regression pass + documentation

**Files:**
- Modify: `CLAUDE.md` (append a short note about the new batch-dedup pipeline).

**Interfaces:**
- Consumes: everything above.
- Produces: nothing new — this is verification + docs only.

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: all pre-existing tests still pass plus every test added in Tasks 1–8.

- [ ] **Step 2: Run ruff**

Run: `uv run ruff check src/ server/ tests/`
Expected: no new warnings introduced by this plan's changes.

- [ ] **Step 3: Add a short doc note in `CLAUDE.md`**

In `CLAUDE.md`, in the `## Architecture Decisions` section, add a new subsection immediately after `### Script-side randomness` (search for the heading and insert below its closing paragraph):

```markdown
### Batch-level prompt dedup (issue #111)

When a batch generates `count > 1` questions, each subject's batch loop accumulates a `list[PriorScope]` of already-accepted siblings (`{核心問題 | 出題概念, 學習內容 codes}`) and passes it to the next question's user prompt via a new optional `prior_scopes` keyword on `build_user_prompt` (math) / `build_text_user_prompt` (社會/自然). The LLM sees a short `## 已生成題目（請避免相似範圍）` block listing up to the 10 most recent siblings so it varies angle/題材 even when learning-content codes overlap. Empty list → section omitted → count=1 prompts are byte-identical to today. Extractor helpers and formatter live in `src/common/batch_dedup.py`. The server's `generate_question_stream` shares one `threading.Lock`-guarded list across concurrent workers — best-effort dedup consistent with the concurrent worker design. Embedding-similarity retry (Phase 2) is out of scope.
```

- [ ] **Step 4: Final verification**

Run: `uv run pytest -q && uv run ruff check src/ server/ tests/`
Expected: PASS, no lint errors.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: describe batch-dedup pipeline in CLAUDE.md (#111)"
```
