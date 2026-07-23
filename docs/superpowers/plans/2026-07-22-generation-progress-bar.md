# Generation Progress Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full-width sticky generation-progress bar that reports reliable item milestones after Confirm, supports modal-confirmed cancellation, and preserves completed questions.

**Architecture:** Use the existing `GenerationLog.id` as the generation `run_id`. A new in-process `GenerationRun` coordinator tracks per-item state and cancellation, while the existing SSE stream emits explicit `generation_progress`, `generation_cancel_requested`, and `generation_terminal` events. The React hook normalizes those events into a question-scoped progress model; `GeneratePage` renders a compact/expandable fixed-bottom component and keeps existing cards/results independent from the overlay.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy/Alembic, asyncio + ThreadPoolExecutor, SSE via `sse-starlette` and `@microsoft/fetch-event-source`, React 19, TypeScript, Tailwind CSS v4, Vitest, React Testing Library, pytest.

## Global Constraints

- Progress is milestone-based; do not add an estimated percentage.
- `completed` counts only final accepted top-level questions, not drafts, verification attempts, or subquestions.
- Batch questions and subquestion generation remain concurrent and may complete out of order.
- The top-level headline total is the requested question count; subquestion counts are detail-only metadata.
- The sticky bar spans the full viewport width, with inner content aligned to the existing page container.
- The bar is compact by default, expandable for details, and remains visible in completed, failed, and canceled terminal states until dismissed.
- Cancellation requires a confirmation modal; completed questions are preserved.
- Cancellation is cooperative: in-flight provider/renderer calls may finish, but no new retry/correction/image operation may start after a safe cancellation checkpoint.
- Every progress and terminal event is correlated by `run_id`; stale-run events must be ignored by the frontend.
- `done` is a transport-closure marker only and must not overwrite an explicit failed or canceled terminal state.
- Preserve existing `result` SSE payload compatibility for smoke scripts and external consumers; attach transport metadata under a reserved `_generation` key and strip it before persistence/display.
- Keep existing detailed `stage`, `llm_*`, `question_update`, and LLM-trace functionality available as secondary detail.
- Do not change the persisted exam-question schema solely for progress UI metadata.
- Use existing translations in `web/src/i18n/messages.ts`; add English and zh-TW strings for every new user-visible label.
- Do not add a new durable job queue or a cross-process cancellation store in this feature; the active-run registry is process-local and uses the existing generation log for identity and ownership.

---

## File map

### Backend

- **Create:** `server/generate/progress.py` — thread-safe run state, item milestones, aggregate stage selection, cancellation token, and serialized progress snapshots.
- **Create:** `tests/server/test_generation_progress.py` — pure coordinator tests for counts, stage precedence, cancellation, monotonicity, and terminal state.
- **Create:** `src/common/cancellation.py` — shared cancellation exception/check helper that subject pipelines can use without importing server code.
- **Modify:** `src/cli.py` — add optional cancellation checkpoints to math generation/correction and image/verify boundaries.
- **Modify:** `src/social_studies/cli.py` — add cancellation checkpoints to text generation, subquestion retries, image loops, verification, and corrections.
- **Modify:** `src/natural_sciences/cli.py` — add cancellation checkpoints to text generation, subquestion retries, image/verification boundaries, and corrections.
- **Create:** `tests/test_generation_cancellation.py` — subject-pipeline cancellation checkpoint tests.
- **Modify:** `server/generate/service.py` — register worker item state, map worker stages to progress, emit result metadata/progress/terminal events, continue after item failures, and pass cancellation callbacks.
- **Create:** `tests/server/test_generation_progress_service.py` — service-level SSE tests for concurrent completion, failure isolation, result metadata, and cancellation.
- **Modify:** `server/generate/routes.py` — create/register runs, update generation-log status from terminal events, and expose authenticated cancellation endpoint.
- **Modify:** `server/models.py` — add `canceled` to `GenerationStatus`.
- **Modify:** `server/app.py` — initialize the process-local generation-run registry on `app.state`.
- **Create:** `alembic/versions/9f5e1a2c3d4b_add_canceled_generation_status.py` — add `canceled` to the native PostgreSQL enum; no-op for SQLite’s string-backed enum.
- **Create:** `tests/server/test_generate_cancel.py` — cancellation endpoint ownership, idempotency, and active-run behavior.

### Frontend

- **Modify:** `web/src/hooks/useGenerate.ts` — progress types/state, event normalization, stale-run filtering, cancellation request, terminal-state handling, and dismissible progress state.
- **Modify:** `web/src/hooks/useGenerate.test.ts` — mock SSE and fetch to cover the new hook contract.
- **Create:** `web/src/components/CancelGenerationModal.tsx` — accessible confirmation modal.
- **Create:** `web/src/components/CancelGenerationModal.test.tsx` — modal keyboard, labels, and action tests.
- **Create:** `web/src/components/GenerationProgressBar.tsx` — fixed-bottom compact bar, expandable item details, terminal summaries, and cancel/dismiss controls.
- **Create:** `web/src/components/GenerationProgressBar.test.tsx` — active, expanded, terminal, responsive-control, and cancel behavior tests.
- **Modify:** `web/src/components/ProgressLog.tsx` — suppress the empty black log and accept the status/error combinations used inside expanded details.
- **Modify:** `web/src/pages/GeneratePage.tsx` — mount the bar, pass hook state/actions, move existing agent/LLM detail into expansion, and reserve bottom layout space.
- **Create:** `web/src/pages/GeneratePage.test.tsx` — page-level wiring test for the progress bar and cancellation callback.
- **Modify:** `web/src/i18n/messages.ts` — add all progress-stage, item-status, cancellation-modal, terminal, dismissal, and connection-error translations in both locales.

