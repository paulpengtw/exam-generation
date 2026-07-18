# Per-Option 誘答分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach a per-option 誘答分析 dict — mapping each option label to the cognitive trap it targets — to every generated question across math, social studies, and natural sciences, then surface it in the web card and ODT export (GitHub issue #115, extended from SS-only to all three subjects).

**Architecture:** New `誘答分析: dict[str, str]` field added at the correct level for each subject's schema (math flat on `ExamQuestion`; SS/NS on `SubQuestion`). Prompt updates land in each subject's system + user prompts (for SS/NS this is the 子題產生器 prompt) with a taxonomy guidance block and a JSON example. A shared `src/common/distractor.py` helper produces a warning list when 誘答分析 keys do not match `(A)`–`(D)` labels extracted from the 題目, wired into every subject's verifier as a details-level advisory (never `passed=False`). Correctors let 誘答分析 mutate so it tracks corrected answers. Frontend adds a collapsible amber panel per 小題 (SS/NS) or per-question (math). ODT export emits the block under each 小題's 解析.

**Tech Stack:** Pydantic v2 (`dict[str, str] = Field(default_factory=dict)`), pytest via `uv run pytest`, React 19 + Vite + Tailwind 4, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-07-15-distractor-analysis-design.md`

## Global Constraints

- Applies to **all three subjects** (math flat on `ExamQuestion`, SS/NS on `SubQuestion`).
- Field is `誘答分析: dict[str, str] = Field(default_factory=dict)`. Empty dict is the default and existing output stays valid.
- Keys are the option labels used inside the 題目 text (`"A"`, `"B"`, `"C"`, `"D"` for math 選擇題 / SS 選擇題 / NS Simple/Complex-multiple-choice; `"是"`/`"非"` for math 是非題). Values describe the cognitive trap (誤讀題意 / 概念混淆 / 部分正確誘騙 / 過度推論 …). For the correct option the value is a one-sentence 「正確答案：…」. Constructed-response items may leave the dict empty or use `{"常見錯誤": "..."}`.
- Requirement level in prompts: **hard** for 選擇題-family 題型 (math 選擇題 + 是非題; SS 選擇題; NS Simple/Complex-multiple-choice); **optional 「常見錯誤」** for constructed-response 題型 (math 封閉式 / 開放式; SS 封閉式 / 開放式建構反應題; NS Constructed-response).
- For SS and NS, the 誘答分析 for each 小題 is written by that 子題's `子題產生器` call — NOT by the 文本生成器.
- Each subject's corrector must add 誘答分析 to the mutable-fields list and must NOT restore it from the original when the LLM emits a corrected answer.
- The verifier's `validate_distractor_keys()` helper appends warnings to `VerificationResult.details`; it must never flip `passed` to `False`.
- i18n key for the collapsible panel is `card.distractorAnalysis`; both `en-US` and `zh-TW` translations required.
- Frontend collapsible panel is amber-toned and is shown only where 答案/解析 is already shown; when the dict is empty, the panel is not rendered.
- ODT export inserts the section under each 小題's 解析 line for SS/NS, and under 正確解題分析 for math.
- All Python commands run from `/workspace/exam-generation/`. All web commands run from `/workspace/exam-generation/web/`.

---

### Task 1: Schema field on all three subjects

**Files:**
- Modify: `src/schemas.py:96-115` (`ExamQuestion` class — math flat)
- Modify: `src/social_studies/schemas.py:76-95` (`SubQuestion` class)
- Modify: `src/natural_sciences/schemas.py:79-97` (`SubQuestion` class)
- Create: `tests/test_distractor_analysis_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `src.schemas.ExamQuestion.誘答分析: dict[str, str]`
  - `src.social_studies.schemas.SubQuestion.誘答分析: dict[str, str]`
  - `src.natural_sciences.schemas.SubQuestion.誘答分析: dict[str, str]`
  - Empty-dict default across all three (backward compatible).

- [ ] **Step 1: Write the failing test**

Create `tests/test_distractor_analysis_schema.py`:

```python
"""Schema round-trip for the 誘答分析 field on math, SS, and NS."""

from __future__ import annotations

import json


def test_math_exam_question_accepts_and_defaults_distractor_analysis() -> None:
    from src.schemas import ExamQuestion

    q = ExamQuestion(
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[],
        題目=["Q?"],
        正確解題分析=["A"],
    )
    assert q.誘答分析 == {}

    dump = json.loads(q.model_dump_json())
    assert dump["誘答分析"] == {}

    q2 = ExamQuestion(
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[],
        題目=["Q?"],
        正確解題分析=["A"],
        誘答分析={"A": "正確答案：加權平均。", "B": "誤讀題意：忽略權重。"},
    )
    assert q2.誘答分析["B"] == "誤讀題意：忽略權重。"


def test_social_studies_subquestion_accepts_and_defaults_distractor_analysis() -> None:
    from src.social_studies.schemas import SubQuestion

    sq = SubQuestion(題型="選擇題", 題目="Q?")
    assert sq.誘答分析 == {}

    sq2 = SubQuestion(
        題型="選擇題",
        題目="Q?",
        誘答分析={"A": "正確答案：...", "C": "概念混淆"},
    )
    assert sq2.誘答分析["C"] == "概念混淆"


def test_natural_sciences_subquestion_accepts_and_defaults_distractor_analysis() -> None:
    from src.natural_sciences.schemas import SubQuestion

    sq = SubQuestion(題型="Simple-multiple-choice", 題目="Q?")
    assert sq.誘答分析 == {}

    sq2 = SubQuestion(
        題型="Constructed-response",
        題目="Q?",
        誘答分析={"常見錯誤": "誤以為 CO2 是主要污染物"},
    )
    assert sq2.誘答分析["常見錯誤"].startswith("誤以為")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_distractor_analysis_schema.py -x`
Expected: FAIL with `AttributeError: 'ExamQuestion' object has no attribute '誘答分析'` (or Pydantic `ValidationError: Extra inputs are not permitted` on the constructor with 誘答分析).

- [ ] **Step 3: Add the field to all three schemas**

In `src/schemas.py`, inside the `ExamQuestion` class body (after the existing `出題概念: str = ""` line, ~line 114), add:

```python
    誘答分析: dict[str, str] = Field(default_factory=dict)
```

In `src/social_studies/schemas.py`, inside the `SubQuestion` class body (after the existing `評分規準: list[RubricEntry] = Field(default_factory=list)` line, ~line 91), add:

```python
    誘答分析: dict[str, str] = Field(default_factory=dict)
```

In `src/natural_sciences/schemas.py`, inside the `SubQuestion` class body (after the existing `評分規準: list[RubricEntry] = Field(default_factory=list)` line, ~line 97), add:

```python
    誘答分析: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_distractor_analysis_schema.py -x`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/schemas.py src/social_studies/schemas.py src/natural_sciences/schemas.py tests/test_distractor_analysis_schema.py
git commit -m "feat(schema): add 誘答分析 dict field to math/SS/NS question models (#115)"
```

---

### Task 2: Shared validate_distractor_keys helper

**Files:**
- Create: `src/common/distractor.py`
- Create: `tests/test_common_distractor.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `validate_distractor_keys(question_text: str, analysis: dict[str, str]) -> list[str]` — returns a list of human-readable warnings (empty list means clean). Never raises.
  - Later tasks (verifiers) import this from `src.common.distractor`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_common_distractor.py`:

```python
"""Unit tests for the distractor-key validator."""

from __future__ import annotations


def test_returns_empty_when_dict_is_empty() -> None:
    from src.common.distractor import validate_distractor_keys

    assert validate_distractor_keys("What is 2+2? (A) 3 (B) 4 (C) 5 (D) 6", {}) == []


def test_returns_empty_when_keys_match_option_labels() -> None:
    from src.common.distractor import validate_distractor_keys

    text = "問題：\n(A) 3\n(B) 4\n(C) 5\n(D) 6"
    analysis = {
        "A": "誤讀題意",
        "B": "正確答案：4。",
        "C": "概念混淆",
        "D": "過度推論",
    }
    assert validate_distractor_keys(text, analysis) == []


def test_warns_when_analysis_has_extra_key() -> None:
    from src.common.distractor import validate_distractor_keys

    text = "問題：\n(A) 3\n(B) 4\n(C) 5\n(D) 6"
    warnings = validate_distractor_keys(text, {"A": "x", "B": "x", "C": "x", "D": "x", "E": "x"})
    assert len(warnings) == 1
    assert "E" in warnings[0]


def test_warns_when_analysis_is_missing_key() -> None:
    from src.common.distractor import validate_distractor_keys

    text = "問題：\n(A) 3\n(B) 4\n(C) 5\n(D) 6"
    warnings = validate_distractor_keys(text, {"A": "x", "B": "x", "C": "x"})
    assert len(warnings) == 1
    assert "D" in warnings[0]


def test_extracts_uppercase_labels_only_and_tolerates_full_width_parens() -> None:
    from src.common.distractor import validate_distractor_keys

    text = "問題：\n（A）3\n（B）4"
    warnings = validate_distractor_keys(text, {"A": "x", "B": "x"})
    assert warnings == []


