# Per-batch Opus 情境-題材 Creative Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-batch Opus planning call that produces N distinct social-studies creative briefs (`selected_context` + `題材_angle` + `framing_hooks`); each batch question consumes one brief so 題材 substitution is guided by Opus creative direction instead of a bare 情境 enum.

**Architecture:** New `CreativeBrief` Pydantic model plus `plan_context_angles()` in `src/common/planner.py` (subject-agnostic) and a social-studies shim in `src/social_studies/planner.py`. `SampledParams.creative_brief` threads one brief through to `build_text_user_prompt()` in `src/social_studies/context_builder.py`, which prepends a 「創意指引」 system-prompt block and rewrites the `情境` user-prompt line when a brief is present. Batch loops in `src/social_studies/cli.py` and the SS branch of `server/generate/service.py` call Opus once before the loop (only when `count ≥ 1` and `config.creative_planning` is true) and assign briefs by index. Failures fall back to briefless prompts.

**Tech Stack:** Python 3.11+, Pydantic, existing `LLMClient.plan()` (Opus), `src.common.planner._parse_candidates` JSON tolerance, pytest via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-07-15-opus-creative-planning-design.md`

## Global Constraints

- Social studies only for v1 — no math, no natural sciences (`src/planner.py`, `src/natural_sciences/planner.py` are untouched).
- Granularity is **per batch**: one Opus call plans N briefs for a `count`-question batch; never one Opus call per question.
- Model routing uses `Config.model_plan` (Opus) via `LLMClient.plan()`; execution model stays Sonnet.
- Enabled by default for SS via `Config.creative_planning: bool` (env `CREATIVE_PLANNING`, default `True`). Disabling forces the legacy briefless code path.
- Opus call failure, malformed JSON, or fewer briefs than `count` → log a `WARNING` and continue with briefless prompts for the uncovered slots. Planning never blocks generation.
- Each brief's `selected_context` **must** be a member of the caller-supplied `sampled_contexts` set; any brief whose `selected_context` is out-of-set is dropped (fallback to briefless for that slot).
- Script-side randomness remains authoritative: Opus picks the creative angle only, never new curriculum parameters (學習內容/學習表現/科目/年級/題型/etc.).
- When no brief is present, `build_text_user_prompt()` output must be byte-identical to the current template — the diversity-oriented additions are gated on `params.creative_brief is not None`.
- The #111 dedup prompt block remains as belt-and-suspenders — this plan does not remove it.
- All Python commands run from repo root `/workspace/exam-generation` unless a step specifies otherwise.

---

### Task 1: Add `CreativeBrief` schema + `SampledParams.creative_brief`

**Files:**
- Modify: `src/social_studies/schemas.py` (add `CreativeBrief` class near the other BaseModels; add field to `SampledParams`)
- Test: `tests/test_social_studies_creative_brief_schema.py` (Create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `CreativeBrief(BaseModel)` with `selected_context: str`, `題材_angle: str`, `framing_hooks: list[str]`.
  - `SampledParams.creative_brief: CreativeBrief | None = None` — read by Task 4 (`build_text_user_prompt`) and Task 5/6 (batch loops).

- [ ] **Step 1: Write the failing test**

Create `tests/test_social_studies_creative_brief_schema.py`:

```python
"""Schema tests for CreativeBrief + SampledParams.creative_brief."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.social_studies.sampler import sample_params
from src.social_studies.schemas import CreativeBrief, SampledParams


def test_creative_brief_accepts_valid_payload() -> None:
    brief = CreativeBrief(
        selected_context="個人",
        題材_angle="以居家防疫日記串起個人與公共衛生決策",
        framing_hooks=["病患日記", "決策會議紀錄"],
    )
    assert brief.selected_context == "個人"
    assert brief.題材_angle.startswith("以居家防疫日記")
    assert brief.framing_hooks == ["病患日記", "決策會議紀錄"]


def test_creative_brief_requires_selected_context_and_angle() -> None:
    with pytest.raises(ValidationError):
        CreativeBrief(題材_angle="only angle", framing_hooks=[])
    with pytest.raises(ValidationError):
        CreativeBrief(selected_context="個人", framing_hooks=[])


def test_creative_brief_framing_hooks_defaults_to_empty_list() -> None:
    brief = CreativeBrief(selected_context="公共", 題材_angle="市議會辯論觀點")
    assert brief.framing_hooks == []


def test_sampled_params_creative_brief_defaults_to_none() -> None:
    params = sample_params(seed=1)
    assert params.creative_brief is None


def test_sampled_params_can_attach_creative_brief() -> None:
    params = sample_params(seed=1)
    brief = CreativeBrief(selected_context="個人", 題材_angle="角度說明")
    updated: SampledParams = params.model_copy(update={"creative_brief": brief})
    assert updated.creative_brief == brief
    assert params.creative_brief is None  # original untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_studies_creative_brief_schema.py -x`
Expected: FAIL with `ImportError: cannot import name 'CreativeBrief' from 'src.social_studies.schemas'`.

- [ ] **Step 3: Write the implementation**

In `src/social_studies/schemas.py`, add a new class directly after the existing `SubQuestionConfig` class (before `class SubQuestion(...)`):

```python
class CreativeBrief(BaseModel):
    """Opus-generated creative direction for one 題組 in a batch (issue #114).

    - `selected_context` must be one of the batch's sampled 情境 values.
    - `題材_angle` is a 1–2 sentence framing tying 核心問題 × 情境.
    - `framing_hooks` are 1–2 concrete grounding devices (e.g. 病患日記,
      決策會議紀錄) the 文本生成器 can weave into the passage.
    """
    selected_context: str
    題材_angle: str
    framing_hooks: list[str] = Field(default_factory=list)
```

Then, in the same file, extend `SampledParams` with the optional brief field. Add it directly after the existing `subquestion_configs: list[SubQuestionConfig] = Field(default_factory=list)` line at the bottom of the class:

```python
    # #114: per-batch Opus 創意 brief; None when planning is disabled or unavailable
    creative_brief: CreativeBrief | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_studies_creative_brief_schema.py -x`
Expected: PASS — 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/schemas.py tests/test_social_studies_creative_brief_schema.py
git commit -m "feat(ss): add CreativeBrief schema and SampledParams.creative_brief slot (#114)"
```

---

### Task 2: `plan_context_angles()` in `src/common/planner.py`

**Files:**
- Modify: `src/common/planner.py` (add `plan_context_angles` and `_parse_brief_candidates` helper; keep existing `plan_core_questions` untouched)
- Test: `tests/test_common_plan_context_angles.py` (Create)

**Interfaces:**
- Consumes: `LLMClient.plan(system, user, purpose)` from `src/llm_client.py`; `CreativeBrief` from Task 1 (imported inside the function body to avoid a hard dependency cycle at module import for math/NS callers that don't need CreativeBrief).
- Produces: `plan_context_angles(client, count, sampled_contexts, learning_content_pool, core_question=None, *, system_prompt, user_prompt_template, learning_stage="第四學習階段") -> list[CreativeBrief]`. Returns exactly `count` briefs; drops any brief whose `selected_context` is not in `sampled_contexts`; if fewer than `count` survive, pads the tail with briefs from the surviving pool (or an empty list if none). On LLM error, propagates the exception — callers handle fallback.

- [ ] **Step 1: Write the failing test**

Create `tests/test_common_plan_context_angles.py`:

```python
"""Tests for src.common.planner.plan_context_angles (issue #114)."""

from __future__ import annotations

import json

import pytest

from src.common.planner import plan_context_angles
from src.social_studies.schemas import CreativeBrief


_SYSTEM = "test-system-prompt (n={n})"
_USER = (
    "contexts={contexts}\n"
    "count={count}\n"
    "learning_content={learning_content}\n"
    "core_question={core_question}"
)


class _StubClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[tuple[str, str, str]] = []

    def plan(self, system: str, user: str, purpose: str = "plan") -> str:
        self.calls.append((system, user, purpose))
        return self._response


def test_parses_n_briefs_and_returns_exact_count() -> None:
    payload = json.dumps([
        {"selected_context": "個人", "題材_angle": "居家防疫日記", "framing_hooks": ["日記"]},
        {"selected_context": "公共", "題材_angle": "市議會質詢", "framing_hooks": ["質詢紀錄"]},
        {"selected_context": "職業", "題材_angle": "護理排班表", "framing_hooks": ["排班表"]},
    ])
    client = _StubClient(payload)
    briefs = plan_context_angles(
        client,
        count=3,
        sampled_contexts=["個人", "公共", "職業"],
        learning_content_pool=["歷Ka-Ⅳ-1"],
        core_question=None,
        system_prompt=_SYSTEM,
        user_prompt_template=_USER,
    )
    assert len(briefs) == 3
    assert all(isinstance(b, CreativeBrief) for b in briefs)
    assert [b.selected_context for b in briefs] == ["個人", "公共", "職業"]
    # purpose stamped for observability
    assert client.calls[0][2] == "plan_context_angles"


def test_drops_briefs_with_out_of_set_context_and_pads_from_survivors() -> None:
    payload = json.dumps([
        {"selected_context": "個人", "題材_angle": "有效角度一", "framing_hooks": []},
        {"selected_context": "教育", "題材_angle": "非法情境, 應該被丟", "framing_hooks": []},
        {"selected_context": "公共", "題材_angle": "有效角度二", "framing_hooks": []},
    ])
    client = _StubClient(payload)
    briefs = plan_context_angles(
        client,
        count=3,
        sampled_contexts=["個人", "公共"],
        learning_content_pool=[],
        system_prompt=_SYSTEM,
        user_prompt_template=_USER,
    )
    # Only 2 survive; result is padded to 3 by reusing survivors from the front.
    assert len(briefs) == 3
    assert {b.selected_context for b in briefs} <= {"個人", "公共"}
    assert briefs[0].題材_angle == "有效角度一"
    assert briefs[1].題材_angle == "有效角度二"
    assert briefs[2].題材_angle in {"有效角度一", "有效角度二"}


def test_returns_empty_list_when_all_briefs_out_of_set() -> None:
    payload = json.dumps([
        {"selected_context": "教育", "題材_angle": "x", "framing_hooks": []},
    ])
    client = _StubClient(payload)
    briefs = plan_context_angles(
        client,
        count=2,
        sampled_contexts=["個人", "公共"],
        learning_content_pool=[],
        system_prompt=_SYSTEM,
        user_prompt_template=_USER,
    )
    assert briefs == []


def test_raises_when_llm_output_is_not_a_json_array() -> None:
    client = _StubClient("not-json-at-all")
    with pytest.raises(ValueError):
        plan_context_angles(
            client,
            count=1,
            sampled_contexts=["個人"],
            learning_content_pool=[],
            system_prompt=_SYSTEM,
            user_prompt_template=_USER,
        )


def test_user_prompt_includes_core_question_when_present() -> None:
    payload = json.dumps([
        {"selected_context": "個人", "題材_angle": "a", "framing_hooks": []},
    ])
    client = _StubClient(payload)
    plan_context_angles(
        client,
        count=1,
        sampled_contexts=["個人"],
        learning_content_pool=["歷Ka-Ⅳ-1"],
        core_question="如何理解疫情擴散？",
        system_prompt=_SYSTEM,
        user_prompt_template=_USER,
    )
    _, user, _ = client.calls[0]
    assert "如何理解疫情擴散？" in user
    assert "歷Ka-Ⅳ-1" in user
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_common_plan_context_angles.py -x`
Expected: FAIL with `ImportError: cannot import name 'plan_context_angles' from 'src.common.planner'`.

- [ ] **Step 3: Write the implementation**

In `src/common/planner.py`, append the following after the existing `_parse_candidates` function (do not modify `plan_core_questions`):

```python
def plan_context_angles(
    client: LLMClient,
    count: int,
    sampled_contexts: list[str],
    learning_content_pool: list[str],
    core_question: str | None = None,
    *,
    system_prompt: str,
    user_prompt_template: str,
    learning_stage: str = "第四學習階段",
) -> list:
    """Ask the planning model for `count` mutually-distinct 題材 briefs.

    Returns a list of `src.social_studies.schemas.CreativeBrief` objects of
    length `count` (padded from survivors) or an empty list when none of the
    LLM's briefs pass validation. Raises `ValueError` when the LLM response
    cannot be parsed as a JSON array at all — callers must catch and fall
    back to briefless prompts.
    """
    from src.social_studies.schemas import CreativeBrief

    system = system_prompt.format(n=count, learning_stage=learning_stage)
    user = user_prompt_template.format(
        contexts="、".join(sampled_contexts),
        count=count,
        learning_content="、".join(learning_content_pool) or "（未指定）",
        core_question=core_question or "（未指定）",
    )

    raw = client.plan(system, user, purpose="plan_context_angles")
    entries = _parse_brief_candidates(raw)

    allowed = set(sampled_contexts)
    survivors: list[CreativeBrief] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ctx = entry.get("selected_context")
        angle = entry.get("題材_angle") or entry.get("題材角度") or ""
        hooks = entry.get("framing_hooks") or []
        if not ctx or ctx not in allowed or not angle:
            continue
        if not isinstance(hooks, list):
            hooks = []
        try:
            survivors.append(CreativeBrief(
                selected_context=ctx,
                題材_angle=str(angle),
                framing_hooks=[str(h) for h in hooks if h],
            ))
        except Exception:
            continue

    if not survivors:
        return []
    if len(survivors) >= count:
        return survivors[:count]
    # Pad the tail by cycling through survivors so every slot has a brief.
    padded = list(survivors)
    i = 0
    while len(padded) < count:
        padded.append(survivors[i % len(survivors)])
        i += 1
    return padded


def _parse_brief_candidates(raw: str) -> list:
    """Extract a JSON array of dicts from LLM output; retry-tolerant."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    text = code_block.group(1).strip() if code_block else raw.strip()

    arr_match = re.search(r"\[.*\]", text, re.DOTALL)
    if arr_match:
        text = arr_match.group(0)

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"plan_context_angles: could not parse JSON: {exc}") from exc

    if not isinstance(result, list):
        raise ValueError(
            f"plan_context_angles: expected JSON array, got {type(result).__name__}",
        )
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_common_plan_context_angles.py -x`
Expected: PASS — 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/common/planner.py tests/test_common_plan_context_angles.py
git commit -m "feat(planner): add plan_context_angles for per-batch creative briefs (#114)"
```

---

### Task 3: Social-studies shim `plan_context_angles()` with 108課綱 prompts

**Files:**
- Modify: `src/social_studies/planner.py` (add SS-specific prompts + shim; keep existing `plan_core_questions` untouched)
- Test: `tests/test_social_studies_plan_context_angles.py` (Create)

**Interfaces:**
- Consumes: `plan_context_angles` from `src/common/planner.py` (Task 2), `LLMClient` from `src/llm_client.py`.
- Produces: `src.social_studies.planner.plan_context_angles(client, count, sampled_contexts, learning_content_pool, core_question=None) -> list[CreativeBrief]`. Batch loops in Task 5 and Task 6 import this exact name.

- [ ] **Step 1: Write the failing test**

Create `tests/test_social_studies_plan_context_angles.py`:

```python
"""Tests for src.social_studies.planner.plan_context_angles shim (issue #114)."""

from __future__ import annotations

import json

from src.social_studies.planner import (
    plan_context_angles,
    _SS_CREATIVE_PLANNER_SYSTEM_PROMPT,
    _SS_CREATIVE_PLANNER_USER_TEMPLATE,
)
from src.social_studies.schemas import CreativeBrief


class _StubClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[tuple[str, str, str]] = []

    def plan(self, system: str, user: str, purpose: str = "plan") -> str:
        self.calls.append((system, user, purpose))
        return self._response


def test_shim_uses_social_studies_prompt_templates() -> None:
    payload = json.dumps([
        {"selected_context": "公共", "題材_angle": "議會辯論", "framing_hooks": ["逐字稿"]},
        {"selected_context": "個人", "題材_angle": "青少年志工日記", "framing_hooks": ["日記"]},
    ])
    client = _StubClient(payload)
    briefs = plan_context_angles(
        client,
        count=2,
        sampled_contexts=["公共", "個人"],
        learning_content_pool=["公Aa-Ⅳ-1"],
        core_question="如何理解青少年參與公共事務？",
    )
    assert len(briefs) == 2
    assert all(isinstance(b, CreativeBrief) for b in briefs)
    # Templates used
    assert "108課綱社會領域" in client.calls[0][0]
    assert "彼此的題材必須互相不同" in client.calls[0][0]
    assert "公Aa-Ⅳ-1" in client.calls[0][1]
    assert "如何理解青少年參與公共事務？" in client.calls[0][1]


def test_shim_returns_empty_list_when_all_out_of_set() -> None:
    payload = json.dumps([
        {"selected_context": "教育", "題材_angle": "x", "framing_hooks": []},
    ])
    client = _StubClient(payload)
    assert plan_context_angles(
        client,
        count=1,
        sampled_contexts=["個人"],
        learning_content_pool=[],
    ) == []


def test_templates_carry_n_and_learning_stage_placeholders() -> None:
    assert "{n}" in _SS_CREATIVE_PLANNER_SYSTEM_PROMPT
    assert "{learning_stage}" in _SS_CREATIVE_PLANNER_SYSTEM_PROMPT
    assert "{contexts}" in _SS_CREATIVE_PLANNER_USER_TEMPLATE
    assert "{count}" in _SS_CREATIVE_PLANNER_USER_TEMPLATE
    assert "{learning_content}" in _SS_CREATIVE_PLANNER_USER_TEMPLATE
    assert "{core_question}" in _SS_CREATIVE_PLANNER_USER_TEMPLATE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_studies_plan_context_angles.py -x`
Expected: FAIL with `ImportError: cannot import name 'plan_context_angles' from 'src.social_studies.planner'`.

- [ ] **Step 3: Write the implementation**

Replace the contents of `src/social_studies/planner.py` with the following (adds the new shim + prompts alongside the existing `plan_core_questions`; nothing existing is deleted):

```python
"""Subject-specific shim over src.common.planner for 社會領域."""

from __future__ import annotations

from src.common.planner import (
    _parse_candidates,
    plan_context_angles as _base_plan_context_angles,
    plan_core_questions as _base_plan,
)
from src.llm_client import LLMClient
from src.social_studies.schemas import CreativeBrief

_PLANNER_SYSTEM_PROMPT = """\
你是一位資深108課綱社會領域命題教師。
使用者會提供一個議題或主題，請你根據108課綱社會領域（歷史、地理、公民與社會）的素養導向命題精神，
提出 {n} 個不同角度的「核心問題」候選。

核心問題的要求：
- 一句話，以「如何」、「為什麼」、「什麼」等開放性問法引導探究
- 跨科或深度連結社會領域學習內容
- 適合{learning_stage}學生作答
- 彼此角度明顯不同（歷史脈絡、空間地理、公民社會各至少一個面向）

請直接輸出 JSON 陣列，不要其他說明文字：
["核心問題一", "核心問題二", "核心問題三"]
"""

_PLANNER_USER_TEMPLATE = """\
議題/主題：{topic}{subject_hint}{grade_hint}

請提出 {n} 個核心問題候選。
"""


_SS_CREATIVE_PLANNER_SYSTEM_PROMPT = """\
你是一位資深108課綱社會領域命題教師，正在為一批 {n} 道題組規劃彼此不同的「情境-題材」創意方向。
每個題組的核心參數（年級、學習內容、學習表現、科目、題型）已由系統隨機決定；你只負責挑選情境與構思題材角度。
本任務適用學習階段：{learning_stage}。

規則：
- 你會拿到本批次「可用的情境」清單；每個 brief 的 `selected_context` **必須從清單中挑選**，不得自創新情境。
- 每個 brief 由三個欄位組成：
  * `selected_context`：從可用情境挑選的一個值。
  * `題材_angle`：1–2 句創意框架，將情境與可能的核心問題連結；避免教科書式描述。
  * `framing_hooks`：1–2 個具體取材錨點，例如「病患日記」、「決策會議紀錄」、「田野筆記」。
- {n} 個 brief 之間**彼此的題材必須互相不同**：情境可以重覆，但題材角度與 framing_hooks 不得雷同，避免只換名稱的變體。
- 題材應能被 108課綱 指定學習內容支撐；不要引用學生程度以外的專業術語。
- 你不決定學習內容、學習表現、核心素養、題目等其他參數，僅提供情境與題材創意。

輸出格式為 JSON 陣列，共 {n} 筆，每筆為物件：

```json
[
  {{
    "selected_context": "個人",
    "題材_angle": "以居家防疫日記串起個人與公共衛生決策",
    "framing_hooks": ["病患日記", "家庭記事本"]
  }}
]
```

只輸出 JSON 陣列，不要其他說明文字。
"""

_SS_CREATIVE_PLANNER_USER_TEMPLATE = """\
本批次需要 {count} 個題組，請為它們規劃 {count} 個互相不同的情境-題材創意 brief：

- 可用情境（selected_context 必須從中挑選）：{contexts}
- 本批次共用的指定學習內容：{learning_content}
- 使用者指定核心問題（僅供參考，可為「（未指定）」）：{core_question}

請輸出恰好 {count} 個 brief 的 JSON 陣列。
"""


def plan_core_questions(
    client: LLMClient,
    topic: str,
    *,
    subject_filter: list[str] | None = None,
    grade: int | None = None,
    n: int = 3,
    learning_stage: str = "第四學習階段",
) -> list[str]:
    """Call planning model, return n candidate 核心問題 for the given topic."""
    return _base_plan(
        client,
        topic,
        system_prompt=_PLANNER_SYSTEM_PROMPT,
        user_prompt_template=_PLANNER_USER_TEMPLATE,
        n=n,
        learning_stage=learning_stage,
        subject_filter=subject_filter,
        grade=grade,
    )


def plan_context_angles(
    client: LLMClient,
    count: int,
    sampled_contexts: list[str],
    learning_content_pool: list[str],
    core_question: str | None = None,
    *,
    learning_stage: str = "第四學習階段",
) -> list[CreativeBrief]:
    """Call the planning model and return `count` distinct 社會領域 briefs.

    Returns `[]` when Opus is unavailable or every brief was out-of-set;
    raises `ValueError` when the LLM response could not be parsed as JSON.
    Callers (batch loops) must handle both to fall back to briefless prompts.
    """
    return _base_plan_context_angles(
        client,
        count=count,
        sampled_contexts=sampled_contexts,
        learning_content_pool=learning_content_pool,
        core_question=core_question,
        system_prompt=_SS_CREATIVE_PLANNER_SYSTEM_PROMPT,
        user_prompt_template=_SS_CREATIVE_PLANNER_USER_TEMPLATE,
        learning_stage=learning_stage,
    )


__all__ = ["plan_core_questions", "plan_context_angles", "_parse_candidates"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_studies_plan_context_angles.py -x`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/planner.py tests/test_social_studies_plan_context_angles.py
git commit -m "feat(ss): shim plan_context_angles with 社會領域 creative planner prompt (#114)"
```

---

### Task 4: Render brief into `build_text_user_prompt` + 創意指引 system-prompt block

**Files:**
- Modify: `src/social_studies/context_builder.py` (`build_text_system_prompt` + `build_text_user_prompt` + `build_user_prompt`)
- Test: `tests/test_social_studies_creative_brief_prompt.py` (Create)

**Interfaces:**
- Consumes: `SampledParams.creative_brief` from Task 1.
- Produces:
  - When `params.creative_brief is not None`, `build_text_user_prompt()` rewrites the `- **情境**：...` line to `- **情境**：{selected_context}（創意取材角度：{題材_angle}；參考取材點：{framing_hooks}）` and appends a `## 創意指引` section discouraging copying few-shot 題材.
  - `build_text_system_prompt()` appends a top-level `### 創意指引` block when a brief is present.
  - When `params.creative_brief is None`, both prompts are byte-identical to the current template.

- [ ] **Step 1: Write the failing test**

Create `tests/test_social_studies_creative_brief_prompt.py`:

```python
"""Prompt rendering tests for CreativeBrief threading into 文本生成器 (issue #114)."""

from __future__ import annotations

import random

from src.social_studies.context_builder import (
    build_text_system_prompt,
    build_text_user_prompt,
)
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import CreativeBrief


def _brief() -> CreativeBrief:
    return CreativeBrief(
        selected_context="個人",
        題材_angle="以居家防疫日記串起個人與公共衛生決策",
        framing_hooks=["病患日記", "家庭記事本"],
    )


def test_without_brief_prompt_matches_current_template(tmp_path) -> None:
    params = sample_params(seed=7)
    text_before, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "創意取材角度" not in text_before
    assert "## 創意指引" not in text_before


def test_with_brief_rewrites_context_line_in_user_prompt(tmp_path) -> None:
    params = sample_params(seed=7).model_copy(update={"creative_brief": _brief()})
    text, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert (
        "- **情境**：個人（創意取材角度：以居家防疫日記串起個人與公共衛生決策；"
        "參考取材點：病患日記、家庭記事本）"
    ) in text
    assert "## 創意指引" in text
    assert "避免直接複製參考範例的題材" in text
    assert "題材角度：以居家防疫日記串起個人與公共衛生決策" in text


def test_with_brief_but_empty_hooks_omits_參考取材點(tmp_path) -> None:
    brief = CreativeBrief(selected_context="公共", 題材_angle="市議會辯論觀點", framing_hooks=[])
    params = sample_params(seed=7).model_copy(update={"creative_brief": brief})
    text, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "- **情境**：公共（創意取材角度：市議會辯論觀點）" in text
    assert "參考取材點" not in text


def test_system_prompt_appends_創意指引_block_only_with_brief() -> None:
    sys_none = build_text_system_prompt()
    assert "### 創意指引" not in sys_none

    sys_with = build_text_system_prompt(creative_brief=_brief())
    assert "### 創意指引" in sys_with
    assert "情境-題材角度" in sys_with
    assert "不得直接沿用範例題材" in sys_with


def test_user_topic_override_still_wins_over_brief(tmp_path) -> None:
    """A user-typed topic replaces the 情境 line entirely; brief text is not injected."""
    params = sample_params(seed=7).model_copy(update={"creative_brief": _brief()})
    text, _ = build_text_user_prompt(
        params,
        tmp_path,
        rng=random.Random(1),
        user_topic="使用者自訂主題",
    )
    assert "- **情境**：使用者自訂主題（PISA閱讀情境）" in text
    assert "創意取材角度" not in text
    # 創意指引 section is still appended so the LLM diversifies within the topic.
    assert "## 創意指引" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_studies_creative_brief_prompt.py -x`
Expected: FAIL — `build_text_system_prompt()` does not accept a `creative_brief` kwarg; user prompt does not contain "創意取材角度".

- [ ] **Step 3: Write the implementation**

Edit `src/social_studies/context_builder.py`:

(a) Add a module-level helper directly above `SYSTEM_PROMPT_TEMPLATE` (near line 71):

```python
_CREATIVE_BRIEF_SYSTEM_BLOCK = """\

### 創意指引

- 本批次題組已由前置規劃器指定「情境-題材角度」與「參考取材點」，請以此為文本取材主軸。
- 不得直接沿用範例題材（few-shot）中的題材、機構名、資料形式；請以指定角度重新設計素材。
- 題材角度必須具體落地在文本中（不是抽象口號）；至少一項 framing hook 應成為文本或素材的組成元素。
"""


def _render_brief_context_suffix(brief) -> str:
    """Return the parenthetical creative suffix appended to the 情境 line."""
    if brief is None:
        return ""
    parts = [f"創意取材角度：{brief.題材_angle}"]
    if brief.framing_hooks:
        parts.append("參考取材點：" + "、".join(brief.framing_hooks))
    return "（" + "；".join(parts) + "）"


def _render_brief_guidance_section(brief) -> str:
    """Return a `## 創意指引` user-prompt section for the given brief."""
    if brief is None:
        return ""
    hook_line = (
        f"\n- 建議取材點：{'、'.join(brief.framing_hooks)}"
        if brief.framing_hooks else ""
    )
    return (
        "\n## 創意指引\n\n"
        f"- 情境：{brief.selected_context}\n"
        f"- 題材角度：{brief.題材_angle}"
        f"{hook_line}\n"
        "- 請以上述題材角度為文本取材主軸，避免直接複製參考範例的題材或格式。\n"
    )
```

(b) Update `build_text_system_prompt` (currently around line 844) to accept a `creative_brief` kwarg and append the block:

```python
def build_text_system_prompt(
    grades: list[int] | None = None,
    learning_stage: str | None = None,
    content_text: str | None = None,
    performance_text: str | None = None,
    creative_brief: "CreativeBrief | None" = None,
) -> str:
    prompt = build_system_prompt(
        grades=grades,
        learning_stage=learning_stage,
        content_text=content_text,
        performance_text=performance_text,
    )
    prompt_intro = prompt.split("## 輸出格式", 1)[0].rstrip()
    body = prompt_intro + """

## 輸出格式

你必須輸出一個合法的 JSON 物件，格式如下：

```json
{
  "核心問題": "本題組的核心問題",
  "文本": "完整閱讀素材",
  "取材來源": ["來源一"],
  "subquestions": [
    {
      "序號": 1,
      "題型": "選擇題",
      "出題概念": "一句話說明此小題要評量的能力"
    }
  ]
}
```

`subquestions` 陣列為各小題的出題規劃，每筆只需序號、題型與一句出題概念說明；詳細題目與答案將由後續子題產生器負責。請只輸出 JSON，不要輸出其他文字。
"""
    if creative_brief is not None:
        body += _CREATIVE_BRIEF_SYSTEM_BLOCK
    return body
```

Also add the type import at the top of the module (after the existing `SubQuestionConfig` import on line 28):

```python
from src.social_studies.schemas import CreativeBrief, SampledParams, SubQuestionConfig
```

(c) Update `build_user_prompt` (currently around line 277) so the 情境 line reflects any creative brief. Locate the block that assembles `context` in the `USER_PROMPT_TEMPLATE.format(...)` call (currently `context=topic_override or "、".join(c.value for c in params.情境),`) and replace it. First, compute the context string before the `text = USER_PROMPT_TEMPLATE.format(...)` call:

```python
    brief = getattr(params, "creative_brief", None)
    if topic_override:
        context_line = topic_override
    elif brief is not None:
        suffix = _render_brief_context_suffix(brief)
        context_line = f"{brief.selected_context}{suffix}"
    else:
        context_line = "、".join(c.value for c in params.情境)
```

Then change the `format(...)` argument to `context=context_line,`.

(d) Update `build_text_user_prompt` (currently around line 882) so the creative-brief guidance section is appended after `build_user_prompt` returns. Locate the existing body:

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
    )
```

Immediately after that `build_user_prompt(...)` call, before the existing `text = text.replace(...)` line, insert:

```python
    brief = getattr(params, "creative_brief", None)
    if brief is not None:
        text += _render_brief_guidance_section(brief)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_studies_creative_brief_prompt.py -x`
Expected: PASS — 5 tests green.

- [ ] **Step 5: Sanity-check the byte-identical fallback**

Run: `uv run pytest tests/test_social_studies_context_builder.py -x`
Expected: PASS — pre-existing SS prompt tests still pass unchanged (brief is `None` on all pre-existing fixtures).

- [ ] **Step 6: Commit**

```bash
git add src/social_studies/context_builder.py tests/test_social_studies_creative_brief_prompt.py
git commit -m "feat(ss): render CreativeBrief into 文本生成器 system + user prompts (#114)"
```

---

### Task 5: `Config.creative_planning` env flag

**Files:**
- Modify: `src/config.py` (`Config` dataclass + `from_env`)
- Test: `tests/test_config_creative_planning.py` (Create)

**Interfaces:**
- Consumes: env var `CREATIVE_PLANNING`.
- Produces: `Config.creative_planning: bool` (default `True`), consumed by the batch loops in Tasks 6 and 7.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_creative_planning.py`:

```python
"""Tests for Config.creative_planning env-var wiring (issue #114)."""

from __future__ import annotations

import pytest

from src.config import Config


@pytest.mark.parametrize("value,expected", [
    ("1", True),
    ("true", True),
    ("True", True),
    ("0", False),
    ("false", False),
    ("False", False),
    ("", False),
])
def test_creative_planning_reads_env_var(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("CREATIVE_PLANNING", value)
    cfg = Config.from_env()
    assert cfg.creative_planning is expected


def test_creative_planning_defaults_to_true_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("CREATIVE_PLANNING", raising=False)
    cfg = Config.from_env()
    assert cfg.creative_planning is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_creative_planning.py -x`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'creative_planning'`.

- [ ] **Step 3: Write the implementation**

Edit `src/config.py`.

(a) Add the field to the `Config` dataclass, directly after the existing `log_truncate` line (line 27):

```python
    creative_planning: bool = True  # per-batch Opus 情境-題材 planning (SS only); env CREATIVE_PLANNING
```

(b) Extend `from_env` (currently ends on line 52) with the reader, directly after the `log_truncate=...` line inside the `return cls(...)` call:

```python
            log_truncate=int(os.environ["LLM_LOG_TRUNCATE"]) if os.environ.get("LLM_LOG_TRUNCATE") else None,
            creative_planning=os.environ.get("CREATIVE_PLANNING", "1") not in ("0", "false", "False", ""),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_creative_planning.py -x`
Expected: PASS — 8 tests green (7 parametrized + 1 default).

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config_creative_planning.py
git commit -m "feat(config): add creative_planning flag (env CREATIVE_PLANNING, default on) (#114)"
```

---

### Task 6: Batch planning + brief assignment in `src/social_studies/cli.py`

**Files:**
- Modify: `src/social_studies/cli.py` (add `_plan_batch_briefs` helper + wire into `main()` batch loop)
- Test: `tests/test_social_studies_cli_creative_planning.py` (Create)

**Interfaces:**
- Consumes: `Config.creative_planning` (Task 5); `plan_context_angles` from `src/social_studies/planner.py` (Task 3); `SampledParams.creative_brief` (Task 1).
- Produces: `_plan_batch_briefs(client, config, params_list) -> list[CreativeBrief | None]` — returns a list of length `len(params_list)` where index `i` is the brief for question `i`, or `None` when planning was disabled/failed. `main()` in CLI now attaches `briefs[i]` to `params_list[i].creative_brief` before calling `generate_with_corrections`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_social_studies_cli_creative_planning.py`:

```python
"""Tests for CLI-side batch planning integration (issue #114)."""

from __future__ import annotations

import pytest

from src.config import Config
from src.social_studies.cli import _plan_batch_briefs
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import CreativeBrief


class _StubClient:
    """Minimal client stub exposing only the methods the planner touches."""

    def __init__(self, briefs: list[CreativeBrief] | Exception) -> None:
        self._briefs = briefs
        self.plan_calls = 0

    def plan(self, system, user, purpose="plan"):
        self.plan_calls += 1
        if isinstance(self._briefs, Exception):
            raise self._briefs
        import json
        return json.dumps([b.model_dump() for b in self._briefs])


def _params(seed: int):
    return sample_params(seed=seed)


def test_returns_none_list_when_creative_planning_disabled() -> None:
    cfg = Config(creative_planning=False)
    client = _StubClient([])
    p = _params(1)
    briefs = _plan_batch_briefs(client, cfg, [p, p])
    assert briefs == [None, None]
    assert client.plan_calls == 0


def test_returns_none_list_when_client_is_none() -> None:
    cfg = Config(creative_planning=True)
    briefs = _plan_batch_briefs(None, cfg, [_params(1)])
    assert briefs == [None]


def test_returns_brief_per_slot_when_planner_succeeds() -> None:
    cfg = Config(creative_planning=True)
    p = _params(1)
    contexts = [c.value for c in p.情境]
    stub_briefs = [
        CreativeBrief(selected_context=contexts[0], 題材_angle=f"角度{i}", framing_hooks=[])
        for i in range(2)
    ]
    client = _StubClient(stub_briefs)
    briefs = _plan_batch_briefs(client, cfg, [p, p])
    assert len(briefs) == 2
    assert all(isinstance(b, CreativeBrief) for b in briefs)
    assert client.plan_calls == 1  # per-batch, not per-question


def test_returns_none_list_on_llm_failure(caplog) -> None:
    cfg = Config(creative_planning=True)
    client = _StubClient(RuntimeError("Opus is down"))
    with caplog.at_level("WARNING"):
        briefs = _plan_batch_briefs(client, cfg, [_params(1), _params(2)])
    assert briefs == [None, None]
    assert any("creative planning" in r.message.lower() for r in caplog.records)


def test_pads_missing_slots_with_none_when_planner_returns_empty() -> None:
    """When plan_context_angles returns []], all slots are None (briefless)."""
    cfg = Config(creative_planning=True)
    # Response with only out-of-set contexts → survivors = 0 → planner returns []
    class _EmptyClient:
        plan_calls = 0

        def plan(self, system, user, purpose="plan"):
            _EmptyClient.plan_calls += 1
            return '[{"selected_context": "教育", "題材_angle": "x", "framing_hooks": []}]'

    p = _params(1)
    # sampled 情境 excludes 教育 for seed=1? sampler always samples from all_contexts,
    # so pick a params whose 情境 excludes 教育 by construction:
    from src.social_studies.schemas import QuestionContext
    p_only_person = p.model_copy(update={"情境": [QuestionContext("個人")]})
    briefs = _plan_batch_briefs(_EmptyClient(), cfg, [p_only_person, p_only_person])
    assert briefs == [None, None]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_studies_cli_creative_planning.py -x`
Expected: FAIL with `ImportError: cannot import name '_plan_batch_briefs' from 'src.social_studies.cli'`.

- [ ] **Step 3: Write the implementation**

Edit `src/social_studies/cli.py`.

(a) Add a logger and an import at the top of the module, next to the existing imports (after `from src.social_studies.verifier import verify_question`, around line 45):

```python
import logging

from src.social_studies.planner import plan_context_angles
from src.social_studies.schemas import CreativeBrief  # add to the existing schema import list

logger = logging.getLogger(__name__)
```

(Merge the `CreativeBrief` import into the existing `from src.social_studies.schemas import (...)` block rather than duplicating the block.)

(b) Add the `_plan_batch_briefs` helper directly above `def generate_one(...)` (currently line 534):

```python
def _plan_batch_briefs(
    client: LLMClient | None,
    config: Config,
    params_list: list[SampledParams],
) -> list[CreativeBrief | None]:
    """One Opus planning call for the whole batch; length matches params_list.

    Returns `[None] * n` when planning is disabled, the client is unavailable,
    the batch is empty, no shared 情境 remain, the LLM raises, or every
    returned brief is out-of-set. Never raises — planning must never block
    generation.
    """
    n = len(params_list)
    if n == 0:
        return []
    if not config.creative_planning or client is None:
        return [None] * n

    # Union of sampled 情境 across the batch — Opus is free to pick any of them.
    contexts: list[str] = []
    for params in params_list:
        for c in params.情境:
            if c.value not in contexts:
                contexts.append(c.value)
    if not contexts:
        return [None] * n

    # Use the first question's 學習內容_pool as the shared grounding; SS batches
    # typically share stage/subject so this is a reasonable representative pool.
    learning_content_pool = list(params_list[0].學習內容_pool)

    try:
        briefs = plan_context_angles(
            client,
            count=n,
            sampled_contexts=contexts,
            learning_content_pool=learning_content_pool,
            core_question=None,
        )
    except Exception as exc:
        logger.warning("Creative planning failed; falling back to briefless prompts: %s", exc)
        return [None] * n

    if not briefs:
        logger.warning("Creative planning returned no valid briefs; falling back to briefless prompts")
        return [None] * n

    # briefs already has length n (padded by plan_context_angles), but guard
    # against future changes by explicitly filling the tail with None.
    result: list[CreativeBrief | None] = list(briefs[:n])
    while len(result) < n:
        result.append(None)
    return result
```

(c) In `main()`, replace the batch loop so a single `_plan_batch_briefs` call runs before the per-question loop and each question's params gets `creative_brief` attached. Locate the current loop (starting near line 862) and change the setup block so `sample_params` results are collected first, then briefs are planned, then generation runs:

```python
    try:
        params_list: list[SampledParams] = []
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
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
            params_list.append(params)

        briefs = _plan_batch_briefs(client, config, params_list)
        for i, brief in enumerate(briefs):
            if brief is not None:
                params_list[i] = params_list[i].model_copy(update={"creative_brief": brief})

        for i, params in enumerate(params_list):
            question_id = f"ss_{timestamp}_{i+1:03d}"
            print(f"\n[{i+1}/{args.count}] Sampled: grade={params.grade}, "
                  f"科目={params.科目.value}, "
                  f"情境={'、'.join(c.value for c in params.情境)}, "
                  f"題型={'、'.join(t.value for t in params.題型)}, 閱讀歷程={'、'.join(p.value for p in params.閱讀歷程)}, "
                  f"文本形式={params.文本形式.value}, "
                  f"題目內容類型={params.題目內容類型}, "
                  f"核心素養={'、'.join(c.value for c in params.核心素養)}, "
                  f"creative_brief={'yes' if params.creative_brief else 'no'}", file=sys.stderr)

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
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)
            results.append(question)

            if not args.batch:
                out_path = config.output_dir / f"{question_id}.json"
                out_path.write_text(
                    question.model_dump_json(indent=2, exclude_none=True),
                    encoding="utf-8",
                )
                print(f"  Saved: {out_path}", file=sys.stderr)
```

(The `finally:` block, batch write, and Playwright teardown are unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_studies_cli_creative_planning.py tests/test_social_studies_creative_brief_prompt.py -x`
Expected: PASS — 5 new CLI tests + 5 prompt tests green.

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/cli.py tests/test_social_studies_cli_creative_planning.py
git commit -m "feat(ss/cli): plan creative briefs once per batch and thread into params (#114)"
```

---

### Task 7: Batch planning inside the SS branch of `server/generate/service.py`

**Files:**
- Modify: `server/generate/service.py` (`generate_question_stream` — SS branch of `worker_one`)
- Test: `tests/server/test_ss_creative_planning_service.py` (Create)

**Interfaces:**
- Consumes: `Config.creative_planning`, `_plan_batch_briefs` (Task 6), `SampledParams.creative_brief` (Task 1). The SS worker path is the only branch modified; math and natural sciences branches are untouched.
- Produces: web batch runs receive one shared Opus creative plan (one LLM call, not `count`), with each SS worker consuming its assigned brief. Failures degrade to briefless prompts.

- [ ] **Step 1: Write the failing test**

Create `tests/server/test_ss_creative_planning_service.py`:

```python
"""Tests for server-side per-batch creative planning (issue #114)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from src.social_studies.schemas import CreativeBrief, ExamQuestion


class _AppState:
    """Minimal app_state stub — no renderer pool, no math data."""
    renderer_pool = None


def _collect(coro):
    async def _run():
        events = []
        async for evt in coro:
            events.append(evt)
        return events
    return asyncio.run(_run())


def test_ss_batch_calls_plan_context_angles_once(monkeypatch, tmp_path) -> None:
    plan_calls = {"count": 0}

    def fake_plan(client, count, sampled_contexts, learning_content_pool,
                  core_question=None, **kwargs):
        plan_calls["count"] += 1
        return [
            CreativeBrief(selected_context=sampled_contexts[0], 題材_angle=f"角度{i}")
            for i in range(count)
        ]

    monkeypatch.setattr(
        "src.social_studies.cli.plan_context_angles",
        fake_plan,
    )

    captured_params = []

    def fake_generate(**kwargs):
        captured_params.append(kwargs["params"])
        eq = ExamQuestion(
            id=kwargs["question_id"],
            情境=[c.value for c in kwargs["params"].情境],
            題型種類=kwargs["params"].題型種類.value,
            題型="選擇題",
            閱讀歷程=[p.value for p in kwargs["params"].閱讀歷程],
            文本形式=kwargs["params"].文本形式.value,
        )
        return eq

    monkeypatch.setattr(
        "server.generate.service.ss_generate_with_corrections",
        fake_generate,
    )

    cfg = ServerConfig(api_key="x", output_dir=tmp_path, creative_planning=True)
    params = GenerateParams(subject="social_studies", count=3, skip_verify=True)

    events = _collect(generate_question_stream(params, cfg, _AppState()))

    assert plan_calls["count"] == 1
    assert len(captured_params) == 3
    assert all(p.creative_brief is not None for p in captured_params)
    assert {"result", "done"}.issubset({e["event"] for e in events})


def test_ss_batch_skips_planning_when_flag_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "src.social_studies.cli.plan_context_angles",
        MagicMock(side_effect=AssertionError("should not be called")),
    )

    def fake_generate(**kwargs):
        return ExamQuestion(
            id=kwargs["question_id"],
            情境=[c.value for c in kwargs["params"].情境],
            題型種類=kwargs["params"].題型種類.value,
            題型="選擇題",
            閱讀歷程=[p.value for p in kwargs["params"].閱讀歷程],
            文本形式=kwargs["params"].文本形式.value,
        )

    monkeypatch.setattr(
        "server.generate.service.ss_generate_with_corrections",
        fake_generate,
    )

    cfg = ServerConfig(api_key="x", output_dir=tmp_path, creative_planning=False)
    params = GenerateParams(subject="social_studies", count=2, skip_verify=True)

    events = _collect(generate_question_stream(params, cfg, _AppState()))
    assert {"result", "done"}.issubset({e["event"] for e in events})


def test_math_branch_never_plans(monkeypatch, tmp_path) -> None:
    """Math batches must not touch plan_context_angles even when the flag is on."""
    monkeypatch.setattr(
        "src.social_studies.cli.plan_context_angles",
        MagicMock(side_effect=AssertionError("must not be called for math")),
    )
    # We only need to prove the SS planner is not invoked; short-circuit math
    # generation by making sample_params raise so the branch exits early.
    monkeypatch.setattr(
        "server.generate.service.math_sample_params",
        MagicMock(side_effect=RuntimeError("stop math")),
    )

    class _MathState:
        renderer_pool = None
        curriculum = {}
        performance = {}
        intro_text = ""
        grade_content = {}

    cfg = ServerConfig(api_key="x", output_dir=tmp_path, creative_planning=True)
    params = GenerateParams(subject="math", count=2, skip_verify=True)

    events = _collect(generate_question_stream(params, cfg, _MathState()))
    # Errors are OK; the AssertionError side_effect above is what we're guarding against.
    assert {"error", "done"}.intersection({e["event"] for e in events}) or True
```

- [ ] **Step 2: Verify prerequisite `ServerConfig.creative_planning` exists**

Run: `uv run python -c "from server.config import ServerConfig; import inspect; assert 'creative_planning' in inspect.signature(ServerConfig).parameters"`
Expected: exits 0 after Task 5 (Config already has the field). If it fails with `AssertionError`, add `creative_planning: bool = True` to `ServerConfig` in `server/config.py` alongside the other cascade fields and rerun.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/server/test_ss_creative_planning_service.py -x`
Expected: FAIL — Task 7 has not yet inserted the planning call into the SS worker branch, so `plan_calls["count"] == 1` fails (still 0).

- [ ] **Step 4: Write the implementation**

Edit `server/generate/service.py`:

(a) Add an import block near the other SS imports (after line 74):

```python
from src.social_studies.cli import _plan_batch_briefs as ss_plan_batch_briefs
from src.social_studies.schemas import CreativeBrief as SSCreativeBrief
```

(b) Inside `generate_question_stream`, insert a batch-planning step **before** `question_clients = [LLMClient(config) for _ in range(count)]` (currently around line 383). Add:

```python
    # #114: for SS batches, plan creative briefs once before spawning workers.
    ss_batch_briefs: list[SSCreativeBrief | None] = []
    if is_social_studies and count >= 1 and config.creative_planning:
        # Sample all SS params up front so plan_context_angles sees the actual
        # 情境 and 學習內容 pool that the workers will use. Workers re-sample
        # with the same seed and receive the corresponding brief.
        pre_params_list = []
        for i in range(count):
            seed = (base_seed + i) if base_seed is not None else None
            pre_params_list.append(
                ss_sample_params(
                    grade=params.grade,
                    context=context_override,
                    set_type=set_type_override,
                    q_type=q_type_override,
                    subject=subject_override,
                    content_type=params.content_type,
                    learning_performance=params.learning_performance,
                    seed=seed,
                    sub_question_count=params.sub_question_count,
                    question_word_limit=params.question_word_limit,
                    option_word_limit=params.option_word_limit,
                    subquestion_configs=_decode_subquestion_configs(
                        params.subquestion_configs,
                    ),
                ),
            )
        # Use a dedicated planning client so worker observers stay clean.
        planning_client = LLMClient(config)
        ss_batch_briefs = ss_plan_batch_briefs(planning_client, config, pre_params_list)
    elif is_social_studies:
        ss_batch_briefs = [None] * count
```

(c) In the SS branch of `worker_one` (currently around line 254), attach the assigned brief right after `rng_params = ss_sample_params(...)`:

```python
                if i < len(ss_batch_briefs) and ss_batch_briefs[i] is not None:
                    rng_params = rng_params.model_copy(
                        update={"creative_brief": ss_batch_briefs[i]},
                    )
```

(No changes to the math or natural-sciences branches.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/server/test_ss_creative_planning_service.py -x`
Expected: PASS — 3 tests green.

- [ ] **Step 6: Run the full existing server-side test suite**

Run: `uv run pytest tests/server/ -x`
Expected: PASS — no regressions in `test_plan_core_questions_routes.py` or other server tests.

- [ ] **Step 7: Commit**

```bash
git add server/generate/service.py tests/server/test_ss_creative_planning_service.py
git commit -m "feat(server): per-batch SS creative planning in generate_question_stream (#114)"
```

---

### Task 8: Full-suite regression + `ServerConfig` fallback wiring

**Files:**
- Modify: `server/config.py` (add `creative_planning` mirror if not already present after Task 7 Step 2)
- Test: `tests/test_config_creative_planning.py` (extend with a `ServerConfig` case)

**Interfaces:**
- Consumes: `Config.creative_planning` from Task 5 (already env-driven).
- Produces: `ServerConfig.creative_planning: bool` with the same default so `service.py` can read it uniformly. This is a no-op if Task 7 Step 2 already showed the field exists.

- [ ] **Step 1: Read `server/config.py` and confirm whether `creative_planning` needs to be added**

Run: `grep -n "creative_planning" /workspace/exam-generation/server/config.py || echo MISSING`
Expected: prints line number (skip Step 2–4) OR prints `MISSING` (proceed).

- [ ] **Step 2: If MISSING, write the failing test**

Append to `tests/test_config_creative_planning.py`:

```python
def test_server_config_creative_planning_defaults_to_true() -> None:
    from server.config import ServerConfig
    cfg = ServerConfig(api_key="x")
    assert cfg.creative_planning is True


def test_server_config_creative_planning_reads_env(monkeypatch) -> None:
    from server.config import ServerConfig
    monkeypatch.setenv("CREATIVE_PLANNING", "0")
    cfg = ServerConfig.from_env()
    assert cfg.creative_planning is False
```

Run: `uv run pytest tests/test_config_creative_planning.py::test_server_config_creative_planning_defaults_to_true -x`
Expected: FAIL with `AttributeError: 'ServerConfig' object has no attribute 'creative_planning'`.

- [ ] **Step 3: If MISSING, add the field**

Read `server/config.py` and add `creative_planning: bool = True` alongside the other bool fields; extend `ServerConfig.from_env` to read `os.environ.get("CREATIVE_PLANNING", "1") not in ("0", "false", "False", "")`, matching the `Config.from_env` implementation from Task 5.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_creative_planning.py -x`
Expected: PASS — all tests green.

- [ ] **Step 5: Full suite**

Run: `uv run pytest -x`
Expected: PASS — no regressions across social studies, math, natural sciences, or server tests. If any pre-existing test breaks, diagnose (do not skip) — the plan's guarantee is that `creative_brief=None` yields byte-identical prompts.

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/ server/ tests/`
Expected: PASS — no new lint errors introduced.

- [ ] **Step 7: Commit**

```bash
git add server/config.py tests/test_config_creative_planning.py
git commit -m "chore: mirror creative_planning flag on ServerConfig (#114)"
```

---

### Task 9: Diversity smoke test (env-gated manual/real-LLM run)

**Files:**
- Test: `tests/test_social_studies_creative_planning_smoke.py` (Create)

**Interfaces:**
- Consumes: real Opus + Sonnet endpoints via env vars (`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_PLAN`, `LLM_MODEL_EXECUTE`). Gated on env var `RUN_CREATIVE_PLANNING_SMOKE=1` so CI does not spend API tokens.
- Produces: a manual assertion that 5 same-parameter generations yield at least 3 distinct 題材 keywords (per the spec's manual QA criterion).

- [ ] **Step 1: Write the smoke test**

Create `tests/test_social_studies_creative_planning_smoke.py`:

```python
"""Env-gated diversity smoke test for creative planning (issue #114).

Not run in CI. Trigger locally with:

    RUN_CREATIVE_PLANNING_SMOKE=1 uv run pytest \
        tests/test_social_studies_creative_planning_smoke.py -s

The test issues one real Opus planning call for a 5-question batch and
asserts that at least 3 distinct 題材 keywords appear across the briefs.
"""

from __future__ import annotations

import os
import re

import pytest

from src.config import Config
from src.llm_client import LLMClient
from src.social_studies.planner import plan_context_angles
from src.social_studies.sampler import sample_params

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_CREATIVE_PLANNING_SMOKE") != "1",
    reason="Set RUN_CREATIVE_PLANNING_SMOKE=1 to run this smoke test.",
)


def test_five_briefs_have_at_least_three_distinct_題材_keywords() -> None:
    cfg = Config.from_env()
    cfg.validate()
    client = LLMClient(cfg)

    params = sample_params(seed=42)
    contexts = [c.value for c in params.情境]

    briefs = plan_context_angles(
        client,
        count=5,
        sampled_contexts=contexts,
        learning_content_pool=params.學習內容_pool,
        core_question=None,
    )

    assert len(briefs) == 5, f"expected 5 briefs, got {len(briefs)}"

    # A very rough "distinct keyword" heuristic: take the first 2 Chinese
    # nouns from each 題材_angle by grabbing runs of 2–5 CJK characters that
    # appear before typical particles/verbs.
    keywords = set()
    for brief in briefs:
        tokens = re.findall(r"[一-鿿]{2,5}", brief.題材_angle)
        keywords.update(tokens[:3])

    print("題材 keywords across 5 briefs:", keywords)
    assert len(keywords) >= 3, (
        f"expected ≥3 distinct 題材 keywords across 5 briefs, got {len(keywords)}: {keywords}"
    )
```

- [ ] **Step 2: Verify the skip guard works with the env var unset**

Run: `uv run pytest tests/test_social_studies_creative_planning_smoke.py -v`
Expected: SKIPPED — pytest reports 1 skipped test with reason "Set RUN_CREATIVE_PLANNING_SMOKE=1 to run this smoke test."

- [ ] **Step 3: Commit**

```bash
git add tests/test_social_studies_creative_planning_smoke.py
git commit -m "test(ss): env-gated diversity smoke test for creative planning (#114)"
```

- [ ] **Step 4 (manual, operator only): run against real Opus**

Run (only when the operator has a live `LLM_API_KEY` and wants to spend tokens):

```bash
RUN_CREATIVE_PLANNING_SMOKE=1 uv run pytest \
    tests/test_social_studies_creative_planning_smoke.py -s
```

Expected: PASS — printed keyword set has ≥3 distinct 題材 keywords. Attach the printed set to the issue #114 verification comment.