### Documentation and verification

- **Modify:** `FLOW.md` — document the Confirm boundary, run-scoped progress events, cancellation endpoint, and preserved partial results.
- **Modify:** `scripts/smoke_test_phase2.sh` — replace the obsolete required `progress` assertion with `generation_progress`/`generation_terminal` checks while retaining the compatible result-payload assertions.

---

## Task 1: Build the thread-safe generation-run coordinator

**Files:**
- Create: `server/generate/progress.py`
- Test: `tests/server/test_generation_progress.py`

**Interfaces:**
- Produces `GenerationRun`, `GenerationRunRegistry`, `ItemStatus`, `AggregateStage`, `TerminalStatus`, and `ProgressSnapshot` for Tasks 3–4.
- `GenerationRun` also exposes `cancel_item(index: int)`, which transitions an active item to `canceled` without changing completed siblings.
- `GenerationRun` uses the existing generation-log UUID as `run_id` and accepts `user_id` and `total` at construction.

- [ ] **Step 1: Write failing coordinator tests**

Add tests covering the exact public behavior:

```python
from uuid import uuid4

from server.generate.progress import GenerationRun, GenerationRunRegistry


def test_progress_counts_and_stage_precedence() -> None:
    run = GenerationRun(uuid4(), uuid4(), total=3)
    run.start_item(0)
    run.start_item(1)
    run.update_stage(0, "rendering")
    run.update_stage(1, "verifying")
    run.complete_item(0, item_id="q0")

    snapshot = run.snapshot()
    assert snapshot["total"] == 3
    assert snapshot["completed"] == 1
    assert snapshot["active"] == 1
    assert snapshot["pending"] == 1
    assert snapshot["current_stage"] == "verifying_answers"
    assert snapshot["item_index"] == 1
    assert snapshot["item_status"] == "verifying"


def test_cancel_marks_pending_items_and_is_idempotent() -> None:
    run = GenerationRun(uuid4(), uuid4(), total=2)
    run.start_item(0)
    assert run.request_cancel() is True
    assert run.request_cancel() is False
    run.cancel_pending_items()

    snapshot = run.snapshot()
    assert run.is_cancel_requested() is True
    assert snapshot["canceled"] == 1
    assert snapshot["pending"] == 0


def test_registry_enforces_run_lookup_by_id() -> None:
    registry = GenerationRunRegistry()
    run = registry.register(uuid4(), uuid4(), total=1)
    assert registry.get(run.run_id) is run
    registry.remove(run.run_id)
    assert registry.get(run.run_id) is None
```

Also test that `completed`, `failed`, and `canceled` counts never decrease, that terminal snapshots set `terminal=True`, and that the aggregate stage priority is correcting > verifying > rendering > generating > pending > finalizing.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
uv run pytest tests/server/test_generation_progress.py -q
```

Expected: FAIL because `server.generate.progress` does not exist.

- [ ] **Step 3: Implement the coordinator**

Create `server/generate/progress.py` with these concrete definitions:

```python
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Literal

ItemStatus = Literal[
    "pending", "generating", "rendering", "verifying", "correcting",
    "completed", "failed", "canceled",
]
AggregateStage = Literal[
    "fixing_answer_issues", "verifying_answers", "rendering_images",
    "generating_questions", "waiting_to_start", "finalizing",
]
TerminalStatus = Literal["completed", "failed", "canceled"]
ProgressSnapshot = dict[str, object]

_STAGE_ORDER: tuple[ItemStatus, ...] = (
    "correcting", "verifying", "rendering", "generating", "pending",
)
_STAGE_KEYS: dict[ItemStatus, str] = {
    "correcting": "fixing_answer_issues",
    "verifying": "verifying_answers",
    "rendering": "rendering_images",
    "generating": "generating_questions",
    "pending": "waiting_to_start",
}
_STAGE_LABELS: dict[str, str] = {
    "fixing_answer_issues": "Fixing answer issues",
    "verifying_answers": "Verifying answers",
    "rendering_images": "Rendering images",
    "generating_questions": "Generating questions",
    "waiting_to_start": "Waiting to start",
    "finalizing": "Finalizing",
}

@dataclass
class ItemProgress:
    index: int
    status: ItemStatus = "pending"
    item_id: str | None = None
    latest_message: str | None = None
    error_message: str | None = None
    subquestions_completed: int | None = None
    subquestions_total: int | None = None