def test_true_false_labels_pass_through() -> None:
    """是非題 uses 是 / 非 as keys; no options in text → no warnings expected."""
    from src.common.distractor import validate_distractor_keys

    warnings = validate_distractor_keys("下列敘述是否正確：2+2=4", {"是": "正確答案：...", "非": "..."})
    assert warnings == []


def test_never_raises_on_non_dict() -> None:
    from src.common.distractor import validate_distractor_keys

    assert validate_distractor_keys("text", None) == []  # type: ignore[arg-type]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_common_distractor.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.common.distractor'`.

- [ ] **Step 3: Write the implementation**

Create `src/common/distractor.py`:

```python
"""Validate that per-option 誘答分析 keys line up with the option labels in 題目.

Used by all three subject verifiers as a details-level advisory: warnings are
appended to VerificationResult.details but NEVER flip passed to False.
"""

from __future__ import annotations

import re

# Matches (A)–(Z) and full-width （A）–（Z） option-label markers in question text.
_OPTION_LABEL_RE = re.compile(r"[(（]\s*([A-Z])\s*[)）]")


def _extract_option_labels(question_text: str) -> set[str]:
    if not isinstance(question_text, str):
        return set()
    return {m.group(1) for m in _OPTION_LABEL_RE.finditer(question_text)}


def validate_distractor_keys(
    question_text: str, analysis: dict[str, str] | None
) -> list[str]:
    """Return human-readable warnings about mismatched 誘答分析 keys.

    Rules:
    - Empty / non-dict input → no warnings.
    - When question_text contains (A)-(D) style labels, every extracted label
      must appear in the analysis dict, and every analysis key must correspond
      to an extracted label (extras trigger a warning).
    - When the question has no (X) labels (constructed-response, 是非題 with
      是/非 keys, matching-type items), the dict is passed through without
      warnings — reviewers can still see the payload.
    """
    if not isinstance(analysis, dict) or not analysis:
        return []

    labels = _extract_option_labels(question_text)
    if not labels:
        return []

    warnings: list[str] = []
    keys = set(analysis.keys())
    missing = sorted(labels - keys)
    extra = sorted(keys - labels - {"常見錯誤"})
    if missing:
        warnings.append(
            f"誘答分析缺少選項 {', '.join(missing)}（題目中有此選項但未提供分析）"
        )
    if extra:
        warnings.append(
            f"誘答分析出現題目未定義的鍵 {', '.join(extra)}"
        )
    return warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_common_distractor.py -x`
Expected: PASS — 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/common/distractor.py tests/test_common_distractor.py
git commit -m "feat(common): add validate_distractor_keys helper for 誘答分析 audits (#115)"
```

---

### Task 3: Math system + user prompt guidance and _parse_question wiring

**Files:**
- Modify: `src/context_builder.py:72-140` (`SYSTEM_PROMPT_TEMPLATE`) and `src/context_builder.py:142-178` (`USER_PROMPT_TEMPLATE`)
- Modify: `src/cli.py:359-454` (`_parse_question`)
- Create: `tests/test_math_distractor_prompt.py`

**Interfaces:**
- Consumes: `src.schemas.ExamQuestion.誘答分析` (Task 1).
- Produces:
  - System prompt now contains a `## 誘答分析的設計` block with the taxonomy and one JSON example.
  - User prompt for `題型 in {選擇題, 是非題}` contains a hard requirement line; for other 題型 it is marked optional (`常見錯誤`).
  - `_parse_question` populates `ExamQuestion.誘答分析` from LLM output (`raw.get("誘答分析", {})`) with a `dict[str, str]` coercion.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_math_distractor_prompt.py`:

```python
"""Math prompts and parser wiring for 誘答分析 (issue #115)."""

from __future__ import annotations

import random
from pathlib import Path

from src.context_builder import build_system_prompt, build_user_prompt
from src.sampler import sample_params


def test_math_system_prompt_contains_distractor_guidance() -> None:
    system = build_system_prompt()
    assert "誘答分析的設計" in system
    assert "誘讀題意" in system or "誤讀題意" in system
    assert "概念混淆" in system
    assert "\"誘答分析\"" in system or "誘答分析" in system


def test_math_user_prompt_mc_type_hard_requires_distractor_analysis(tmp_path: Path) -> None:
    params = sample_params(seed=1, q_type="選擇題")
    text, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "誘答分析" in text
    assert "必須" in text  # hard requirement phrasing


def test_math_user_prompt_true_false_hard_requires_distractor_analysis(tmp_path: Path) -> None:
    params = sample_params(seed=1, q_type="是非題")
    text, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "誘答分析" in text
    assert "「是」" in text or "是/非" in text  # keys hint


def test_math_user_prompt_open_response_marks_distractor_optional(tmp_path: Path) -> None:
    params = sample_params(seed=1, q_type="開放式建構反應題")
    text, _ = build_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "常見錯誤" in text  # optional key hint


def test_parse_question_populates_distractor_analysis() -> None:
    from src.cli import _parse_question
    from src.schemas import SampledParams
    from src.sampler import sample_params

    params: SampledParams = sample_params(seed=42, q_type="選擇題")
    raw = {
        "情境": [c.value for c in params.情境],
        "題型種類": params.題型種類.value,
        "題型": params.題型.value,
        "數學思考": [t.value for t in params.數學思考],
        "學習內容": [],
        "題目": ["Q?", "(A) 3", "(B) 4", "(C) 5", "(D) 6"],
        "正確解題分析": ["B"],
        "誘答分析": {"A": "誤讀題意", "B": "正確答案：4。", "C": "概念混淆", "D": "過度推論"},
    }
    q = _parse_question(raw, "q-test", params, "test-model")
    assert q.誘答分析["A"] == "誤讀題意"
    assert q.誘答分析["B"].startswith("正確答案")


def test_parse_question_defaults_to_empty_dict_when_missing() -> None:
    from src.cli import _parse_question
    from src.sampler import sample_params

    params = sample_params(seed=42, q_type="選擇題")
    raw = {
        "情境": [c.value for c in params.情境],
        "題型種類": params.題型種類.value,
        "題型": params.題型.value,
        "數學思考": [t.value for t in params.數學思考],
        "學習內容": [],
        "題目": ["Q?"],
        "正確解題分析": ["A"],
    }
    q = _parse_question(raw, "q-test", params, "test-model")
    assert q.誘答分析 == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_math_distractor_prompt.py -x`
Expected: FAIL — the prompts do not yet contain the guidance strings and `_parse_question` does not yet copy `誘答分析`.

- [ ] **Step 3: Add the system-prompt guidance block**

In `src/context_builder.py`, inside `SYSTEM_PROMPT_TEMPLATE`, insert the following block **immediately after** the `## 命題原則` section (i.e. after item 6 in the numbered list and before `## 課程綱要參考`, around line 84):

```text

## 誘答分析的設計

`誘答分析` 是一個以「選項標籤」為鍵、對應誘答描述為值的 JSON dict：

- **選擇題**：鍵為 `"A"` / `"B"` / `"C"` / `"D"`。錯誤選項描述其針對的認知陷阱（誤讀題意 / 概念混淆 / 部分正確誘騙 / 過度推論 …），正確選項的值為一句 「正確答案：…」。
- **是非題**：鍵為 `"是"` / `"非"`。正確項填「正確答案：…」，錯誤項描述學生常見誤解。
- **建構反應題（封閉式 / 開放式）**：可留空 `{}`，或提供 `{"常見錯誤": "…"}` 描述一項最常見的錯誤。

範例：

```json
"誘答分析": {
  "A": "誤讀題意：將『加權平均』誤算為算術平均。",
  "B": "正確答案：74 分鐘（依人數比計算加權平均）。",
  "C": "概念混淆：把加權係數誤用為比例分子的相反值。",
  "D": "過度推論：只取最大群組的平均值代表整體。"
}
```
```

Then in the JSON schema example (around line 91-112 of `SYSTEM_PROMPT_TEMPLATE`), add a line `"誘答分析": {"A": "...", "B": "正確答案：...", "C": "...", "D": "..."},` immediately after the `"出題概念": "..."` line and before `"題目": [...],`.

- [ ] **Step 4: Add the user-prompt requirement**

In `src/context_builder.py`, inside `USER_PROMPT_TEMPLATE`, extend the `## 重要提醒` numbered list (currently items 1-8, ends around line 177) by appending a new item 9:

```text
9. **誘答分析**：本題若為 選擇題 或 是非題，`誘答分析` **必須**同時涵蓋所有選項標籤（選擇題的 A/B/C/D 或是非題的 是/非）；正確選項填「正確答案：…」，其餘選項描述其針對的錯誤概念。若為 封閉式 / 開放式建構反應題，`誘答分析` 可為空 `{}` 或使用 `{{"常見錯誤": "..."}}` 描述一項最常見錯誤。
```

Note: literal braces inside a `.format()` template need doubling as shown (`{{` / `}}`).

- [ ] **Step 5: Wire the field into `_parse_question`**

In `src/cli.py`, inside `_parse_question` (line 359-454), append a `誘答分析=...` argument to the `ExamQuestion(...)` constructor call (currently ends at line 453). Modify the final return block so it reads:

