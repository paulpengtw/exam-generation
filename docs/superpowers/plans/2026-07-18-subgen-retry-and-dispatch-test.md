# Per-子題 Retry + Parallel-Dispatch Integration Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two remaining gaps of GitHub issue #117 ("Parallel per-子題 LLM generation"): (1) a failed 子題產生器 call gets a bounded number of fresh per-slot retries before the slot is silently dropped from `subquestions[]`, in both the social-studies and natural-sciences pipelines; (2) integration tests with a mocked LLM prove N parallel dispatches and correct 序號 result ordering in `generate_one`.

**Architecture:** The two-stage 文本生成器 → N parallel 子題產生器 pipeline from issue #117 is **already shipped** (commit `6018a0e`, PRs #118/#119): `ThreadPoolExecutor` fan-out capped by `SUBGEN_MAX_CONCURRENCY`, per-call `sub_generator#i` agent ids, `_GEN_LOCK` removed. This plan only adds a retry loop inside the existing per-slot worker closure `_generate_subquestion` (`src/social_studies/cli.py:705-742` and the near-identical `src/natural_sciences/cli.py:444-481`), driven by a new `Config.subgen_retries` knob (env `SUBGEN_RETRIES`, default 1) that sits alongside the existing `subgen_max_concurrency`. Tests inject fake clients through the existing `sub_client_factory: Callable[[], Any] | None` keyword on both `generate_one` implementations; a `threading.Barrier` proves real concurrency.

**Tech Stack:** Python 3.11 managed with `uv`; `pytest`; stdlib `threading` (`ThreadPoolExecutor` is already in place — tests add `Barrier`/`Lock`); Pydantic models already defined per subject. **No new dependencies.**

**Issue:** https://github.com/paulpengtw/exam-generation/issues/117 (remaining scope per the 2026-07-18 audit)

## Context: what is already done (do NOT re-implement)

- 文本生成器 call → N-entry 子題 plan → N concurrent 子題產生器 calls (`concurrent.futures.ThreadPoolExecutor`, `max_workers = min(len(sq_plans), config.subgen_max_concurrency)`).
- Per-call agent ids `sub_generator#<序號>` stamped on all streamed events via `generate_json(..., agent_override=agent_id)`.
- `sub_client_factory` test-injection hook on both `generate_one` signatures (`src/social_studies/cli.py:640`, `src/natural_sciences/cli.py:385`). When a non-`LLMClient` fake is passed as `client` **and** `sub_client_factory` is provided, the real parallel dispatch path runs with factory-produced sub-clients (`use_embedded_subquestions` is False).
- `Config.subgen_max_concurrency` (env `SUBGEN_MAX_CONCURRENCY`, default 6) in `src/config.py:25,53`.

**The gaps this plan closes:** today a 子題產生器 call that raises — or returns output `_parse_subquestion` cannot parse — becomes `None` and the slot vanishes from `subquestions[]` with only a stderr line. And no test exercises the `ThreadPoolExecutor` path at all (no test in `tests/` references `sub_client_factory`).

## Global Constraints