class GenerationRun:
    def __init__(self, run_id: uuid.UUID, user_id: uuid.UUID, total: int) -> None:
        self.run_id = run_id
        self.user_id = user_id
        self.total = total
        self._items = {i: ItemProgress(index=i) for i in range(total)}
        self._cancel_event = threading.Event()
        self._lock = threading.RLock()
        self._terminal_status: TerminalStatus | None = None

    def start_item(self, index: int, *, item_id: str | None = None) -> None: ...
    def update_stage(self, index: int, stage: ItemStatus, *, item_id: str | None = None) -> None: ...
    def update_subquestions(self, index: int, completed: int, total: int) -> None: ...
    def complete_item(self, index: int, *, item_id: str | None = None) -> None: ...
    def fail_item(self, index: int, message: str) -> None: ...
    def cancel_item(self, index: int) -> None: ...
    def cancel_pending_items(self) -> None: ...
    def request_cancel(self) -> bool: ...
    def is_cancel_requested(self) -> bool: ...
    def terminal(self, status: TerminalStatus) -> None: ...
    def snapshot(self, *, item_index: int | None = None, item_id: str | None = None) -> dict: ...

class GenerationRunRegistry:
    def register(self, run_id: uuid.UUID, user_id: uuid.UUID, total: int) -> GenerationRun: ...
    def get(self, run_id: uuid.UUID) -> GenerationRun | None: ...
    def remove(self, run_id: uuid.UUID) -> None: ...
```

Implement all mutating methods under the `RLock`. `snapshot()` must serialize `run_id` as a string, include `total`, `completed`, `failed`, `active`, `pending`, `canceled`, `current_stage`, `stage_label`, `terminal`, and optional item/subquestion fields. When `item_index` is omitted, select the highest-priority active item for the optional item fields. Compute the aggregate stage from `_STAGE_ORDER`; use `finalizing` only when no pending/active items remain and the run is not yet terminal.

- [ ] **Step 4: Run the coordinator tests and verify they pass**

Run:

```bash
uv run pytest tests/server/test_generation_progress.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the coordinator**

```bash
git add server/generate/progress.py tests/server/test_generation_progress.py
git commit -m "feat: add generation progress coordinator"
```

---

## Task 2: Add cancellation checkpoints to subject pipelines

**Files:**
- Create: `src/common/cancellation.py`
- Modify: `src/cli.py`
- Modify: `src/social_studies/cli.py`
- Modify: `src/natural_sciences/cli.py`
- Create: `tests/test_generation_cancellation.py`

**Interfaces:**
- Produces `GenerationCancelled`, `ShouldCancel`, and `raise_if_cancelled()`.
- Adds `should_cancel: ShouldCancel | None = None` as the final optional parameter to each subject’s `generate_one()` and `generate_with_corrections()`; existing callers remain source-compatible.
- Social studies’ `_render_subquestion_images()` also receives the optional callback.

- [ ] **Step 1: Write failing cancellation tests**

Create a test for the shared helper and at least one boundary in each subject pipeline. The helper test must have this shape:

```python
import pytest

from src.common.cancellation import GenerationCancelled, raise_if_cancelled


def test_raise_if_cancelled_raises_only_when_requested() -> None:
    raise_if_cancelled(lambda: False)
    with pytest.raises(GenerationCancelled):
        raise_if_cancelled(lambda: True)
```

For the subject tests, monkeypatch the initial generator/renderer/verifier functions so a callback that returns `True` causes `GenerationCancelled` before the next downstream operation. Assert that the downstream mock was not called. Use the existing subject schema fixtures/helpers rather than constructing unrelated schemas.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
uv run pytest tests/test_generation_cancellation.py -q
```

Expected: FAIL because the helper and callback parameters do not exist.

- [ ] **Step 3: Implement the shared helper**

Create `src/common/cancellation.py`:

```python
from __future__ import annotations

from collections.abc import Callable

ShouldCancel = Callable[[], bool]


class GenerationCancelled(Exception):
    """Raised at a safe generation boundary after a run cancellation request."""


def raise_if_cancelled(should_cancel: ShouldCancel | None) -> None:
    if should_cancel is not None and should_cancel():
        raise GenerationCancelled()
```

- [ ] **Step 4: Add checkpoints to math**

In `src/cli.py`, append `should_cancel` to `generate_one()` and `generate_with_corrections()`. Call `raise_if_cancelled(should_cancel)`:

1. immediately before the initial LLM call;
2. after parsing and before image rendering;
3. after image rendering and before verification;
4. at the top of every correction-loop iteration;
5. before correction, before correction-image rerender, and before re-verification.

Pass the callback from `generate_with_corrections()` into `generate_one()`.

- [ ] **Step 5: Add checkpoints to social studies and natural sciences**

Apply the same top-level boundaries in both subject modules. In each parallel subquestion retry loop, call `raise_if_cancelled()` before creating a new sub-client and again before starting a retry. In social studies, add the callback to `_render_subquestion_images()` and check it before each subquestion image render. Do not catch `GenerationCancelled` inside a subquestion worker; let the parent worker classify the item as canceled.

- [ ] **Step 6: Run the cancellation tests and existing generation tests**

Run:

```bash
uv run pytest tests/test_generation_cancellation.py tests/test_subgen_parallel_dispatch.py tests/test_subgen_retry_social_studies.py tests/test_subgen_retry_natural_sciences.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit cancellation checkpoints**

```bash
git add src/common/cancellation.py src/cli.py src/social_studies/cli.py src/natural_sciences/cli.py tests/test_generation_cancellation.py
git commit -m "feat: add cooperative generation cancellation"
```

---

## Task 3: Emit question-scoped progress from the generation service

**Files:**
- Modify: `server/generate/service.py`
- Create: `tests/server/test_generation_progress_service.py`