```python
    raw_distractor = raw.get("誘答分析", {})
    if isinstance(raw_distractor, dict):
        distractor = {str(k): str(v) for k, v in raw_distractor.items()}
    else:
        distractor = {}

    return ExamQuestion(
        id=question_id,
        情境=raw.get("情境", [c.value for c in params.情境]),
        題型種類=raw.get("題型種類", params.題型種類.value),
        題型=raw.get("題型", params.題型.value),
        數學思考=raw_thinking,
        學習內容=parsed_content,
        題目=raw.get("題目", []),
        正確解題分析=raw.get("正確解題分析", []),
        chart_spec=chart_spec,
        核心素養=core_competencies,
        學習表現=parsed_lp,
        題目內容類型=raw.get("題目內容類型", params.題目內容類型),
        出題概念=raw.get("出題概念", ""),
        誘答分析=distractor,
        metadata=QuestionMetadata(
            grade=params.grade,
            style=params.style,
            model=model,
            seed=None,
        ),
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_math_distractor_prompt.py -x`
Expected: PASS — 6 tests green.

- [ ] **Step 7: Commit**

```bash
git add src/context_builder.py src/cli.py tests/test_math_distractor_prompt.py
git commit -m "feat(math): prompt guidance + parser wiring for 誘答分析 (#115)"
```

---

### Task 4: Social studies 子題產生器 prompt guidance and _parse_subquestion wiring

**Files:**
- Modify: `src/social_studies/context_builder.py:925-970` (`build_subquestion_system_prompt`)
- Modify: `src/social_studies/context_builder.py:972-1116` (`build_subquestion_user_prompt`)
- Modify: `src/social_studies/cli.py:304-377` (`_parse_subquestion`)
- Create: `tests/test_social_studies_distractor_prompt.py`

**Interfaces:**
- Consumes: `src.social_studies.schemas.SubQuestion.誘答分析` (Task 1).
- Produces:
  - The 子題產生器 system prompt contains the taxonomy + example JSON block.
  - The 子題產生器 user prompt hard-requires 誘答分析 when the slot 題型 is `選擇題`, and marks it optional for `封閉式建構反應題` / `開放式建構反應題`.
  - `_parse_subquestion` populates `SubQuestion.誘答分析` from `sq_raw.get("誘答分析", {})` with `dict[str, str]` coercion.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_social_studies_distractor_prompt.py`:

```python
"""Social-studies 子題產生器 prompt + parser wiring for 誘答分析."""

from __future__ import annotations

import random
from pathlib import Path

from src.social_studies.context_builder import (
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
)
from src.social_studies.sampler import sample_params as ss_sample_params


def test_subquestion_system_prompt_contains_distractor_taxonomy() -> None:
    prompt = build_subquestion_system_prompt("第四學習階段")
    assert "誘答分析的設計" in prompt
    assert "誤讀題意" in prompt
    assert "概念混淆" in prompt