- **Out of scope (explicitly, per the 2026-07-18 audit):** the migration feature flag `enable_parallel_subquestion_generation` from the issue body — moot, the parallel path is the only path; and the latency benchmark artifact — YAGNI. Do not add either.
- **Out of scope:** math pipeline (`src/cli.py`) — it has no 子題 structure; and any `web/` frontend change.
- **No `server/` changes.** The server builds the src `Config` via `Config.from_env()` (`server/generate/routes.py:198-201`), so the new `SUBGEN_RETRIES` env var flows through with zero server code.
- **Behavior preservation:** `SUBGEN_RETRIES=0` must reproduce today's drop-on-first-failure behavior exactly. Default is `1` (one extra fresh call per failed slot).
- Retry applies only to the real LLM path — the `use_embedded_subquestions` shortcut (fake `client`, no factory) parses the plan dict directly and never retries.
- All commands run from the repo root `/workspace/exam-generation`. Python tests: `uv run pytest ...`. Do **not** run `tests/server` without `uv sync --extra web` (fastapi etc. are optional deps and a plain `uv sync` drops them); nothing in this plan needs `tests/server`.
- Ruff (`uv run ruff check`, line-length 100, rules E/F/I/W): the three touched src files carry exactly **6 pre-existing E501s** (long Chinese prompt strings). New/changed lines must stay ≤ 100 chars; the error count for those files must not grow. New test files must be ruff-clean.
- Threads, not asyncio — match the shipped implementation (the issue's async sketch was superseded by the thread-based PRs #118/#119).
- Retry attempts reuse the **same** prompt (deterministic build, outside the loop) and the same `agent_override=f"sub_generator#{idx}"`; each attempt uses a **fresh client** (a new `LLMClient(config)` — or one more `sub_client_factory()` call in tests). Repeated `llm_request`/`llm_response` pairs under one agent id are already how the verify/correct loop behaves, and `ExchangeRecorder` writes one row per pair, so no observer/recorder changes are needed.

---

### Task 1: `Config.subgen_retries` knob (env `SUBGEN_RETRIES`)

**Files:**
- Modify: `src/config.py:25` (dataclass field) and `src/config.py:53` (`from_env`)
- Test: `tests/test_config_subgen_retries.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: `Config.subgen_retries: int` — extra fresh-call attempts per failed 子題 slot; env `SUBGEN_RETRIES`, default `1`. Tasks 2–4 read it as `config.subgen_retries`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config_subgen_retries.py`:

```python
"""Tests for Config.subgen_retries env-var wiring (issue #117 remaining scope)."""

from __future__ import annotations

import pytest

from src.config import Config


def test_subgen_retries_dataclass_default() -> None:
    assert Config().subgen_retries == 1


def test_subgen_retries_defaults_to_1_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("SUBGEN_RETRIES", raising=False)
    cfg = Config.from_env()
    assert cfg.subgen_retries == 1


@pytest.mark.parametrize("value,expected", [("0", 0), ("1", 1), ("3", 3)])
def test_subgen_retries_reads_env_var(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("SUBGEN_RETRIES", value)
    cfg = Config.from_env()
    assert cfg.subgen_retries == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_subgen_retries.py -v`
Expected: FAIL — 5 tests, each with `AttributeError: 'Config' object has no attribute 'subgen_retries'`.

- [ ] **Step 3: Write the implementation**

In `src/config.py`, add the field directly after the existing `subgen_max_concurrency` line (line 25):

```python
    subgen_max_concurrency: int = 6
    subgen_retries: int = 1  # extra fresh 子題產生器 calls per failed slot (0 = drop on first failure)
```

And in `from_env` (after the existing `subgen_max_concurrency=` line, line 53):

```python
            subgen_max_concurrency=int(os.environ.get("SUBGEN_MAX_CONCURRENCY", "6")),
            subgen_retries=int(os.environ.get("SUBGEN_RETRIES", "1")),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_subgen_retries.py -v`
Expected: PASS — 5 tests green.

- [ ] **Step 5: Lint the touched file**

Run: `uv run ruff check src/config.py tests/test_config_subgen_retries.py`
Expected: `All checks passed!` (src/config.py has no pre-existing errors).

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_config_subgen_retries.py
git commit -m "feat: add SUBGEN_RETRIES config knob for per-子題 retry (#117)"
```

---

### Task 2: Social-studies per-子題 bounded retry

**Files:**
- Modify: `src/social_studies/cli.py:705-742` (the `_generate_subquestion` closure inside `generate_one`)
- Test: `tests/test_subgen_retry_social_studies.py` (create)

**Interfaces:**
- Consumes: `Config.subgen_retries` (Task 1); existing `generate_one(config, client, params, question_id, ..., skip_verify=..., disable_reference_fewshot=..., sub_client_factory=..., ...)` (all parameters are plain positional-or-keyword — call with keywords) and the fake-client contract below.
- Produces: retry semantics — per failed slot, up to `1 + max(0, config.subgen_retries)` total `generate_json` calls, each on a fresh client (`sub_client_factory()` per attempt when injected), before the slot is dropped. Both an **exception** from `generate_json` and a **`None`** from `_parse_subquestion` count as a failed attempt.

**Fake-client contract used by the tests** (dictated by the call sites in `generate_one`): the main `client` needs `get_observer()` and `generate_json(system, user, images=None, **kwargs) -> dict`; a sub-client needs `set_observer(obs)` and `generate_json(system, user, images=None, agent_override=None, **kwargs) -> dict`, where `agent_override` arrives as `"sub_generator#<序號>"`. Passing a non-`LLMClient` main client **plus** a `sub_client_factory` routes through the real `ThreadPoolExecutor` dispatch. `content_type="純文字"` keeps `_ensure_top_level_visual_spec` from issuing an extra LLM call; `skip_verify=True` skips the verifier; no `chart_spec` in any fake payload means no image rendering.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subgen_retry_social_studies.py`:

```python
"""Per-子題 bounded retry in the SS parallel 子題產生器 pipeline (issue #117).

A failed 子題產生器 call — an exception from generate_json OR output that
_parse_subquestion cannot parse — must get up to config.subgen_retries fresh
LLM calls for that slot only before the slot is dropped from subquestions[].
Other slots are never regenerated.
"""

from __future__ import annotations

import threading
from pathlib import Path

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion

N_SLOTS = 3


class _State:
    """Call-recording state shared across fake sub-clients (threads)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls_by_slot: dict[int, int] = {}
        self.factory_calls = 0


def _slot(agent_override: str) -> int:
    # generate_one always passes agent_override="sub_generator#<序號>".
    return int(agent_override.split("#", 1)[1])


def _valid_sq_raw(idx: int) -> dict:
    return {
        "序號": idx,
        "題型": "選擇題",
        "題目": f"第{idx}小題題目",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": f"概念{idx}",
    }


class _FakeTextClient:
    """文本生成器 stand-in: text shell with N_SLOTS 子題 plans, no chart_spec."""

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [
                {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
                for i in range(1, N_SLOTS + 1)
            ],
        }


class _FlakySubClient:
    """Raises for failing_slot on its first fail_times calls, then succeeds."""

    def __init__(self, state: _State, failing_slot: int, fail_times: int) -> None:
        self._state = state
        self._failing_slot = failing_slot
        self._fail_times = fail_times

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = _slot(agent_override)
        with self._state.lock:
            attempt = self._state.calls_by_slot.get(idx, 0) + 1
            self._state.calls_by_slot[idx] = attempt
        if idx == self._failing_slot and attempt <= self._fail_times:
            raise RuntimeError(f"boom: slot {idx} attempt {attempt}")
        return _valid_sq_raw(idx)


def _generate(state: _State, sub_client, subgen_retries: int) -> ExamQuestion:
    config = Config(data_dir=Path("data"), subgen_retries=subgen_retries)

    def factory():
        with state.lock:
            state.factory_calls += 1
        return sub_client

    params = sample_params(seed=11, content_type="純文字")
    question = generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="ss_retry_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=factory,
    )
    assert isinstance(question, ExamQuestion)
    return question


def test_failed_slot_is_retried_and_recovered() -> None:
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=1)
    question = _generate(state, flaky, subgen_retries=1)
    assert [sq.序號 for sq in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot == {1: 1, 2: 2, 3: 1}
    # Fresh client per attempt: 3 initial + 1 retry for slot 2.
    assert state.factory_calls == 4


def test_zero_retries_drops_failed_slot_immediately() -> None:
    """SUBGEN_RETRIES=0 preserves today's drop-on-first-failure behavior."""
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=1)
    question = _generate(state, flaky, subgen_retries=0)
    assert [sq.序號 for sq in question.subquestions] == [1, 3]
    assert state.calls_by_slot == {1: 1, 2: 1, 3: 1}
    assert state.factory_calls == 3


def test_slot_dropped_after_retry_budget_exhausted() -> None:
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=99)
    question = _generate(state, flaky, subgen_retries=2)
    assert [sq.序號 for sq in question.subquestions] == [1, 3]
    assert state.calls_by_slot == {1: 1, 2: 3, 3: 1}  # 1 initial + 2 retries
    assert state.factory_calls == 5


def test_unparseable_output_is_also_retried() -> None:
    """_parse_subquestion returning None (no exception) must also trigger retry."""

    class _GarbageThenGoodClient:
        def __init__(self, state: _State) -> None:
            self._state = state

        def set_observer(self, obs) -> None:
            pass

        def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
            idx = _slot(agent_override)
            with self._state.lock:
                attempt = self._state.calls_by_slot.get(idx, 0) + 1
                self._state.calls_by_slot[idx] = attempt
            if idx == 1 and attempt == 1:
                return ["not", "a", "dict"]  # _parse_subquestion -> None
            return _valid_sq_raw(idx)

    state = _State()
    question = _generate(state, _GarbageThenGoodClient(state), subgen_retries=1)
    assert [sq.序號 for sq in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot[1] == 2
    assert state.factory_calls == 4
```

- [ ] **Step 2: Run tests to verify they fail (red)**

Run: `uv run pytest tests/test_subgen_retry_social_studies.py -v`
Expected: **3 failed, 1 passed** —
- `test_failed_slot_is_retried_and_recovered` FAIL: `assert [1, 3] == [1, 2, 3]` (slot dropped, no retry yet)
- `test_zero_retries_drops_failed_slot_immediately` PASS (documents preserved behavior)
- `test_slot_dropped_after_retry_budget_exhausted` FAIL on `state.calls_by_slot` (got `{1: 1, 2: 1, 3: 1}`)
- `test_unparseable_output_is_also_retried` FAIL: `assert [2, 3] == [1, 2, 3]`

- [ ] **Step 3: Implement the retry loop**

In `src/social_studies/cli.py`, replace the `_generate_subquestion` closure (lines 705–742). Current code:

```python
    def _generate_subquestion(sq_plan: dict) -> SubQuestion | None:
        idx = sq_plan.get("序號", sq_plans.index(sq_plan) + 1)
        agent_id = f"sub_generator#{idx}"
        if use_embedded_subquestions:
            return _parse_subquestion(sq_plan, question_id, params, idx)

        sub_client = sub_client_factory() if sub_client_factory is not None else LLMClient(config)
        if hasattr(sub_client, "set_observer"):
            sub_client.set_observer(obs)
        slot_cfg = (
            params.subquestion_configs[idx - 1]
            if idx - 1 < len(params.subquestion_configs) else None
        )
        sub_user, sub_images = build_subquestion_user_prompt(
            核心問題=text_raw.get("核心問題", ""),
            文本=text_raw.get("文本", ""),
            取材來源=text_raw.get("取材來源", []),
            sq_plan=sq_plan,
            params=params,
            few_shot_dir=few_shot_dir,
            image_generation_mode=image_generation_mode,
            cfg=slot_cfg,
            disable_reference_fewshot=disable_reference_fewshot,
        )
        emit_stage(obs, agent_id, "llm_generate", "start")
        try:
            sq_raw = sub_client.generate_json(
                sub_system,
                sub_user,
                images=sub_images or None,
                agent_override=agent_id,
            )
            result = _parse_subquestion(sq_raw, question_id, params, idx)
        except Exception as e:
            print(f"  Sub-generator {agent_id} failed: {e}", file=sys.stderr)
            result = None
        emit_stage(obs, agent_id, "llm_generate", "end")
        return result
```

New code (prompt built once outside the loop — it is deterministic; fresh client per attempt; a `None` parse counts as a failed attempt):

```python
    def _generate_subquestion(sq_plan: dict) -> SubQuestion | None:
        idx = sq_plan.get("序號", sq_plans.index(sq_plan) + 1)
        agent_id = f"sub_generator#{idx}"
        if use_embedded_subquestions:
            return _parse_subquestion(sq_plan, question_id, params, idx)

        slot_cfg = (
            params.subquestion_configs[idx - 1]
            if idx - 1 < len(params.subquestion_configs) else None
        )
        sub_user, sub_images = build_subquestion_user_prompt(
            核心問題=text_raw.get("核心問題", ""),
            文本=text_raw.get("文本", ""),
            取材來源=text_raw.get("取材來源", []),
            sq_plan=sq_plan,
            params=params,
            few_shot_dir=few_shot_dir,
            image_generation_mode=image_generation_mode,
            cfg=slot_cfg,
            disable_reference_fewshot=disable_reference_fewshot,
        )

        attempts = 1 + max(0, config.subgen_retries)
        result: SubQuestion | None = None
        for attempt in range(1, attempts + 1):
            sub_client = (
                sub_client_factory() if sub_client_factory is not None else LLMClient(config)
            )
            if hasattr(sub_client, "set_observer"):
                sub_client.set_observer(obs)
            emit_stage(obs, agent_id, "llm_generate", "start", attempt=attempt)
            try:
                sq_raw = sub_client.generate_json(
                    sub_system,
                    sub_user,
                    images=sub_images or None,
                    agent_override=agent_id,
                )
                result = _parse_subquestion(sq_raw, question_id, params, idx)
            except Exception as e:
                print(
                    f"  Sub-generator {agent_id} attempt {attempt}/{attempts} failed: {e}",
                    file=sys.stderr,
                )
                result = None
            emit_stage(obs, agent_id, "llm_generate", "end", attempt=attempt)
            if result is not None:
                return result
            if attempt < attempts:
                print(
                    f"  Retrying sub-generator {agent_id} (attempt {attempt + 1}/{attempts})...",
                    file=sys.stderr,
                )
        print(
            f"  Sub-generator {agent_id} dropped after {attempts} attempt(s)",
            file=sys.stderr,
        )
        return None
```

Notes for the implementer:
- `emit_stage` accepts `**extra` (`src/llm_client.py:39-56`), so `attempt=attempt` is just an extra key on the stage event — observers pass dicts through, no consumer change needed.
- Only this closure changes; the `ThreadPoolExecutor` fan-out and the `sq_results`/序號-sort assembly directly below it stay untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subgen_retry_social_studies.py -v`
Expected: PASS — 4 tests green.

- [ ] **Step 5: Run the existing SS test files to catch regressions**

Run: `uv run pytest tests/test_social_studies_cli_creative_planning.py tests/test_per_subquestion_lc_lp_output.py tests/test_social_studies_subquestion_images.py -q`
Expected: all pass (baseline behavior unchanged: the embedded-subquestions shortcut and 序號 assembly are untouched).

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/social_studies/cli.py tests/test_subgen_retry_social_studies.py`
Expected: only the pre-existing `E501` errors already present in `src/social_studies/cli.py` (Chinese prompt strings); zero findings for the new test file; no new error codes or locations.

- [ ] **Step 7: Commit**

```bash
git add src/social_studies/cli.py tests/test_subgen_retry_social_studies.py
git commit -m "feat(ss): bounded per-子題 retry before dropping failed slots (#117)"
```

---

### Task 3: Natural-sciences per-子題 bounded retry + docs

**Files:**
- Modify: `src/natural_sciences/cli.py:444-481` (the `_generate_subquestion` closure inside `generate_one`)
- Test: `tests/test_subgen_retry_natural_sciences.py` (create)
- Modify: `README.md` (env table row after line 232; two-stage paragraph at line 49)
- Modify: `CLAUDE.md` (verify-loop bullet, line 23; `src/config.py` key-files row, line 188)

**Interfaces:**
- Consumes: `Config.subgen_retries` (Task 1); NS `generate_one` (`src/natural_sciences/cli.py:369`) with the same `sub_client_factory` hook and fake-client contract as Task 2 (see Task 2's contract note — it applies verbatim; NS has no `_ensure_top_level_visual_spec`, but keep `content_type="純文字"` anyway so no `chart_spec` is expected).
- Produces: identical retry semantics as Task 2, in the NS pipeline; operator docs for `SUBGEN_RETRIES`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subgen_retry_natural_sciences.py` (mirror of Task 2 with NS imports and the PISA-Science 題型 value).

> **題型 spelling trap:** the NS `SubQuestion.題型` Pydantic enum values come from `data/natural_sciences/curriculum/schema_parameters.csv` and use **spaces**: `Simple multiple-choice` / `Complex multiple-choice` / `Constructed response`. The hyphenated forms (`Simple-multiple-choice` …) are only the CLI `--q-type` choices / few-shot folder names — a hyphenated 題型 in a fake payload makes `_parse_subquestion` raise inside its `try`, return `None`, and silently drop the slot. Use the space-separated values in every fake payload below.

```python
"""Per-子題 bounded retry in the NS parallel 子題產生器 pipeline (issue #117).

Mirror of tests/test_subgen_retry_social_studies.py for the natural-sciences
generate_one: a failed 子題產生器 call gets up to config.subgen_retries fresh
LLM calls for that slot only before the slot is dropped.
"""

from __future__ import annotations

import threading
from pathlib import Path

from src.config import Config
from src.natural_sciences.cli import generate_one
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schemas import ExamQuestion

N_SLOTS = 3


class _State:
    """Call-recording state shared across fake sub-clients (threads)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls_by_slot: dict[int, int] = {}
        self.factory_calls = 0


def _slot(agent_override: str) -> int:
    return int(agent_override.split("#", 1)[1])


def _valid_sq_raw(idx: int) -> dict:
    return {
        "序號": idx,
        "題型": "Simple multiple-choice",
        "題目": f"第{idx}小題題目",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": f"概念{idx}",
    }


class _FakeTextClient:
    """文本生成器 stand-in: text shell with N_SLOTS 子題 plans, no chart_spec."""

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [
                {"序號": i, "題型": "Simple multiple-choice", "出題概念": f"概念{i}"}
                for i in range(1, N_SLOTS + 1)
            ],
        }


class _FlakySubClient:
    """Raises for failing_slot on its first fail_times calls, then succeeds."""

    def __init__(self, state: _State, failing_slot: int, fail_times: int) -> None:
        self._state = state
        self._failing_slot = failing_slot
        self._fail_times = fail_times

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = _slot(agent_override)
        with self._state.lock:
            attempt = self._state.calls_by_slot.get(idx, 0) + 1
            self._state.calls_by_slot[idx] = attempt
        if idx == self._failing_slot and attempt <= self._fail_times:
            raise RuntimeError(f"boom: slot {idx} attempt {attempt}")
        return _valid_sq_raw(idx)


def _generate(state: _State, sub_client, subgen_retries: int) -> ExamQuestion:
    config = Config(data_dir=Path("data"), subgen_retries=subgen_retries)

    def factory():
        with state.lock:
            state.factory_calls += 1
        return sub_client

    params = sample_params(seed=11, content_type="純文字")
    question = generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="ns_retry_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=factory,
    )
    assert isinstance(question, ExamQuestion)
    return question


def test_failed_slot_is_retried_and_recovered() -> None:
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=1)
    question = _generate(state, flaky, subgen_retries=1)
    assert [sq.序號 for sq in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot == {1: 1, 2: 2, 3: 1}
    assert state.factory_calls == 4


def test_zero_retries_drops_failed_slot_immediately() -> None:
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=1)
    question = _generate(state, flaky, subgen_retries=0)
    assert [sq.序號 for sq in question.subquestions] == [1, 3]
    assert state.calls_by_slot == {1: 1, 2: 1, 3: 1}
    assert state.factory_calls == 3


def test_slot_dropped_after_retry_budget_exhausted() -> None:
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=99)
    question = _generate(state, flaky, subgen_retries=2)
    assert [sq.序號 for sq in question.subquestions] == [1, 3]
    assert state.calls_by_slot == {1: 1, 2: 3, 3: 1}  # 1 initial + 2 retries
    assert state.factory_calls == 5


def test_unparseable_output_is_also_retried() -> None:
    """_parse_subquestion returning None (no exception) must also trigger retry."""

    class _GarbageThenGoodClient:
        def __init__(self, state: _State) -> None:
            self._state = state

        def set_observer(self, obs) -> None:
            pass

        def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
            idx = _slot(agent_override)
            with self._state.lock:
                attempt = self._state.calls_by_slot.get(idx, 0) + 1
                self._state.calls_by_slot[idx] = attempt
            if idx == 1 and attempt == 1:
                return ["not", "a", "dict"]  # _parse_subquestion -> None
            return _valid_sq_raw(idx)

    state = _State()
    question = _generate(state, _GarbageThenGoodClient(state), subgen_retries=1)
    assert [sq.序號 for sq in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot[1] == 2
    assert state.factory_calls == 4
```

- [ ] **Step 2: Run tests to verify they fail (red)**

Run: `uv run pytest tests/test_subgen_retry_natural_sciences.py -v`
Expected: **3 failed, 1 passed** — same shape as Task 2 Step 2 (`test_zero_retries_drops_failed_slot_immediately` passes; the other three fail because NS still drops on first failure).

- [ ] **Step 3: Implement the retry loop in the NS pipeline**

In `src/natural_sciences/cli.py`, replace the `_generate_subquestion` closure (lines 444–481). Current code:

```python
    def _generate_subquestion(sq_plan: dict) -> SubQuestion | None:
        idx = sq_plan.get("序號", sq_plans.index(sq_plan) + 1)
        agent_id = f"sub_generator#{idx}"
        if use_embedded_subquestions:
            return _parse_subquestion(sq_plan, question_id, params, idx)

        sub_client = sub_client_factory() if sub_client_factory is not None else LLMClient(config)
        if hasattr(sub_client, "set_observer"):
            sub_client.set_observer(obs)
        slot_cfg = (
            params.subquestion_configs[idx - 1]
            if idx - 1 < len(params.subquestion_configs) else None
        )
        sub_user, sub_images = build_subquestion_user_prompt(
            核心問題=text_raw.get("核心問題", ""),
            文本=text_raw.get("文本", ""),
            取材來源=text_raw.get("取材來源", []),
            sq_plan=sq_plan,
            params=params,
            few_shot_dir=config.data_dir / "natural_sciences" / "few_shot",
            image_generation_mode=image_generation_mode,
            cfg=slot_cfg,
            disable_reference_fewshot=disable_reference_fewshot,
        )
        emit_stage(obs, agent_id, "llm_generate", "start")
        try:
            sq_raw = sub_client.generate_json(
                sub_system,
                sub_user,
                images=sub_images or None,
                agent_override=agent_id,
            )
            result = _parse_subquestion(sq_raw, question_id, params, idx)
        except Exception as e:
            print(f"  Sub-generator {agent_id} failed: {e}", file=sys.stderr)
            result = None
        emit_stage(obs, agent_id, "llm_generate", "end")
        return result
```

New code (identical structure to Task 2 Step 3; only the `few_shot_dir` argument differs):

```python
    def _generate_subquestion(sq_plan: dict) -> SubQuestion | None:
        idx = sq_plan.get("序號", sq_plans.index(sq_plan) + 1)
        agent_id = f"sub_generator#{idx}"
        if use_embedded_subquestions:
            return _parse_subquestion(sq_plan, question_id, params, idx)

        slot_cfg = (
            params.subquestion_configs[idx - 1]
            if idx - 1 < len(params.subquestion_configs) else None
        )
        sub_user, sub_images = build_subquestion_user_prompt(
            核心問題=text_raw.get("核心問題", ""),
            文本=text_raw.get("文本", ""),
            取材來源=text_raw.get("取材來源", []),
            sq_plan=sq_plan,
            params=params,
            few_shot_dir=config.data_dir / "natural_sciences" / "few_shot",
            image_generation_mode=image_generation_mode,
            cfg=slot_cfg,
            disable_reference_fewshot=disable_reference_fewshot,
        )

        attempts = 1 + max(0, config.subgen_retries)
        result: SubQuestion | None = None
        for attempt in range(1, attempts + 1):
            sub_client = (
                sub_client_factory() if sub_client_factory is not None else LLMClient(config)
            )
            if hasattr(sub_client, "set_observer"):
                sub_client.set_observer(obs)
            emit_stage(obs, agent_id, "llm_generate", "start", attempt=attempt)
            try:
                sq_raw = sub_client.generate_json(
                    sub_system,
                    sub_user,
                    images=sub_images or None,
                    agent_override=agent_id,
                )
                result = _parse_subquestion(sq_raw, question_id, params, idx)
            except Exception as e:
                print(
                    f"  Sub-generator {agent_id} attempt {attempt}/{attempts} failed: {e}",
                    file=sys.stderr,
                )
                result = None
            emit_stage(obs, agent_id, "llm_generate", "end", attempt=attempt)
            if result is not None:
                return result
            if attempt < attempts:
                print(
                    f"  Retrying sub-generator {agent_id} (attempt {attempt + 1}/{attempts})...",
                    file=sys.stderr,
                )
        print(
            f"  Sub-generator {agent_id} dropped after {attempts} attempt(s)",
            file=sys.stderr,
        )
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subgen_retry_natural_sciences.py -v`
Expected: PASS — 4 tests green.

- [ ] **Step 5: Document `SUBGEN_RETRIES`**

Four exact edits:

1. `README.md` env table — after the row (line 232):

```markdown
| `SUBGEN_MAX_CONCURRENCY` | CLI + server | Max concurrent 子題產生器 LLM calls per 題組 (SS/NS only) | `6` |
```

insert:

```markdown
| `SUBGEN_RETRIES` | CLI + server | Extra fresh-call attempts for a failed/unparseable 子題產生器 slot before that 子題 is dropped (SS/NS only; `0` = drop on first failure) | `1` |
```

2. `README.md` line 49 (two-stage generation bullet) — after the sentence ending `` capped by `SUBGEN_MAX_CONCURRENCY`, default 6). `` and before `The assembled 題組 then flows`, insert:

```markdown
A 子題產生器 call that raises or returns unparseable output is retried with a fresh LLM call for that slot only, up to `SUBGEN_RETRIES` times (default 1), before the slot is dropped.
```

3. `CLAUDE.md` line 23 — replace the fragment

```markdown
(via `ThreadPoolExecutor`, capped by `SUBGEN_MAX_CONCURRENCY`, default 6); the assembled 題組 then enters the verify/correct loop.
```

with

```markdown
(via `ThreadPoolExecutor`, capped by `SUBGEN_MAX_CONCURRENCY`, default 6; failed/unparseable 子題 calls get up to `SUBGEN_RETRIES` fresh retries, default 1, before the slot is dropped); the assembled 題組 then enters the verify/correct loop.
```

4. `CLAUDE.md` line 188 — replace the key-files row

```markdown
| `src/config.py` | Environment variable configuration; `subgen_max_concurrency` (env `SUBGEN_MAX_CONCURRENCY`, default 6) caps parallel 子題產生器 calls |
```

with

```markdown
| `src/config.py` | Environment variable configuration; `subgen_max_concurrency` (env `SUBGEN_MAX_CONCURRENCY`, default 6) caps parallel 子題產生器 calls; `subgen_retries` (env `SUBGEN_RETRIES`, default 1) bounds per-子題 fresh-call retries before a failed slot is dropped |
```

- [ ] **Step 6: Run the existing NS test files + lint**

Run: `uv run pytest tests/test_natural_sciences_context_builder.py tests/test_natural_sciences_verifier.py tests/test_natural_sciences_few_shot.py -q`
Expected: all pass.

Run: `uv run ruff check src/natural_sciences/cli.py tests/test_subgen_retry_natural_sciences.py`
Expected: only the pre-existing `E501` errors already present in `src/natural_sciences/cli.py`; zero findings for the new test file.

- [ ] **Step 7: Commit**

```bash
git add src/natural_sciences/cli.py tests/test_subgen_retry_natural_sciences.py README.md CLAUDE.md
git commit -m "feat(ns): bounded per-子題 retry + SUBGEN_RETRIES docs (#117)"
```

---

### Task 4: Parallel-dispatch + ordering integration tests (both subjects), final verification

**Files:**
- Test: `tests/test_subgen_parallel_dispatch.py` (create)

**Interfaces:**
- Consumes: the shipped `ThreadPoolExecutor` dispatch in both `generate_one` implementations, the `sub_client_factory` hook, and `Config(subgen_max_concurrency=..., subgen_retries=...)` (Task 1). Fake-client contract from Task 2.
- Produces: regression tests locking in issue #117's acceptance criteria "N parallel dispatches" and "correct 序號 ordering". **These test already-shipped behavior, so there is no red→green implementation step — they must pass on first run.** If they fail, stop and debug the pipeline (that is a real bug), do not adjust the assertions.

Concurrency proof: every fake sub-client blocks on one shared `threading.Barrier(N_SLOTS)`. The barrier releases only when all `N_SLOTS` `generate_json` calls are in flight **simultaneously**; if dispatch were serialized the barrier would time out, the worker would raise `BrokenBarrierError`, and — with `subgen_retries=0` so no retry masks it — the slot would be dropped and the subquestion-count assertion fails loudly. Ordering proof: after the barrier, workers sleep `0.1 * (N_SLOTS - idx)` seconds so they **complete in reverse 序號 order**, yet the assembled `subquestions[]` must come back sorted by 序號 with each slot's own payload.

- [ ] **Step 1: Write the tests**

Create `tests/test_subgen_parallel_dispatch.py`:

```python
"""Integration tests: N 子題產生器 dispatches run in parallel and results
keep 序號 order (issue #117 acceptance criteria), for both SS and NS.

A shared threading.Barrier(N_SLOTS) only releases when all N fake LLM calls
are in flight at once — serialized dispatch would time out and fail loudly
(subgen_retries=0 ensures no retry masks a BrokenBarrierError). Staggered
sleeps then force reverse-序號 completion, so as_completed() yields results
out of order and the 序號-sorted reassembly is actually exercised.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from src.config import Config

N_SLOTS = 4
BARRIER_TIMEOUT_S = 30.0


class _DispatchState:
    def __init__(self) -> None:
        self.barrier = threading.Barrier(N_SLOTS)
        self.lock = threading.Lock()
        self.dispatched_agents: list[str] = []
        self.completion_order: list[int] = []


class _BarrierSubClient:
    """Blocks until all N_SLOTS workers arrive, then finishes in reverse order."""

    def __init__(self, state: _DispatchState, sq_raw_for) -> None:
        self._state = state
        self._sq_raw_for = sq_raw_for

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#", 1)[1])
        with self._state.lock:
            self._state.dispatched_agents.append(agent_override)
        # Concurrency proof: releases only when N_SLOTS calls are in flight.
        self._state.barrier.wait(timeout=BARRIER_TIMEOUT_S)
        # Scramble completion: higher 序號 finishes first.
        time.sleep(0.1 * (N_SLOTS - idx))
        with self._state.lock:
            self._state.completion_order.append(idx)
        return self._sq_raw_for(idx)


def _config() -> Config:
    # subgen_retries=0: a BrokenBarrierError must surface as a dropped slot,
    # never be absorbed by the Task 2/3 retry path.
    return Config(
        data_dir=Path("data"),
        subgen_max_concurrency=N_SLOTS,
        subgen_retries=0,
    )


def _assert_parallel_and_ordered(state: _DispatchState, question) -> None:
    # N parallel dispatches, exactly one per slot.
    assert sorted(state.dispatched_agents) == [
        f"sub_generator#{i}" for i in range(1, N_SLOTS + 1)
    ]
    # Workers completed out of 序號 order (reverse, via staggered sleeps)...
    assert set(state.completion_order) == set(range(1, N_SLOTS + 1))
    assert state.completion_order != sorted(state.completion_order)
    # ...but the assembled 題組 is in 序號 order with each slot's own payload.
    assert [sq.序號 for sq in question.subquestions] == [1, 2, 3, 4]
    assert [sq.題目 for sq in question.subquestions] == [
        f"第{i}小題題目" for i in range(1, N_SLOTS + 1)
    ]


# ---------------------------------------------------------------- 社會領域


def _ss_sq_raw(idx: int) -> dict:
    return {
        "序號": idx,
        "題型": "選擇題",
        "題目": f"第{idx}小題題目",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": f"概念{idx}",
    }


class _SSTextClient:
    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [
                {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
                for i in range(1, N_SLOTS + 1)
            ],
        }


def test_social_studies_parallel_dispatch_and_seq_order() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import ExamQuestion

    state = _DispatchState()
    params = sample_params(seed=23, content_type="純文字")
    question = generate_one(
        config=_config(),
        client=_SSTextClient(),
        params=params,
        question_id="ss_dispatch_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _BarrierSubClient(state, _ss_sq_raw),
    )
    assert isinstance(question, ExamQuestion)
    _assert_parallel_and_ordered(state, question)


# ---------------------------------------------------------------- 自然科學


def _ns_sq_raw(idx: int) -> dict:
    return {
        "序號": idx,
        "題型": "Simple multiple-choice",
        "題目": f"第{idx}小題題目",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": f"概念{idx}",
    }


class _NSTextClient:
    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [
                {"序號": i, "題型": "Simple multiple-choice", "出題概念": f"概念{i}"}
                for i in range(1, N_SLOTS + 1)
            ],
        }


def test_natural_sciences_parallel_dispatch_and_seq_order() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params
    from src.natural_sciences.schemas import ExamQuestion

    state = _DispatchState()
    params = sample_params(seed=23, content_type="純文字")
    question = generate_one(
        config=_config(),
        client=_NSTextClient(),
        params=params,
        question_id="ns_dispatch_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _BarrierSubClient(state, _ns_sq_raw),
    )
    assert isinstance(question, ExamQuestion)
    _assert_parallel_and_ordered(state, question)
```

- [ ] **Step 2: Run the new tests — expected to pass immediately**

Run: `uv run pytest tests/test_subgen_parallel_dispatch.py -v`
Expected: PASS — 2 tests green in well under 5 seconds each (the staggered sleeps total ~0.6 s per test). A hang of ~30 s followed by a failed subquestion-count assertion means dispatch was serialized — that is a product bug; investigate `ThreadPoolExecutor` wiring in the relevant `generate_one`, do not weaken the test.

- [ ] **Step 3: Lint the new test file**

Run: `uv run ruff check tests/test_subgen_parallel_dispatch.py`
Expected: `All checks passed!`

- [ ] **Step 4: Run the full non-server suite**

Run: `uv run pytest tests/ --ignore=tests/server -q`
Expected: all pass, 1 skipped — 15 more tests than the pre-plan baseline (baseline at plan time: `296 passed, 1 skipped`; after this plan: `311 passed, 1 skipped`). `tests/server` is excluded because it needs `uv sync --extra web`; no server code changed in this plan.

- [ ] **Step 5: Final lint sweep over everything this plan touched**

Run: `uv run ruff check src/config.py src/social_studies/cli.py src/natural_sciences/cli.py tests/test_config_subgen_retries.py tests/test_subgen_retry_social_studies.py tests/test_subgen_retry_natural_sciences.py tests/test_subgen_parallel_dispatch.py`
Expected: exactly the **6 pre-existing E501** errors (all in the two cli files' long Chinese prompt strings, present before this plan) and nothing else.

- [ ] **Step 6: Commit**

```bash
git add tests/test_subgen_parallel_dispatch.py
git commit -m "test: prove N parallel 子題 dispatches and 序號 result ordering (#117)"
```