**Interfaces:**
- Extends `generate_question_stream()` with `run: GenerationRun | None = None` after `generation_log_id`.
- Emits `started`, `generation_progress`, `question_update`, compatible `result`, `generation_cancel_requested`, `generation_terminal`, and final `done` events.
- Result events remain question-shaped and add only `_generation: {"index": int, "item_id": str | None}`.

- [ ] **Step 1: Write failing service tests**

Create a `collect_stream(params, run=None) -> list[dict]` helper in the test file that builds a `ServerConfig`, a `SimpleNamespace(renderer_pool=None)`, and collects every event from `service.generate_question_stream(params, config, app_state, run=run)`. Patch one subject generator with deterministic functions; use a short `time.sleep()` keyed by item index to force out-of-order completion. Cover:

```python
def test_service_emits_indexed_results_and_terminal_progress(tmp_path) -> None:
    events = asyncio.run(collect_stream(count=2, fake_workers_complete_out_of_order=True))
    started = next(e for e in events if e["event"] == "started")
    assert started["data"]["total"] == 2
    results = [e["data"] for e in events if e["event"] == "result"]
    assert {r["_generation"]["index"] for r in results} == {0, 1}
    assert all("題目" in r for r in results)
    terminal = next(e for e in events if e["event"] == "generation_terminal")
    assert terminal["data"]["status"] == "completed"
    assert terminal["data"]["completed"] == 2
    assert events[-1]["event"] == "done"
```

Also test:

- one worker failure still allows sibling results and yields terminal `failed` with `failed=1`;
- a run canceled before worker execution yields no result for canceled items and terminal `canceled`;
- a cancellation raised during a correction/image checkpoint marks only that item canceled;
- `generation_progress` events carry the correct item index, item ID when available, and subquestion metadata when supplied;
- `_persist_generation_record()` receives the question payload without `_generation` metadata.

- [ ] **Step 2: Run the focused service tests and verify they fail**

Run:

```bash
uv run pytest tests/server/test_generation_progress_service.py -q
```

Expected: FAIL because the service emits no explicit progress/terminal protocol and result data has no `_generation` metadata.

- [ ] **Step 3: Add service helpers for progress and compatible result payloads**

In `server/generate/service.py`, import `GenerationCancelled` and `GenerationRun`. Add helpers with exact behavior:

```python
def _result_event_payload(
    question: MathExamQuestion | SSExamQuestion | NSExamQuestion,
    config: ServerConfig,
    index: int,
) -> dict[str, Any]:
    payload = _question_to_event(question, config)
    payload["_generation"] = {
        "index": index,
        "item_id": question.id,
    }
    return payload


def _progress_event(run: GenerationRun, **kwargs: Any) -> dict[str, Any]:
    return {"event": "generation_progress", "data": run.snapshot(**kwargs)}


def _strip_generation_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "_generation"}
```

Update `_persist_generation_record()` call sites to pass a payload stripped of `_generation`; do not write transport metadata to `question_json`.

- [ ] **Step 4: Register worker state and map stage events**

At the beginning of `generate_question_stream()`:

1. create a fallback `GenerationRun` only for direct service callers when `run is None`, using `generation_log_id or uuid.uuid4()` and `user_id or uuid.UUID(int=0)`;
2. yield `started` with `{"run_id": str(run.run_id), "total": run.total}`;
3. emit an initial progress snapshot.

In each `worker_one(i, ...)`:

```python
run.start_item(i)
loop.call_soon_threadsafe(
    queue.put_nowait,
    _progress_event(run, item_index=i),
)
```

Wrap the worker’s observer so `stage` events are still forwarded to the existing queue observer and also map `llm_generate → generating`, `render_image → rendering`, `verify → verifying`, and `correct → correcting` for this worker’s index. Pass `run.is_cancel_requested` as `should_cancel` to all three subject `generate_with_corrections()` calls.

Before sampling, before starting `generate_with_corrections()`, and before emitting a result, call `raise_if_cancelled(run.is_cancel_requested)`. Catch `GenerationCancelled` separately, call `run.cancel_item(i)`, emit a progress snapshot with `item_status="canceled"`, and do not emit a result. Catch other exceptions with `run.fail_item(i, message)` and emit a progress snapshot containing the item error; do not terminate the whole stream for a single item failure.

- [ ] **Step 5: Fix result ordering and terminal stream lifecycle**

When a worker succeeds, enqueue the result payload with `_generation` metadata and then enqueue its completed progress snapshot. This preserves the result payload’s existing top-level question fields while giving the frontend the original index.

Replace the current “break on `error`” loop with a loop that drains until `generation_terminal` and then `done`. The signal task must:

1. await all worker futures with `return_exceptions=True`;
2. call `run.cancel_pending_items()` if cancellation was requested;
3. choose terminal status: `canceled` if cancellation was requested, otherwise `failed` if any item failed, otherwise `completed`;
4. call `run.terminal(status)`;
5. enqueue `generation_terminal` with final counts, then `done`.

Keep `pipeline_start/end` events for existing diagnostics, but make the new generation events the stable progress contract.

- [ ] **Step 6: Run service and regression tests**

Run:

```bash
uv run pytest tests/server/test_generation_progress_service.py tests/server/test_generate_routes.py tests/server/test_generate_service_coverage.py tests/server/test_ss_creative_planning_service.py -q
```