def test_subquestion_user_prompt_selection_type_hard_requires_analysis(tmp_path: Path) -> None:
    params = ss_sample_params(seed=1)
    plan = {"序號": 1, "題型": "選擇題", "出題概念": "..."}
    text, _ = build_subquestion_user_prompt(
        核心問題="q?",
        文本="passage",
        取材來源=["src"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "誘答分析" in text
    assert "必須" in text


def test_subquestion_user_prompt_constructed_response_marks_optional(tmp_path: Path) -> None:
    params = ss_sample_params(seed=1)
    plan = {"序號": 1, "題型": "開放式建構反應題", "出題概念": "..."}
    text, _ = build_subquestion_user_prompt(
        核心問題="q?",
        文本="passage",
        取材來源=["src"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "常見錯誤" in text


def test_parse_subquestion_populates_distractor_analysis() -> None:
    from src.social_studies.cli import _parse_subquestion

    params = ss_sample_params(seed=1)
    sq_raw = {
        "序號": 1,
        "題型": "選擇題",
        "題目": "問題？(A) x (B) y (C) z (D) w",
        "答案": "B",
        "答案解析": "...",
        "出題概念": "...",
        "科目": ["地理"],
        "誘答分析": {
            "A": "概念混淆",
            "B": "正確答案：y。",
            "C": "誤讀題意",
            "D": "過度推論",
        },
    }
    sq = _parse_subquestion(sq_raw, "q1", params, 1)
    assert sq is not None
    assert sq.誘答分析["A"] == "概念混淆"
    assert sq.誘答分析["B"].startswith("正確答案")


def test_parse_subquestion_defaults_empty_when_missing() -> None:
    from src.social_studies.cli import _parse_subquestion

    params = ss_sample_params(seed=1)
    sq_raw = {
        "序號": 1, "題型": "選擇題", "題目": "Q", "答案": "A",
        "答案解析": "...", "出題概念": "...", "科目": ["地理"],
    }
    sq = _parse_subquestion(sq_raw, "q1", params, 1)
    assert sq is not None
    assert sq.誘答分析 == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_social_studies_distractor_prompt.py -x`
Expected: FAIL — prompts lack the guidance and `_parse_subquestion` does not carry the field yet.

- [ ] **Step 3: Extend `build_subquestion_system_prompt`**

In `src/social_studies/context_builder.py`, inside the f-string returned by `build_subquestion_system_prompt` (starts ~line 934), insert a `## 誘答分析的設計` section **immediately before** the `## 評分規準` section:

```text
## 誘答分析的設計

`誘答分析` 是一個以「選項標籤」為鍵、對應誘答描述為值的 JSON dict：

- **選擇題**：鍵為 `"A"` / `"B"` / `"C"` / `"D"`。錯誤選項描述其針對的認知陷阱（誤讀題意 / 概念混淆 / 部分正確誘騙 / 過度推論 …），正確選項的值為一句 「正確答案：…」。
- **封閉式 / 開放式建構反應題**：可留空 `{{}}`，或提供 `{{"常見錯誤": "…"}}` 描述一項最常見的錯誤。

範例：

```json
"誘答分析": {{
  "A": "概念混淆：把『生產者剩餘』誤讀為『消費者剩餘』。",
  "B": "正確答案：因供給彈性高，稅賦大部分由消費者承擔。",
  "C": "部分正確誘騙：只提到彈性，未連結稅賦轉嫁方向。",
  "D": "過度推論：忽略市場結構的假設。"
}}
```

```

Also add `"誘答分析": {{"A": "...", "B": "正確答案：...", "C": "...", "D": "..."}},` as an extra field in the JSON schema block inside this same f-string (immediately after `"評分規準": []` and before the closing `}}`), so the LLM sees where the field belongs.

- [ ] **Step 4: Extend `build_subquestion_user_prompt`**

In `src/social_studies/context_builder.py`, inside the f-string returned by `build_subquestion_user_prompt` (starts ~line 1074, ends at line 1116), append a new bullet **inside `## 重要提醒`** immediately before item `5. 請只輸出一道小題的 JSON，不要輸出其他文字。`:

```text
5. **誘答分析**：本小題若為 `選擇題`，`誘答分析` **必須**同時涵蓋題目所有選項標籤（A/B/C/D）；正確選項填「正確答案：…」，其餘選項描述其針對的錯誤概念。若為 `封閉式建構反應題` 或 `開放式建構反應題`，可留空 `{{}}` 或使用 `{{"常見錯誤": "..."}}` 描述一項最常見錯誤。
```

Renumber the existing "5. 請只輸出一道小題的 JSON..." to `6.` to keep the list consistent.

Note: the plain f-string requires literal `{}` in the prompt text — write `{{}}` and `{{"常見錯誤": "..."}}` in the source.

- [ ] **Step 5: Wire the field into `_parse_subquestion`**

In `src/social_studies/cli.py`, inside `_parse_subquestion` (line 304-377), add before the `return SubQuestion(...)` block:

```python
        raw_distractor = sq_raw.get("誘答分析", {})
        if isinstance(raw_distractor, dict):
            distractor = {str(k): str(v) for k, v in raw_distractor.items()}
        else:
            distractor = {}
```

Then add `誘答分析=distractor,` to the `SubQuestion(...)` constructor call, positioned immediately after the existing `評分規準=rubric,` line and before `題目內容類型=...`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_studies_distractor_prompt.py -x`
Expected: PASS — 5 tests green.

- [ ] **Step 7: Commit**

```bash
git add src/social_studies/context_builder.py src/social_studies/cli.py tests/test_social_studies_distractor_prompt.py
git commit -m "feat(ss): 子題產生器 prompt + parser wiring for 誘答分析 (#115)"
```

---

### Task 5: Natural sciences 子題產生器 prompt guidance and _parse_subquestion wiring

**Files:**
- Modify: `src/natural_sciences/context_builder.py:579-623` (`build_subquestion_system_prompt`)
- Modify: `src/natural_sciences/context_builder.py:626-764` (`build_subquestion_user_prompt`)
- Modify: `src/natural_sciences/cli.py:240-296` (`_parse_subquestion`)
- Create: `tests/test_natural_sciences_distractor_prompt.py`

**Interfaces:**
- Consumes: `src.natural_sciences.schemas.SubQuestion.誘答分析` (Task 1).
- Produces:
  - 子題產生器 system prompt contains taxonomy + example JSON block.
  - User prompt hard-requires 誘答分析 for `Simple-multiple-choice` and `Complex-multiple-choice`; marks it optional for `Constructed-response`.
  - `_parse_subquestion` populates `SubQuestion.誘答分析`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_natural_sciences_distractor_prompt.py`:

```python
"""Natural-sciences 子題產生器 prompt + parser wiring for 誘答分析."""

from __future__ import annotations

import random
from pathlib import Path

from src.natural_sciences.context_builder import (
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
)
from src.natural_sciences.sampler import sample_params as ns_sample_params


def test_ns_system_prompt_contains_distractor_taxonomy() -> None:
    prompt = build_subquestion_system_prompt("第四學習階段")
    assert "誘答分析的設計" in prompt
    assert "概念混淆" in prompt


def test_ns_user_prompt_simple_mc_hard_requires_analysis(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1, q_type="Simple-multiple-choice")
    plan = {"序號": 1, "題型": "Simple-multiple-choice", "出題概念": "..."}
    text, _ = build_subquestion_user_prompt(
        核心問題="q?",
        文本="passage",
        取材來源=["src"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "誘答分析" in text
    assert "必須" in text


def test_ns_user_prompt_complex_mc_hard_requires_analysis(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1, q_type="Complex-multiple-choice")
    plan = {"序號": 1, "題型": "Complex-multiple-choice", "出題概念": "..."}
    text, _ = build_subquestion_user_prompt(
        核心問題="q?",
        文本="passage",
        取材來源=["src"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "誘答分析" in text


def test_ns_user_prompt_constructed_response_marks_optional(tmp_path: Path) -> None:
    params = ns_sample_params(seed=1, q_type="Constructed-response")
    plan = {"序號": 1, "題型": "Constructed-response", "出題概念": "..."}
    text, _ = build_subquestion_user_prompt(
        核心問題="q?",
        文本="passage",
        取材來源=["src"],
        sq_plan=plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "常見錯誤" in text


def test_ns_parse_subquestion_populates_and_defaults_distractor_analysis() -> None:
    from src.natural_sciences.cli import _parse_subquestion

    params = ns_sample_params(seed=1, q_type="Simple-multiple-choice")
    sq_raw = {
        "序號": 1,
        "題型": "Simple-multiple-choice",
        "題目": "Q? (A) x (B) y (C) z (D) w",
        "答案": "B",
        "答案解析": "...",
        "出題概念": "...",
        "科目": ["自然科學"],
        "誘答分析": {
            "A": "概念混淆",
            "B": "正確答案：y。",
            "C": "誤讀題意",
            "D": "過度推論",
        },
    }
    sq = _parse_subquestion(sq_raw, "q1", params, 1)
    assert sq is not None
    assert sq.誘答分析["C"] == "誤讀題意"

    sq_raw_2 = dict(sq_raw)
    sq_raw_2.pop("誘答分析")
    sq2 = _parse_subquestion(sq_raw_2, "q1", params, 1)
    assert sq2 is not None
    assert sq2.誘答分析 == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_natural_sciences_distractor_prompt.py -x`
Expected: FAIL — prompts lack the guidance strings and `_parse_subquestion` does not carry the field.

- [ ] **Step 3: Extend `build_subquestion_system_prompt`**

In `src/natural_sciences/context_builder.py`, inside the f-string returned by `build_subquestion_system_prompt` (starts ~line 587), insert a `## 誘答分析的設計` section immediately before the `## 評分規準` block:

```text
## 誘答分析的設計

`誘答分析` 是一個以「選項標籤」為鍵、對應誘答描述為值的 JSON dict：

- **Simple / Complex multiple-choice**：鍵為 `"A"` / `"B"` / `"C"` / `"D"`（Complex 的複選題請對每個獨立敘述使用 `"A是"` / `"A非"` 等鍵，或直接沿用 A/B/C/D）。錯誤選項描述其針對的科學迷思（概念混淆 / 誤讀證據 / 過度推論 / 忽略前提 …），正確選項的值為一句 「正確答案：…」。
- **Constructed-response**：可留空 `{{}}`，或提供 `{{"常見錯誤": "…"}}` 描述一項最常見的科學迷思。

範例：

```json
"誘答分析": {{
  "A": "誤讀證據：把長期趨勢誤解為短期波動。",
  "B": "正確答案：能量守恆造成振幅衰減。",
  "C": "概念混淆：把慣性誤讀為摩擦力效應。",
  "D": "過度推論：從單一實驗推論到所有系統。"
}}
```

```

Add `"誘答分析": {{"A": "...", "B": "正確答案：...", "C": "...", "D": "..."}},` as an extra key in the JSON schema block inside this same f-string, positioned after `"評分規準": []` and before the closing `}}`.

- [ ] **Step 4: Extend `build_subquestion_user_prompt`**

In `src/natural_sciences/context_builder.py`, inside the trailing f-string of `build_subquestion_user_prompt` (starts ~line 723), append to the `## 重要提醒` list before the last item `4. 請只輸出一道小題的 JSON，不要輸出其他文字。`:

```text
4. **誘答分析**：本小題若為 `Simple-multiple-choice` 或 `Complex-multiple-choice`，`誘答分析` **必須**同時涵蓋題目所有選項標籤（預設 A/B/C/D）；正確選項填「正確答案：…」，其餘選項描述其針對的科學迷思。若為 `Constructed-response`，可留空 `{{}}` 或使用 `{{"常見錯誤": "..."}}` 描述一項最常見的科學迷思。
```

Renumber the existing "4. 請只輸出一道小題的 JSON..." to `5.`.

- [ ] **Step 5: Wire the field into `_parse_subquestion`**

In `src/natural_sciences/cli.py`, inside `_parse_subquestion` (line 240-296), add before the `return SubQuestion(...)` block:

```python
        raw_distractor = sq_raw.get("誘答分析", {})
        if isinstance(raw_distractor, dict):
            distractor = {str(k): str(v) for k, v in raw_distractor.items()}
        else:
            distractor = {}
```

Then add `誘答分析=distractor,` to the `SubQuestion(...)` constructor immediately after `評分規準=rubric,`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_natural_sciences_distractor_prompt.py -x`
Expected: PASS — 5 tests green.

- [ ] **Step 7: Commit**

```bash
git add src/natural_sciences/context_builder.py src/natural_sciences/cli.py tests/test_natural_sciences_distractor_prompt.py
git commit -m "feat(ns): 子題產生器 prompt + parser wiring for 誘答分析 (#115)"
```

---

### Task 6: Wire validate_distractor_keys into all three verifiers

**Files:**
- Modify: `src/verifier.py:72-127` (`verify_question`)
- Modify: `src/social_studies/verifier.py:99-150` (`verify_question`)
- Modify: `src/natural_sciences/verifier.py:107-161` (`verify_question`)
- Create: `tests/test_verifiers_distractor_warnings.py`

**Interfaces:**
- Consumes: `src.common.distractor.validate_distractor_keys` (Task 2); `誘答分析` on math `ExamQuestion` and SS/NS `SubQuestion` (Task 1).
- Produces: `VerificationResult.details` is post-processed to append `[誘答分析提醒] <warning>` lines. `passed` is unchanged (warnings never fail a question).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_verifiers_distractor_warnings.py`:

```python
"""verify_question appends distractor warnings without failing the question."""

from __future__ import annotations

import json

import pytest


class _FakeVerifierClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def generate_with_image(self, system, user, image_path=None, purpose="verify"):
        return json.dumps(self._payload, ensure_ascii=False)


def _passed_payload() -> dict:
    return {
        "my_answer": "B", "provided_answer": "B",
        "answer_match": True, "passed": True,
        "details": "看起來沒問題。",
    }


def test_math_verifier_appends_distractor_warning_when_keys_mismatch() -> None:
    from src.schemas import ExamQuestion
    from src.verifier import verify_question

    q = ExamQuestion(
        情境=["個人"], 題型種類="單一題", 題型="選擇題",
        數學思考=["形成"], 學習內容=[],
        題目=["Q? (A) 3 (B) 4 (C) 5 (D) 6"],
        正確解題分析=["B"],
        誘答分析={"A": "x", "B": "正確答案：4。", "C": "x"},  # missing D
    )
    client = _FakeVerifierClient(_passed_payload())
    result = verify_question(client, q)
    assert result.passed is True
    assert "誘答分析提醒" in result.details
    assert "D" in result.details


def test_ss_verifier_appends_distractor_warning() -> None:
    from src.social_studies.schemas import ExamQuestion as SSExamQuestion, SubQuestion
    from src.social_studies.verifier import verify_question

    q = SSExamQuestion(
        情境=["公共"], 題型種類="題組題", 題型="選擇題",
        閱讀歷程=["擷取訊息"], 文本形式="連續文本",
        subquestions=[
            SubQuestion(
                序號=1, 題型="選擇題",
                題目="Q? (A) x (B) y (C) z (D) w",
                答案="A", 誘答分析={"A": "正確答案：x。"},  # missing B/C/D
            ),
        ],
    )
    client = _FakeVerifierClient(_passed_payload())
    result = verify_question(client, q)
    assert result.passed is True
    assert "誘答分析提醒" in result.details


def test_ns_verifier_appends_distractor_warning() -> None:
    from src.natural_sciences.schemas import ExamQuestion as NSExamQuestion, SubQuestion
    from src.natural_sciences.verifier import verify_question

    q = NSExamQuestion(
        情境=["Personal"], 題型種類="題組題", 題型="Simple-multiple-choice",
        subquestions=[
            SubQuestion(
                序號=1, 題型="Simple-multiple-choice",
                題目="Q? (A) x (B) y (C) z (D) w",
                答案="A", 誘答分析={"A": "正確答案：x。"},
            ),
        ],
    )
    client = _FakeVerifierClient(_passed_payload())
    result = verify_question(client, q)
    assert result.passed is True
    assert "誘答分析提醒" in result.details


@pytest.mark.parametrize("subject", ["math", "ss", "ns"])
def test_verifier_leaves_details_unchanged_when_no_warnings(subject: str) -> None:
    payload = _passed_payload()
    if subject == "math":
        from src.schemas import ExamQuestion
        from src.verifier import verify_question
        q = ExamQuestion(
            情境=["個人"], 題型種類="單一題", 題型="選擇題",
            數學思考=["形成"], 學習內容=[],
            題目=["Q?"], 正確解題分析=["A"],
        )
    elif subject == "ss":
        from src.social_studies.schemas import ExamQuestion as SSQ, SubQuestion
        from src.social_studies.verifier import verify_question
        q = SSQ(
            情境=["公共"], 題型種類="題組題", 題型="選擇題",
            閱讀歷程=["擷取訊息"], 文本形式="連續文本",
            subquestions=[SubQuestion(序號=1, 題型="選擇題", 題目="Q?", 答案="A")],
        )
    else:
        from src.natural_sciences.schemas import ExamQuestion as NSQ, SubQuestion
        from src.natural_sciences.verifier import verify_question
        q = NSQ(
            情境=["Personal"], 題型種類="題組題", 題型="Simple-multiple-choice",
            subquestions=[SubQuestion(序號=1, 題型="Simple-multiple-choice", 題目="Q?", 答案="A")],
        )
    client = _FakeVerifierClient(payload)
    result = verify_question(client, q)
    assert result.passed is True
    assert "誘答分析提醒" not in result.details
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_verifiers_distractor_warnings.py -x`
Expected: FAIL — none of the verifiers currently invoke `validate_distractor_keys`, so `details` never contains the `誘答分析提醒` marker.

- [ ] **Step 3: Modify `src/verifier.py`**

At the top of `src/verifier.py`, add:

```python
from src.common.distractor import validate_distractor_keys
```

Then, in `verify_question` (line 72-127), immediately before the final `return VerificationResult(...)`, insert:

```python
    # Non-blocking distractor-key audit (warnings only; never flips passed).
    question_text = "\n".join(question.題目)
    warnings = validate_distractor_keys(question_text, question.誘答分析)
    details = result.get("details", "")
    if warnings:
        details = details.rstrip()
        details += "\n\n[誘答分析提醒] " + " ".join(warnings)
```

Replace the existing `details=result.get("details", ""),` line in the `VerificationResult(...)` constructor with `details=details,` so the augmented value is used.

- [ ] **Step 4: Modify `src/social_studies/verifier.py`**

At the top of `src/social_studies/verifier.py`, add:

```python
from src.common.distractor import validate_distractor_keys
```

Then, in `verify_question` (line 99-150), immediately before the final `return VerificationResult(...)`, insert:

```python
    # Aggregate warnings across all subquestions; math field lives per-小題 for SS.
    all_warnings: list[str] = []
    for sq in question.subquestions:
        warnings = validate_distractor_keys(sq.題目, sq.誘答分析)
        for w in warnings:
            all_warnings.append(f"第{sq.序號}題：{w}")
    details = result.get("details", "")
    if all_warnings:
        details = details.rstrip()
        details += "\n\n[誘答分析提醒] " + "；".join(all_warnings)
```

Replace `details=result.get("details", ""),` with `details=details,` in the `VerificationResult(...)` constructor.

- [ ] **Step 5: Modify `src/natural_sciences/verifier.py`**

At the top of `src/natural_sciences/verifier.py`, add:

```python
from src.common.distractor import validate_distractor_keys
```

Then, in `verify_question` (line 107-161), immediately before the final `return VerificationResult(...)`, insert:

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
```

Replace `details=result.get("details", ""),` with `details=details,` in the `VerificationResult(...)` constructor.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_verifiers_distractor_warnings.py -x`
Expected: PASS — 6 tests green.

- [ ] **Step 7: Commit**

```bash
git add src/verifier.py src/social_studies/verifier.py src/natural_sciences/verifier.py tests/test_verifiers_distractor_warnings.py
git commit -m "feat(verify): non-blocking 誘答分析 key audit across all three subjects (#115)"
```

---

### Task 7: Correctors — allow 誘答分析 to mutate and remind the model

**Files:**
- Modify: `src/corrector.py:20-53` (`_CORRECTION_SYSTEM_PROMPT_CORE`) and `src/corrector.py:57-137` (`correct_question`)
- Modify: `src/social_studies/corrector.py:13-34` (`_CORRECTION_SYSTEM_PROMPT_CORE`) and `src/social_studies/corrector.py:51-167` (`correct_question`)
- Modify: `src/natural_sciences/corrector.py:18-32` (`_CORRECTION_SYSTEM_PROMPT_CORE`) and `src/natural_sciences/corrector.py:55-167` (`correct_question`)
- Create: `tests/test_correctors_distractor_mutation.py`

**Interfaces:**
- Consumes: 誘答分析 fields on the schemas (Task 1); the corrected `raw` JSON from the LLM.
- Produces:
  - Math: corrected `ExamQuestion.誘答分析` is picked up from LLM output (`update["誘答分析"] = ...`), replacing the original when the corrector emits a new dict; otherwise the original is preserved.
  - SS: per-小題 `誘答分析` is picked up from each `subquestions[i]` dict in the LLM output while all curriculum-metadata fields remain frozen from the original.
  - NS: same pattern as SS.
  - All three correction prompts now instruct the LLM: "若答案有改動，`誘答分析` 也必須同步反映新的正解與誘答陷阱，並保持選項標籤一致；未指定選項標籤時可留空 `{}`。"

- [ ] **Step 1: Write the failing tests**

Create `tests/test_correctors_distractor_mutation.py`:

```python
"""Correctors update 誘答分析 when the LLM emits a new version; else preserve it."""

from __future__ import annotations


class _FakeMathClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate_json(self, *_a, **_kw):
        return self.payload


def _math_question():
    from src.schemas import ExamQuestion
    return ExamQuestion(
        情境=["個人"], 題型種類="單一題", 題型="選擇題",
        數學思考=["形成"], 學習內容=[],
        題目=["Q? (A) 3 (B) 4 (C) 5 (D) 6"],
        正確解題分析=["B"],
        誘答分析={"A": "old", "B": "old-correct", "C": "old", "D": "old"},
    )


def test_math_corrector_replaces_distractor_when_llm_emits_new() -> None:
    from src.corrector import correct_question
    from src.schemas import VerificationResult
    q = _math_question()
    client = _FakeMathClient({
        "題目": q.題目, "正確解題分析": ["A"],
        "誘答分析": {
            "A": "正確答案：新解答。",
            "B": "誘導：新概念混淆。",
            "C": "n", "D": "n",
        },
    })
    corrected = correct_question(
        client, q,
        VerificationResult(passed=False, answer_match=False, details="wrong"),
    )
    assert corrected.誘答分析["A"].startswith("正確答案")
    assert corrected.誘答分析["B"].startswith("誘導")


def test_math_corrector_preserves_original_distractor_when_llm_omits_it() -> None:
    from src.corrector import correct_question
    from src.schemas import VerificationResult
    q = _math_question()
    client = _FakeMathClient({"題目": q.題目, "正確解題分析": ["A"]})
    corrected = correct_question(
        client, q,
        VerificationResult(passed=False, answer_match=False, details="x"),
    )
    assert corrected.誘答分析 == {"A": "old", "B": "old-correct", "C": "old", "D": "old"}


class _FakeSSClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate_json(self, *_a, **_kw):
        return self.payload


def test_ss_corrector_updates_subquestion_distractor() -> None:
    from src.social_studies.corrector import correct_question
    from src.social_studies.schemas import ExamQuestion, SubQuestion, VerificationResult
    q = ExamQuestion(
        情境=["公共"], 題型種類="題組題", 題型="選擇題",
        閱讀歷程=["擷取訊息"], 文本形式="連續文本",
        subquestions=[
            SubQuestion(
                id="sq1", 序號=1, 題型="選擇題",
                題目="Q?", 答案="A",
                誘答分析={"A": "old-correct", "B": "old"},
            ),
        ],
    )
    client = _FakeSSClient({
        "subquestions": [{
            "序號": 1, "題型": "選擇題", "題目": "Q?", "答案": "B",
            "答案解析": "corrected",
            "誘答分析": {"A": "誘導：舊解答其實不對。", "B": "正確答案：B。"},
        }],
    })
    corrected = correct_question(
        client, q,
        VerificationResult(passed=False, answer_match=False, details="wrong answer"),
    )
    assert corrected.subquestions[0].誘答分析["B"].startswith("正確答案")


class _FakeNSClient(_FakeSSClient):
    pass


def test_ns_corrector_updates_subquestion_distractor() -> None:
    from src.natural_sciences.corrector import correct_question
    from src.natural_sciences.schemas import ExamQuestion, SubQuestion, VerificationResult
    q = ExamQuestion(
        情境=["Personal"], 題型種類="題組題", 題型="Simple-multiple-choice",
        subquestions=[
            SubQuestion(
                id="sq1", 序號=1, 題型="Simple-multiple-choice",
                題目="Q?", 答案="A",
                誘答分析={"A": "old-correct", "B": "old"},
            ),
        ],
    )
    client = _FakeNSClient({
        "subquestions": [{
            "序號": 1, "題型": "Simple-multiple-choice",
            "題目": "Q?", "答案": "B", "答案解析": "corrected",
            "誘答分析": {"A": "誘導：舊解答其實不對。", "B": "正確答案：B。"},
        }],
    })
    corrected = correct_question(
        client, q,
        VerificationResult(passed=False, answer_match=False, details="wrong answer"),
    )
    assert corrected.subquestions[0].誘答分析["B"].startswith("正確答案")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_correctors_distractor_mutation.py -x`
Expected: FAIL — none of the correctors currently copies 誘答分析 into `update` or into the per-小題 constructor.

- [ ] **Step 3: Modify `src/corrector.py`**

Extend the prompt copy (in `_CORRECTION_SYSTEM_PROMPT_CORE`, ~line 20-33). Replace the current line

```text
- 絕對不可修改：情境、題型種類、題型、數學思考、學習內容、學習表現、核心素養、出題概念、題目內容類型、id、metadata。
```

with:

```text
- 絕對不可修改：情境、題型種類、題型、數學思考、學習內容、學習表現、核心素養、出題概念、題目內容類型、id、metadata。
- 若答案或選項有改動，`誘答分析` 必須同步反映新的正解與誘答陷阱：正解鍵改為「正確答案：…」，其他鍵改為對應新誘答的錯誤概念。選項標籤必須與新的題目一致；若題目沒有 (A)-(D) 標籤，可留空 `{}`。
```

Inside `correct_question`, after the existing block that parses `raw_spec` (around line 127-132), add:

```python
    raw_distractor = corrected_data.get("誘答分析")
    if isinstance(raw_distractor, dict):
        update["誘答分析"] = {str(k): str(v) for k, v in raw_distractor.items()}
```

- [ ] **Step 4: Modify `src/social_studies/corrector.py`**

In `_CORRECTION_SYSTEM_PROMPT_CORE` (line 13-27), replace the existing line

```text
- 絕對不可修改：核心問題、情境、題型種類、題型、閱讀歷程、文本形式、id、metadata、
  各小題的 學習內容/學習表現/核心素養/出題概念/出題指示/科目/年級。
```

with:

```text
- 絕對不可修改：核心問題、情境、題型種類、題型、閱讀歷程、文本形式、id、metadata、
  各小題的 學習內容/學習表現/核心素養/出題概念/出題指示/科目/年級。
- 若某小題的答案或選項有改動，該小題的 `誘答分析` 必須同步反映新的正解與誘答陷阱：正解鍵改為「正確答案：…」，其他鍵改為新的誤解描述。選項標籤必須與新題目一致；若題目沒有 (A)-(D) 標籤，可留空 `{}`。
```

Inside the `for i, sq_raw in enumerate(corrected_data["subquestions"])` loop of `correct_question` (line 111-153), extend the `SubQuestion(...)` constructor call to include:

```python
                    誘答分析=(
                        {str(k): str(v) for k, v in sq_raw.get("誘答分析", {}).items()}
                        if isinstance(sq_raw.get("誘答分析"), dict)
                        else (original.誘答分析 if original else {})
                    ),
```

Position this new keyword argument immediately after `評分規準=rubric if rubric else (original.評分規準 if original else []),`.

- [ ] **Step 5: Modify `src/natural_sciences/corrector.py`**

In `_CORRECTION_SYSTEM_PROMPT_CORE` (line 18-32), replace the existing line

```text
- 絕對不可修改：核心問題、情境、情境子類別、題型種類、題型、科學能力、id、metadata，
  以及各小題的 學習內容/學習表現/科學能力/出題概念/科目/年級。
```

with:

```text
- 絕對不可修改：核心問題、情境、情境子類別、題型種類、題型、科學能力、id、metadata，
  以及各小題的 學習內容/學習表現/科學能力/出題概念/科目/年級。
- 若某小題的答案或選項有改動，該小題的 `誘答分析` 必須同步反映新的正解與誘答陷阱：正解鍵改為「正確答案：…」，其他鍵改為新的科學迷思描述。選項標籤必須與新題目一致；若題目為 Constructed-response 或沒有 (A)-(D) 標籤，可留空 `{}`。
```

Inside the `for i, sq_raw in enumerate(corrected_data["subquestions"])` loop of `correct_question` (line 121-155), extend the `SubQuestion(...)` constructor call to include:

```python
                    誘答分析=(
                        {str(k): str(v) for k, v in sq_raw.get("誘答分析", {}).items()}
                        if isinstance(sq_raw.get("誘答分析"), dict)
                        else (original.誘答分析 if original else {})
                    ),
```

Position this immediately after `評分規準=rubric if rubric else (original.評分規準 if original else []),`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_correctors_distractor_mutation.py -x`
Expected: PASS — 4 tests green.

- [ ] **Step 7: Commit**

```bash
git add src/corrector.py src/social_studies/corrector.py src/natural_sciences/corrector.py tests/test_correctors_distractor_mutation.py
git commit -m "feat(correct): 誘答分析 tracks corrected answers across all three subjects (#115)"
```

---

### Task 8: Refresh ≥2 few-shot examples per subject with realistic 誘答分析

**Files:**
- Modify: `data/few_shot/text_only/example_01.json` (math — first example object, add 誘答分析 inside the `question` dict)
- Modify: `data/few_shot/text_only/112P_questions.json` (math — first two example objects)
- Modify: `data/few_shot/creative_scenario/example_01.json` (math — one additional example)
- Modify: `data/social_studies/few_shot/mixed_text_114P_Society_questions.json` (SS — first example: add 誘答分析 to first two 小題 objects inside `subquestions`)
- Modify: `data/social_studies/few_shot/text_only_READ_Sample_questions.json` (SS — first example: add 誘答分析 to one 小題)
- Modify: `data/natural_sciences/few_shot/Simple-multiple-choice/pisa_examples.json` (NS — first example's subquestions[0])
- Modify: `data/natural_sciences/few_shot/Complex-multiple-choice/pisa_examples.json` (NS — first example's subquestions[0])
- Create: `tests/test_few_shot_distractor_coverage.py`

**Interfaces:**
- Consumes: `src.data_loader.load_few_shot_examples`, `src.social_studies.data_loader.load_few_shot_example_groups`, `src.natural_sciences.data_loader.load_few_shot_example_groups`.
- Produces: at least two examples per subject whose `question` (or `subquestions[i]`) dict contains a non-empty `誘答分析`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_few_shot_distractor_coverage.py`:

```python
"""At least 2 few-shot examples per subject must include realistic 誘答分析."""

from __future__ import annotations

import json
from pathlib import Path


def _iter_math_questions() -> list[dict]:
    root = Path("data/few_shot")
    out: list[dict] = []
    for f in root.glob("*/*.json"):
        with open(f, encoding="utf-8") as fh:
            loaded = json.load(fh)
        pool = loaded if isinstance(loaded, list) else [loaded]
        for ex in pool:
            q = ex.get("question", ex) if isinstance(ex, dict) else {}
            if isinstance(q, dict):
                out.append(q)
    return out


def _iter_ss_questions() -> list[dict]:
    root = Path("data/social_studies/few_shot")
    out: list[dict] = []
    for f in root.glob("*.json"):
        with open(f, encoding="utf-8") as fh:
            loaded = json.load(fh)
        pool = loaded if isinstance(loaded, list) else [loaded]
        for ex in pool:
            q = ex.get("question", ex) if isinstance(ex, dict) else {}
            if isinstance(q, dict):
                out.append(q)
    return out


def _iter_ns_questions() -> list[dict]:
    root = Path("data/natural_sciences/few_shot")
    out: list[dict] = []
    for f in root.glob("*/*.json"):
        with open(f, encoding="utf-8") as fh:
            loaded = json.load(fh)
        pool = loaded if isinstance(loaded, list) else [loaded]
        for ex in pool:
            q = ex.get("question", ex) if isinstance(ex, dict) else {}
            if isinstance(q, dict):
                out.append(q)
    return out


def _count_with_distractor(questions: list[dict]) -> int:
    n = 0
    for q in questions:
        if isinstance(q.get("誘答分析"), dict) and q["誘答分析"]:
            n += 1
            continue
        for sq in q.get("subquestions", []) or []:
            if isinstance(sq, dict) and isinstance(sq.get("誘答分析"), dict) and sq["誘答分析"]:
                n += 1
                break
    return n


def test_math_few_shot_has_at_least_two_distractor_examples() -> None:
    assert _count_with_distractor(_iter_math_questions()) >= 2


def test_ss_few_shot_has_at_least_two_distractor_examples() -> None:
    assert _count_with_distractor(_iter_ss_questions()) >= 2


def test_ns_few_shot_has_at_least_two_distractor_examples() -> None:
    assert _count_with_distractor(_iter_ns_questions()) >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_few_shot_distractor_coverage.py -x`
Expected: FAIL — 0 examples per subject currently contain 誘答分析.

- [ ] **Step 3: Update math few-shot files**

For each math file listed above, add a `"誘答分析": { ... }` key inside the `"question"` dict of the target example, matching the 題型 (`選擇題` → A/B/C/D keys) and the specific 選項 semantics visible in that example's `題目` array. For instance in `data/few_shot/text_only/example_01.json`, after the `"正確解題分析": [...]` array of the first example, add:

```json
    "誘答分析": {
      "A": "誤讀題意：忽略人數比例，僅以算術平均 (65+80+70)÷3 ≈ 71.67 計算。",
      "B": "正確答案：74 分鐘（依人數比 2:5:3 加權平均）。",
      "C": "概念混淆：把加權係數誤用為總份數 10 的其他分數，計算過程走岔。",
      "D": "過度推論：只取捷運組平均 80 作為整體代表值，忽略其他兩組。"
    }
```

Write concrete `誘答分析` blocks that match each example's actual options for the other files as well. Ensure at least 2 math example objects end up with a non-empty `誘答分析` dict (any combination of files above is acceptable as long as the total across math ≥ 2).

- [ ] **Step 4: Update SS few-shot files**

In `data/social_studies/few_shot/mixed_text_114P_Society_questions.json`, add a `"誘答分析": { "A": "...", "B": "正確答案：...", "C": "...", "D": "..." }` key inside `question.subquestions[0]` and inside `question.subquestions[1]` (both should be 選擇題; verify the 題型 field first — for 建構反應題 subquestions use `{"常見錯誤": "..."}` instead).

In `data/social_studies/few_shot/text_only_READ_Sample_questions.json`, do the same for the first example's first 小題. Ensure ≥ 2 SS examples now have non-empty 誘答分析 somewhere in their `subquestions[*]`.

- [ ] **Step 5: Update NS few-shot files**

In `data/natural_sciences/few_shot/Simple-multiple-choice/pisa_examples.json`, add a realistic `"誘答分析": { "A": "...", "B": "正確答案：...", "C": "...", "D": "..." }` key inside the first example's `question.subquestions[0]`.

In `data/natural_sciences/few_shot/Complex-multiple-choice/pisa_examples.json`, do the same for the first example's first 小題. Ensure ≥ 2 NS examples now have non-empty 誘答分析.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_few_shot_distractor_coverage.py -x`
Expected: PASS — 3 tests green.

- [ ] **Step 7: Commit**

```bash
git add data/few_shot data/social_studies/few_shot data/natural_sciences/few_shot tests/test_few_shot_distractor_coverage.py
git commit -m "docs(few-shot): add 誘答分析 to ≥2 examples per subject (#115)"
```

---

### Task 9: Frontend — TypeScript type, i18n keys, and QuestionCard collapsible panel

**Files:**
- Modify: `web/src/hooks/useGenerate.ts:47-91` (`SubQuestion` interface + `ExamQuestion` interface)
- Modify: `web/src/i18n/messages.ts:5-168` (`en-US` block) and `web/src/i18n/messages.ts:169-332` (`zh-TW` block)
- Modify: `web/src/components/QuestionCard.tsx:67-147` (`SubQuestionBlock`) and `web/src/components/QuestionCard.tsx:287-316` (math flat section)
- Modify: `web/src/components/QuestionCard.test.tsx` (add rendering + hidden-when-empty coverage)

**Interfaces:**
- Consumes: JSON emitted by the backend with `誘答分析: Record<string, string>`.
- Produces:
  - `SubQuestion.誘答分析?: Record<string, string>` in TypeScript.
  - `ExamQuestion.誘答分析?: Record<string, string>` in TypeScript.
  - New i18n keys `card.distractorAnalysis`, `card.hideDistractor`, `card.showDistractor` in both languages.
  - `<DistractorPanel>` React component that renders an amber-toned collapsible section with per-option rows.
  - Panel is rendered only when the dict is non-empty; it lives inside the "answer/solution shown" branch (SS/NS: inside `SubQuestionBlock`'s showAnswer branch; math: inside `showSolution` branch).

- [ ] **Step 1: Restore vitest tooling if not present**

Some earlier commits may have removed vitest from `web/package.json`. Before writing tests, verify:

```bash
cd /workspace/exam-generation/web
npm test -- --run 2>&1 | head -20
```

If the command exits `0` (or reports an existing test file passing), skip; if it fails with `vitest: command not found`, reinstall:

```bash
cd /workspace/exam-generation/web
npm install -D vitest @vitest/ui jsdom @testing-library/jest-dom @testing-library/react @testing-library/user-event
```

Then add `"test": "vitest run"` and `"test:watch": "vitest"` to `web/package.json` `"scripts"` if missing.

- [ ] **Step 2: Write the failing tests**

Append the following tests to `web/src/components/QuestionCard.test.tsx`. Update the `question` fixture at the top to include an SS-shape example too:

```tsx
import { fireEvent } from "@testing-library/react";
import type { SubQuestion } from "../hooks/useGenerate";

const ssSub: SubQuestion = {
  id: "sq1",
  序號: 1,
  年級: 8,
  科目: ["地理"],
  核心素養: ["社-J-A2"],
  學習內容: [],
  學習表現: [],
  出題概念: "",
  題型: "選擇題",
  題目: "Q? (A) x (B) y (C) z (D) w",
  答案: "B",
  答案解析: "…",
  評分規準: [],
  誘答分析: {
    A: "誤讀題意",
    B: "正確答案：y。",
    C: "概念混淆",
    D: "過度推論",
  },
};

const ssQuestion: ExamQuestion = {
  id: "ss1",
  情境: ["公共"],
  題型種類: "題組題",
  題型: "選擇題",
  核心問題: "core?",
  文本: "passage",
  subquestions: [ssSub],
  題目: ["passage", ssSub.題目],
  正確解題分析: ["B"],
};

describe("QuestionCard distractor panel", () => {
  it("renders 誘答分析 rows inside a subquestion when the dict is non-empty", () => {
    render(<QuestionCard question={ssQuestion} phase="verified" isFinal={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Answer" }));
    fireEvent.click(screen.getByRole("button", { name: "Show Distractor Analysis" }));
    expect(screen.getByText("誤讀題意")).toBeInTheDocument();
    expect(screen.getByText(/正確答案：y/)).toBeInTheDocument();
  });

  it("does not render the toggle button when 誘答分析 is empty", () => {
    const emptySub: SubQuestion = { ...ssSub, 誘答分析: {} };
    const empty: ExamQuestion = { ...ssQuestion, subquestions: [emptySub] };
    render(<QuestionCard question={empty} phase="verified" isFinal={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Answer" }));
    expect(screen.queryByRole("button", { name: "Show Distractor Analysis" })).not.toBeInTheDocument();
  });

  it("renders 誘答分析 on math flat questions", () => {
    const mathQ: ExamQuestion = {
      ...question,
      誘答分析: { A: "誤讀題意", B: "正確答案：4。", C: "x", D: "y" },
    };
    render(<QuestionCard question={mathQ} phase="verified" isFinal={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Solution" }));
    fireEvent.click(screen.getByRole("button", { name: "Show Distractor Analysis" }));
    expect(screen.getByText(/正確答案：4/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /workspace/exam-generation/web && npm test -- src/components/QuestionCard.test.tsx`
Expected: FAIL — `ExamQuestion` has no `誘答分析`, `SubQuestion` has no `誘答分析`, no `card.distractorAnalysis` translation, no panel component.

- [ ] **Step 4: Extend TypeScript interfaces**

In `web/src/hooks/useGenerate.ts`, extend the interfaces (currently at lines 47-91):

```ts
export interface SubQuestion {
  // ...existing fields unchanged...
  評分規準?: RubricEntry[];
  誘答分析?: Record<string, string>;
  題目內容類型?: string;
  image_generation_mode?: "html" | "gpt_image";
  圖片?: string | null;
  chart_spec?: unknown;
  image_base64?: string;
}

export interface ExamQuestion {
  // ...existing fields unchanged...
  出題概念?: string;
  誘答分析?: Record<string, string>;
  metadata?: unknown;
  image_base64?: string;
}
```

(Only the two new lines are additions; keep the rest of the interfaces exactly as before.)

- [ ] **Step 5: Add i18n keys in both languages**

In `web/src/i18n/messages.ts`, add to the `en-US` block after `"card.rubric": "Rubric",` (~line 157):

```ts
    "card.distractorAnalysis": "Distractor Analysis",
    "card.showDistractor": "Show Distractor Analysis",
    "card.hideDistractor": "Hide Distractor Analysis",
```

Add to the `zh-TW` block after `"card.rubric": "評分規準",` (~line 320):

```ts
    "card.distractorAnalysis": "誘答分析",
    "card.showDistractor": "顯示誘答分析",
    "card.hideDistractor": "隱藏誘答分析",
```

- [ ] **Step 6: Add the DistractorPanel component + wire it into QuestionCard**

In `web/src/components/QuestionCard.tsx`, add a new component definition immediately before `SubQuestionBlock` (around line 67):

```tsx
function DistractorPanel({ analysis }: { analysis: Record<string, string> }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const entries = Object.entries(analysis);
  if (entries.length === 0) return null;
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-sm font-medium text-amber-700 hover:text-amber-800"
      >
        {open ? t("card.hideDistractor") : t("card.showDistractor")}
      </button>
      {open && (
        <div className="mt-2 rounded border border-amber-200 bg-amber-50 p-3 space-y-1 text-sm">
          <div className="font-medium text-amber-800 mb-1">{t("card.distractorAnalysis")}</div>
          {entries.map(([label, note]) => (
            <div key={label} className="flex gap-2 items-start">
              <span className="inline-flex shrink-0 items-center rounded bg-amber-200 px-1.5 py-0.5 text-xs font-bold text-amber-900">
                {label}
              </span>
              <span className="whitespace-pre-wrap text-amber-900">{note}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

Then inside `SubQuestionBlock`, immediately after the `評分規準` block inside the `showAnswer` guard (~line 128-141), add:

```tsx
            {sub.誘答分析 && Object.keys(sub.誘答分析).length > 0 && (
              <DistractorPanel analysis={sub.誘答分析} />
            )}
```

And in the math flat branch, inside the `showSolution && (...)` block (~line 305-313), append after the `正確解題分析` paragraphs:

```tsx
                {question.誘答分析 && Object.keys(question.誘答分析).length > 0 && (
                  <DistractorPanel analysis={question.誘答分析} />
                )}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /workspace/exam-generation/web && npm test`
Expected: PASS — all existing tests plus the 3 new distractor tests green.

- [ ] **Step 8: Verify lint + build**

Run: `cd /workspace/exam-generation/web && npm run lint && npm run build`
Expected: no lint errors; `tsc -b && vite build` succeeds.

- [ ] **Step 9: Commit**

```bash
cd /workspace/exam-generation
git add web/src/hooks/useGenerate.ts web/src/i18n/messages.ts web/src/components/QuestionCard.tsx web/src/components/QuestionCard.test.tsx
git commit -m "feat(web): collapsible 誘答分析 panel per 小題 + math flat question (#115)"
```

---

### Task 10: ODT export — emit 誘答分析 block under each 小題 解析

**Files:**
- Modify: `web/src/utils/odt.ts:120-200` (`buildContentXml`)
- Create: `web/src/utils/odt.test.ts` (new file — no existing test exists)

**Interfaces:**
- Consumes: `SubQuestion.誘答分析` / `ExamQuestion.誘答分析` from Task 9's TypeScript types.
- Produces: 誘答分析 rows written to `content.xml` as `<text:p text:style-name="MetaLine">` under each 小題's 解析 line (SS/NS) and under `正確解題分析` (math flat).

- [ ] **Step 1: Write the failing test**

Create `web/src/utils/odt.test.ts`:

```ts
import JSZip from "jszip";
import { describe, expect, it } from "vitest";

import type { ExamQuestion, SubQuestion } from "../hooks/useGenerate";
import { buildExamOdt } from "./odt";

async function readContentXml(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const file = zip.file("content.xml");
  if (!file) throw new Error("content.xml missing");
  return file.async("string");
}

describe("buildExamOdt distractor section", () => {
  it("emits 誘答分析 rows under a subquestion 解析 for SS/NS", async () => {
    const sub: SubQuestion = {
      id: "sq1", 序號: 1, 年級: 8, 科目: ["地理"], 核心素養: [], 學習內容: [], 學習表現: [],
      出題概念: "", 題型: "選擇題", 題目: "Q?", 答案: "B", 答案解析: "explain",
      評分規準: [], 誘答分析: { A: "trap-A", B: "正確答案：B。" },
    };
    const q: ExamQuestion = {
      id: "ss1", 情境: ["公共"], 題型種類: "題組題", 題型: "選擇題",
      核心問題: "c", 文本: "p", subquestions: [sub], 題目: ["p", "Q?"], 正確解題分析: ["B"],
    };
    const blob = await buildExamOdt("t", [q]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("誘答分析");
    expect(xml).toContain("[A]");
    expect(xml).toContain("trap-A");
    expect(xml).toContain("[B]");
    expect(xml).toContain("正確答案：B。");
  });

  it("emits 誘答分析 rows under 正確解題分析 for math flat questions", async () => {
    const q: ExamQuestion = {
      id: "m1", 情境: ["個人"], 題型種類: "單一題", 題型: "選擇題",
      題目: ["Q? (A) 3 (B) 4"], 正確解題分析: ["B is correct."],
      誘答分析: { A: "trap-A", B: "正確答案：4。" },
    };
    const blob = await buildExamOdt("t", [q]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("誘答分析");
    expect(xml).toContain("[A]");
    expect(xml).toContain("正確答案：4。");
  });

  it("omits the block entirely when 誘答分析 is missing or empty", async () => {
    const q: ExamQuestion = {
      id: "m2", 情境: ["個人"], 題型種類: "單一題", 題型: "選擇題",
      題目: ["Q?"], 正確解題分析: ["A"],
    };
    const blob = await buildExamOdt("t", [q]);
    const xml = await readContentXml(blob);
    expect(xml).not.toContain("誘答分析");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspace/exam-generation/web && npm test -- src/utils/odt.test.ts`
Expected: FAIL — `content.xml` currently never mentions `誘答分析`.

- [ ] **Step 3: Modify `web/src/utils/odt.ts`**

In `buildContentXml` (~line 120-200), inside the `if (isSocialStudies) { ... question.subquestions!.forEach((sub) => { ... }); }` loop, immediately after the `if (sub.評分規準?.length) { ... }` block (~line 183-188), add:

```ts
        if (sub.誘答分析 && Object.keys(sub.誘答分析).length > 0) {
          paras.push(`<text:p text:style-name="MetaLine">${xmlEscape("誘答分析：")}</text:p>`);
          Object.entries(sub.誘答分析).forEach(([label, note]) => {
            paras.push(
              `<text:p text:style-name="Standard">${xmlEscape(`[${label}] ${note}`)}</text:p>`,
            );
          });
        }
```

In the math flat branch (`} else { // Math: flat question + solution ...}`, ~line 190-200), immediately after the `question.正確解題分析.forEach(...)` loop and before the closing `}`, add:

```ts
      if (question.誘答分析 && Object.keys(question.誘答分析).length > 0) {
        paras.push(`<text:p text:style-name="Heading2">${xmlEscape("誘答分析")}</text:p>`);
        Object.entries(question.誘答分析).forEach(([label, note]) => {
          paras.push(
            `<text:p text:style-name="Standard">${xmlEscape(`[${label}] ${note}`)}</text:p>`,
          );
        });
      }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspace/exam-generation/web && npm test -- src/utils/odt.test.ts`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Verify full suite + build**

Run: `cd /workspace/exam-generation/web && npm test && npm run lint && npm run build`
Expected: all vitest tests pass, no lint errors, `tsc -b && vite build` succeeds.

- [ ] **Step 6: Commit**

```bash
cd /workspace/exam-generation
git add web/src/utils/odt.ts web/src/utils/odt.test.ts
git commit -m "feat(export): render 誘答分析 rows in ODT under each 小題 解析 (#115)"
```

---

### Task 11: End-to-end sanity check across all three subjects

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything from Tasks 1–10.

- [ ] **Step 1: Run the full Python test suite**

Run: `uv run pytest`
Expected: all tests pass — including the six new files introduced by Tasks 1, 2, 3, 4, 5, 6, 7, 8, plus every pre-existing test.

- [ ] **Step 2: Lint the Python codebase**

Run: `uv run ruff check src/`
Expected: no new lint issues.

- [ ] **Step 3: Run the full frontend test + build**

Run: `cd /workspace/exam-generation/web && npm test && npm run lint && npm run build`
Expected: all vitest tests pass; no ESLint errors; production build succeeds.

- [ ] **Step 4: Dry-run a math generation and confirm the field surfaces in JSON**

Run: `uv run python -m src.cli generate --count 1 --q-type 選擇題 --dry-run`
Expected: no crash; if `--dry-run` skips the LLM call, inspect the built prompts in the log and confirm they contain `誘答分析` guidance. If the harness supports a real (non-dry) run in staging, invoke with a valid `LLM_API_KEY` and assert the produced JSON has a non-empty `誘答分析` dict for 選擇題 outputs.

- [ ] **Step 5: No commit — this is a verification pass only**

Do not create a commit. If any step fails, open a follow-up task rather than force-completing the plan.