Expected: PASS, including existing assertions that result data contains `題目`, `正確解題分析`, and image data at the top level.

- [ ] **Step 7: Commit service progress events**

```bash
git add server/generate/service.py tests/server/test_generation_progress_service.py
git commit -m "feat: emit question-scoped generation progress"
```

---

## Task 4: Add authenticated cancellation endpoint and generation-log status

**Files:**
- Modify: `server/generate/routes.py`
- Modify: `server/models.py`
- Modify: `server/app.py`
- Create: `alembic/versions/9f5e1a2c3d4b_add_canceled_generation_status.py`
- Create: `tests/server/test_generate_cancel.py`

**Interfaces:**
- Adds `POST /api/generate/runs/{run_id}/cancel`.
- Returns HTTP 200 with `{"run_id": str, "status": "cancel_requested" | "started" | "completed" | "failed" | "canceled"}`.
- Returns 404 for a nonexistent or another user’s generation log.
- Repeated requests for a terminal run return its terminal status without changing it.

- [ ] **Step 1: Write failing endpoint and status tests**

Use the same in-memory SQLite/auth fixtures already present in `tests/server/test_generate_routes.py`. Add tests that:

```python
def test_cancel_generation_requires_owner_and_is_idempotent() -> None:
    # owner receives 200 and cancel_requested for an active registered run
    # another user receives 404
    # after run.terminal("canceled"), a second owner request returns 200/canceled
    assert owner_response.status_code == 200
    assert owner_response.json()["status"] == "cancel_requested"
    assert other_response.status_code == 404
    assert terminal_response.status_code == 200
    assert terminal_response.json()["status"] == "canceled"
```

Also test that the route passes the same `GenerationRun` instance into `generate_question_stream()` and that a `generation_terminal(status="canceled")` event updates `GenerationLog.status` to `canceled` in the route’s `finally` block.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
uv run pytest tests/server/test_generate_cancel.py -q
```

Expected: FAIL because `canceled` is not a valid model status, the registry is not initialized, and the endpoint does not exist.

- [ ] **Step 3: Add the canceled status and migration**

Change `server/models.py`:

```python
GenerationStatus = Enum(
    "started", "completed", "failed", "canceled", name="generation_status"
)
```

Create the Alembic migration with revision `9f5e1a2c3d4b`, down revision `c2dae7035ea7`:

```python
def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE generation_status ADD VALUE IF NOT EXISTS 'canceled'"
        )


def downgrade() -> None:
    # PostgreSQL enum values cannot be safely removed in-place; leave the value
    # in the type and rely on the model downgrade for new writes.
    pass
```

- [ ] **Step 4: Initialize the registry and wire run creation**

In `server/app.py`, import `GenerationRunRegistry` and initialize it in `create_app()` before routers serve requests:

```python
app.state.generation_runs = GenerationRunRegistry()
```

In `generate_endpoint()`, after committing and refreshing the `GenerationLog`, register:

```python
run = request.app.state.generation_runs.register(
    log.id, user.id, params.count
)
```

Pass `run=run` into `generate_question_stream()`. In `event_generator()`, set the local terminal status from `generation_terminal.data.status`, preserve `failed` for run-level errors, and update the existing `GenerationLog` row in `finally`. Remove the registry entry only after the database status update completes.

- [ ] **Step 5: Implement the cancellation endpoint**

Add this route in `server/generate/routes.py`:

```python
@router.post("/generate/runs/{run_id}/cancel", status_code=200)
async def cancel_generation(
    run_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str]:
    log = (
        await session.execute(
            select(GenerationLog).where(
                GenerationLog.id == run_id,
                GenerationLog.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if log is None:
        raise HTTPException(status_code=404, detail="generation run not found")
    if log.status != "started":
        return {"run_id": str(run_id), "status": str(log.status)}
    run = request.app.state.generation_runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=409, detail="generation run is no longer active")
    run.request_cancel()
    return {"run_id": str(run_id), "status": "cancel_requested"}
```

Use the project’s existing auth dependency and existence-hiding behavior. Do not accept a user ID in the request body.

- [ ] **Step 6: Run route, migration, and service tests**

Run:

```bash
uv run pytest tests/server/test_generate_cancel.py tests/server/test_generate_routes.py tests/server/test_generation_progress_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit cancellation API**

```bash
git add server/generate/routes.py server/models.py server/app.py alembic/versions/9f5e1a2c3d4b_add_canceled_generation_status.py tests/server/test_generate_cancel.py
git commit -m "feat: add generation cancellation endpoint"
```

---

## Task 5: Normalize progress and cancellation in `useGenerate`

**Files:**
- Modify: `web/src/hooks/useGenerate.ts`
- Modify: `web/src/hooks/useGenerate.test.ts`

**Interfaces:**
- Adds `GenerationItemStatus`, `GenerationItemProgress`, and `GenerationProgress` exports; the existing `GenerateStatus` union is extended with `canceling`, `completed`, and `canceled`.
- Extends `UseGenerateReturn` with `progress`, `progressDismissed`, `cancelGeneration`, and `dismissProgress`.
- `cancelGeneration(): Promise<void>` posts to `/api/generate/runs/{run_id}/cancel` and does not abort the SSE stream.

- [ ] **Step 1: Write failing hook tests with mocked SSE**

Mock `@microsoft/fetch-event-source` and capture its options:

```ts
const fetchEventSourceMock = vi.hoisted(() => vi.fn());
vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));
```

Add tests using `renderHook` that call `generate()` and then invoke the captured `onmessage` callback with:

1. `started` containing `run_id` and `total`;
2. `generation_progress` for item 1 and item 0 in reverse order;
3. `result` with top-level question fields and `_generation.index`;
4. `generation_terminal` with `status: "completed"`;
5. `done`.

Assert that the final status is `completed`, the original item index is used for `displayResults`, and `done` does not change the terminal status. Add tests that mismatched `run_id` progress is ignored and that `cancelGeneration()` calls:

```text
POST /api/generate/runs/{run_id}/cancel
```

with the auth header and transitions to `canceling` only after a successful response.

- [ ] **Step 2: Run the focused hook tests and verify they fail**

Run:

```bash
cd web && npm test -- --run src/hooks/useGenerate.test.ts
```

Expected: FAIL because the new progress types/state/event cases do not exist.

- [ ] **Step 3: Add progress types and hook state**

In `useGenerate.ts`, define:

```ts
export type GenerateStatus =
  | "idle" | "queued" | "generating" | "canceling"
  | "completed" | "canceled" | "error";

export type GenerationItemStatus =
  | "pending" | "generating" | "rendering" | "verifying"
  | "correcting" | "completed" | "failed" | "canceled";

export interface GenerationItemProgress {
  index: number;
  status: GenerationItemStatus;
  itemId?: string | null;
  latestMessage?: string | null;
  errorMessage?: string | null;
  subquestionsCompleted?: number | null;
  subquestionsTotal?: number | null;
}

export interface GenerationProgress {
  runId: string | null;
  total: number;
  completed: number;
  failed: number;
  active: number;
  pending: number;
  canceled: number;
  currentStage: string;
  stageLabel: string;
  itemIndex?: number | null;
  itemId?: string | null;
  itemStatus?: GenerationItemStatus | null;
  subquestionsCompleted?: number | null;
  subquestionsTotal?: number | null;
  terminal: boolean;
  items: GenerationItemProgress[];
}
```

Add state for `progress`, `progressDismissed`, and the active run ID. Initialize a client-side pending snapshot with `runId: null` and `currentStage: "waiting_to_start"` as soon as `generate()` starts so the bar appears immediately after Confirm.

- [ ] **Step 4: Handle new SSE events and terminal semantics**

Add `onmessage` cases:

- `started`: parse run ID/total, update the snapshot, set status `generating`;
- `generation_progress`: parse, ignore if run ID differs from the active run, merge counts and the indexed item row;
- `generation_cancel_requested`: set status `canceling`;
- `generation_terminal`: set status from its `status`, set `terminal: true`, and merge final counts;
- `result`: parse `_generation.index`/`item_id`, remove `_generation` before storing/displaying the question, and fall back to arrival order only when metadata is absent;
- `done`: abort and clear the controller, but do not set status to `idle` when a terminal event was received; if no terminal event exists, set an explicit error message rather than claiming success.

Keep `question_update` behavior unchanged except for filtering by active run if the server adds run metadata.

- [ ] **Step 5: Implement cancellation and dismissal**

Add:

```ts
const cancelGeneration = useCallback(async (): Promise<void> => {
  const runId = activeRunIdRef.current;
  if (!runId) return;
  const token = useAuthStore.getState().token;
  const response = await fetch(`/api/generate/runs/${runId}/cancel`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    throw new Error(`Cancel request failed: HTTP ${response.status}`);
  }
  setStatus("canceling");
}, []);
```

`dismissProgress()` sets `progressDismissed=true` without clearing results. `generate()` resets dismissal to false. `reset()` clears progress, dismissal, terminal state, and results as it does today.

- [ ] **Step 6: Run hook tests and the frontend build**

Run:

```bash
cd web && npm test -- --run src/hooks/useGenerate.test.ts
npm run build
```

Expected: PASS and a successful TypeScript/Vite build.

- [ ] **Step 7: Commit hook state**

```bash
git add web/src/hooks/useGenerate.ts web/src/hooks/useGenerate.test.ts
git commit -m "feat: normalize generation progress in web hook"
```

---

## Task 6: Build the accessible sticky bar, details panel, and cancel modal

**Files:**
- Create: `web/src/components/CancelGenerationModal.tsx`
- Create: `web/src/components/CancelGenerationModal.test.tsx`
- Create: `web/src/components/GenerationProgressBar.tsx`
- Create: `web/src/components/GenerationProgressBar.test.tsx`
- Modify: `web/src/components/ProgressLog.tsx`
- Modify: `web/src/i18n/messages.ts`

**Interfaces:**
- `CancelGenerationModal` accepts `{ open: boolean; onConfirm: () => void | Promise<void>; onClose: () => void; busy?: boolean }`.
- `GenerationProgressBar` accepts `{ progress: GenerationProgress; status: GenerateStatus; errorMessage: string | null; onCancel: () => Promise<void>; onDismiss: () => void; details?: ReactNode }`.

- [ ] **Step 1: Write failing component tests**

Test the modal:

```tsx
it("requires explicit confirmation and supports Escape", async () => {
  const onConfirm = vi.fn();
  const onClose = vi.fn();
  render(<CancelGenerationModal open onConfirm={onConfirm} onClose={onClose} />);
  expect(screen.getByRole("dialog")).toHaveTextContent(/completed items will be kept/i);
  await userEvent.click(screen.getByRole("button", { name: /continue/i }));
  expect(onClose).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: /cancel generation/i }));
  expect(onConfirm).toHaveBeenCalled();
});
```

Test the bar for:

- compact active rendering with stage and `2 of 5` count;
- no percentage text;
- `aria-live="polite"` and labeled Details/Cancel buttons;
- expanded per-item rows and passed `details` content;
- cancel modal opening and confirm callback;
- cancel button disabled while `status === "canceling"`;
- completed/failed/canceled terminal copy and dismiss control.

- [ ] **Step 2: Run the focused component tests and verify they fail**

Run:

```bash
cd web && npm test -- --run src/components/CancelGenerationModal.test.tsx src/components/GenerationProgressBar.test.tsx
```

Expected: FAIL because the components and translation keys do not exist.

- [ ] **Step 3: Add English and zh-TW translation keys**

In both locale objects in `web/src/i18n/messages.ts`, add keys with these meanings:

```text
progress.bar_details
progress.bar_hide_details
progress.bar_cancel
progress.bar_canceling
progress.bar_dismiss
progress.bar_completed_count
progress.bar_failed_count
progress.bar_canceled_count
progress.bar_connection_interrupted
progress.bar_cancel_failed
progress.stage.generating_questions
progress.stage.rendering_images
progress.stage.verifying_answers
progress.stage.fixing_answer_issues
progress.stage.waiting_to_start
progress.stage.finalizing
progress.item.pending
progress.item.generating
progress.item.rendering
progress.item.verifying
progress.item.correcting
progress.item.completed
progress.item.failed
progress.item.canceled
cancel_generation.title
cancel_generation.body
cancel_generation.continue
cancel_generation.confirm
```

Use concise English strings in `en-US` and natural zh-TW equivalents in `zh-TW`; do not render raw event keys to visitors.

- [ ] **Step 4: Implement the modal**

Create `CancelGenerationModal.tsx` with a fixed `inset-0` overlay, `role="dialog"`, `aria-modal="true"`, heading, body, Continue, and Cancel Generation buttons. Use a ref to focus the first action on open, listen for Escape to call `onClose`, and set `aria-busy`/disable both actions while `busy` is true. Use `z-[60]` so it layers above the sticky bar and feedback button.

- [ ] **Step 5: Implement the sticky bar**

Create `GenerationProgressBar.tsx` with:

- `fixed inset-x-0 bottom-0 z-40 border-t bg-white shadow-lg` container;
- inner `mx-auto max-w-5xl` content wrapper;
- `role="status" aria-live="polite"` compact row;
- spinner only for active states, status icon/text for terminal states;
- current stage translated from `progress.currentStage`, falling back to `progress.stageLabel`;
- count text based on `completed`, `failed`, `canceled`, and `total`;
- Expand/Hide Details button with `aria-expanded`;
- Cancel button that opens the modal, calls `onCancel` after confirmation, and displays `Canceling…` while pending;
- Dismiss button only for terminal states;
- expanded panel with one row per `progress.items`, text status, optional error, optional subquestion count, and the `details` React node.

Do not add a `<progress>` element or percentage because the protocol intentionally does not provide an exact ratio.

- [ ] **Step 6: Make `ProgressLog` safe inside details**

Change the early return in `ProgressLog.tsx` to return `null` when `lines.length === 0`, `llmCalls.length === 0`, and there is no error message, regardless of the active status. This removes the empty fixed-height black panel while preserving actual trace/error content. Keep existing event grouping and trace controls unchanged.

- [ ] **Step 7: Run component tests and lint**

Run:

```bash
cd web && npm test -- --run src/components/CancelGenerationModal.test.tsx src/components/GenerationProgressBar.test.tsx
npm run lint
```

Expected: PASS with no ESLint errors.

- [ ] **Step 8: Commit the UI components**

```bash
git add web/src/components/CancelGenerationModal.tsx web/src/components/CancelGenerationModal.test.tsx web/src/components/GenerationProgressBar.tsx web/src/components/GenerationProgressBar.test.tsx web/src/components/ProgressLog.tsx web/src/i18n/messages.ts
git commit -m "feat: add sticky generation progress bar"
```

---

## Task 7: Integrate the bar into `GeneratePage`

**Files:**
- Modify: `web/src/pages/GeneratePage.tsx`
- Create: `web/src/pages/GeneratePage.test.tsx`

**Interfaces:**
- Consumes `useGenerate()` fields from Task 5 and `GenerationProgressBar` from Task 6.
- Keeps existing `QuestionCard` display/results/download behavior unchanged.

- [ ] **Step 1: Write the page wiring test**

Mock `useGenerate`, `ParamForm`, `AgentStatusPanel`, `ProgressLog`, and `QuestionCard`. Return an active `GenerationProgress` with `runId: "run-1"`, `total: 2`, and one active item. Assert that `GenerationProgressBar`-visible text appears, its cancel control is present, and the page passes the hook’s `cancelGeneration` callback through. Add a terminal-state case asserting the dismiss control is rendered without removing the question card.

- [ ] **Step 2: Run the page test and verify it fails**

Run:

```bash
cd web && npm test -- --run src/pages/GeneratePage.test.tsx
```

Expected: FAIL because `GeneratePage` does not consume or render the new progress state.

- [ ] **Step 3: Wire hook state and actions into the page**

Extend the hook destructuring at `GeneratePage.tsx:37` with:

```ts
const {
  status, jobsAhead, progressLines, results, displayResults, llmCalls,
  agentLanes, errorMessage, progress, progressDismissed,
  cancelGeneration, dismissProgress, generate, reset,
} = useGenerate();
```

Build a `details` node containing the existing `AgentStatusPanel` when lanes exist and `ProgressLog` when trace/error content exists. Map terminal hook statuses to the existing `ProgressLog` status prop (`queued`, `generating`, `error`, or `idle`) so the legacy component remains type-safe.

- [ ] **Step 4: Mount the fixed bar and reserve bottom space**

Remove the standalone agent/progress sections from the normal document flow. Add:

```tsx
{progress && !progressDismissed && (
  <GenerationProgressBar
    progress={progress}
    status={status}
    errorMessage={errorMessage}
    onCancel={cancelGeneration}
    onDismiss={dismissProgress}
    details={details}
  />
)}
```

Apply conditional bottom padding to `<main>` while the bar is visible, for example:

```tsx
<main className={`mx-auto max-w-5xl space-y-6 px-3 py-4 sm:px-4 sm:py-6 ${
  progress && !progressDismissed ? "pb-36" : ""
}`}>
```

Keep `ParamForm` disabled for `generating`, `queued`, and `canceling`. Keep completed display results and downloads available after canceled/failed terminal states.

- [ ] **Step 5: Run page tests and full frontend checks**

Run:

```bash
cd web && npm test -- --run src/pages/GeneratePage.test.tsx src/components/GenerationProgressBar.test.tsx src/hooks/useGenerate.test.ts
npm run lint
npm run build
```

Expected: PASS, no lint errors, and a successful production build.

- [ ] **Step 6: Commit page integration**

```bash
git add web/src/pages/GeneratePage.tsx web/src/pages/GeneratePage.test.tsx
git commit -m "feat: integrate generation progress overlay"
```

---

## Task 8: Update flow documentation and SSE smoke checks

**Files:**
- Modify: `FLOW.md`
- Modify: `scripts/smoke_test_phase2.sh`

**Interfaces:**
- Documents the same `run_id`, event names, statuses, and cancel endpoint implemented in Tasks 3–4.
- Keeps result-payload validation based on top-level `題目`, `正確解題分析`, and `image_base64` fields.

- [ ] **Step 1: Write documentation/smoke assertions first**

Update the smoke script’s basic stream section to require at least one `generation_progress` event and one `generation_terminal` event, and parse terminal JSON to assert `status == "completed"` for the successful request. Remove only the obsolete requirement that a legacy `progress` event exists; do not remove result/done checks.

In `FLOW.md`, add the Confirm step between confirmation rendering and `useGenerate.generate()`, then document:

```text
started(run_id,total)
  -> generation_progress(item counts/stage)
  -> question_update/result with original item metadata
  -> generation_terminal(status/counts)
  -> done (transport close)
```

Document `POST /api/generate/runs/{run_id}/cancel`, modal confirmation, cooperative checkpoints, and preservation of completed results.

- [ ] **Step 2: Run shell syntax and documentation checks**

Run:

```bash
bash -n scripts/smoke_test_phase2.sh
rg -n "generation_progress|generation_terminal|generate/runs/.*/cancel|Confirm" FLOW.md scripts/smoke_test_phase2.sh
```

Expected: shell syntax succeeds and all four documented concepts are present.

- [ ] **Step 3: Commit documentation and smoke updates**

```bash
git add FLOW.md scripts/smoke_test_phase2.sh
git commit -m "docs: document generation progress lifecycle"
```

---

## Task 9: Run the complete verification suite

**Files:**
- No new files; verify all files from Tasks 1–8.

- [ ] **Step 1: Run all backend tests**

```bash
uv run pytest -q
```

Expected: PASS. The result compatibility assertions from Tasks 3 and 8 must remain green: question fields stay at the top level and `_generation` is transport-only.

- [ ] **Step 2: Run all frontend tests, lint, and build**

```bash
cd web && npm test -- --run
npm run lint
npm run build
```

Expected: all Vitest tests pass, ESLint reports no errors, and TypeScript/Vite compilation succeeds.

- [ ] **Step 3: Run focused migration and SSE checks**

```bash
cd /workspace/exam-generation
uv run alembic upgrade head
bash -n scripts/smoke_test_phase2.sh
```

Expected: Alembic reaches the new head and the smoke script passes syntax validation.

- [ ] **Step 4: Inspect the final diff for protocol consistency**

```bash
git diff main...HEAD --check
git status --short
git log --oneline -8
```

Confirm that:

- backend and frontend use the same event names and status strings;
- every new progress/cancellation/terminal event carries the same `run_id` format;
- `done` does not claim success;
- result payloads still expose question fields at the top level;
- cancellation preserves completed display results;
- the sticky overlay reserves bottom space and the modal is above it.

All task commits remain independently reviewable; do not squash them during verification.
