# Aborted History Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record user-ended SSE runs as explicit `aborted` History tombstones and render them as a localized, distinct `中斷` state with request parameters but no question artifact.

**Architecture:** Keep the existing generation-record tombstone model and History API. The generate route classifies cancellation separately from the existing captured-error path, persists at most one `aborted` tombstone, and leaves captured errors as `failed`; the History API returns an explicit status plus the stable preview token `aborted`, while the web History components localize the status and explanation.

**Tech Stack:** Python 3, FastAPI, SSE-Starlette, SQLAlchemy async sessions, pytest, React, TypeScript, Vitest, Testing Library, existing i18n store.

**Spec:** Issue #409 brief supplied in the task request; no separate design document is required.

## Global Constraints

- Work directly on branch `feat/409-aborted-history-runs`; do not commit.
- Do not infer `aborted` from a missing error message; use the explicit stream-teardown path and persisted record status.
- A client disconnect before a terminal event writes exactly one `generation_records.status = 'aborted'` row with `question_json = null` and `error = null`.
- A captured generation error remains `generation_records.status = 'failed'` and keeps its error message; it must not also create an aborted row.
- History detail always exposes saved request parameters for tombstones and never exposes question content or a download action for non-completed records.
- Use the domain terms `中斷紀錄`, `中斷`, and `失敗` in the Traditional Chinese UI; keep the failed and aborted visuals/copy distinct.
- Every behavior follows red → green: write one public-seam test, run it and observe the expected failure, implement the smallest fix, rerun the test, then continue.

---

### Task 1: Classify SSE teardown and persist an aborted tombstone

**Files:**
- Create: `tests/server/test_generate_teardown.py`
- Modify: `server/generate/persistence.py`
- Modify: `server/generate/routes.py`

**Interfaces:**
- Consumes: the existing `GET /api/generate` SSE endpoint, `AsyncSessionLocal` injection, and `GenerationRecord` model.
- Produces: `persist_aborted_generation_record(...)` with the same best-effort write contract as the existing failed-tombstone helper; cancelled event generators persist one aborted row and re-raise cancellation, while captured error events/exceptions persist one failed row and do not produce an aborted row.

- [ ] **Step 1: Write one failing public-seam test.**

  Add an ASGI-level test that drives the real FastAPI route with an injected async stream. The fake stream yields `started` and then waits; the test `send` callback releases an `http.disconnect` message after the first body chunk. Query the test database after the app returns and assert the literal row contract:

  ```python
  assert [row.status for row in rows] == ["aborted"]
  assert rows[0].error is None
  assert rows[0].question_json is None
  assert rows[0].params_json["subject"] == "math"
  ```

  In the same test seam, exercise a stream that raises `RuntimeError` and assert the independent literal contract:

  ```python
  assert [row.status for row in error_rows] == ["failed"]
  assert error_rows[0].error == "Stream error (RuntimeError)"
  assert all(row.status != "aborted" for row in error_rows)
  ```

  Use a real in-memory async database and the public ASGI call rather than invoking a private route helper.

- [ ] **Step 2: Run the test and verify the failure is the missing aborted behavior.**

  Run:

  ```bash
  uv run pytest tests/server/test_generate_teardown.py -q
  ```

  Expected: the disconnect case fails because the existing route completes its `finally` bookkeeping without inserting an `aborted` generation record; the captured-error assertions identify the existing failed behavior and must remain intact.

- [ ] **Step 3: Write the minimal persistence implementation.**

  Add `persist_aborted_generation_record` beside `persist_failed_generation_record`. Construct `GenerationRecord` with the supplied user/log/subject/params, `question_id=""`, `question_json=None`, `image_files=[]`, `status="aborted"`, and no error. Commit through the injected session factory and log-and-swallow database failures exactly as the existing tombstone helper does.

- [ ] **Step 4: Write the minimal route classification.**

  Import `asyncio` and the new persistence helper. In `event_generator`, catch `asyncio.CancelledError` before the broad exception handler. If no captured error has already set `status = "failed"`, persist the aborted tombstone once, leave `error_msg` as `None`, and set the run bookkeeping to its existing non-error terminal value; then re-raise cancellation so SSE-Starlette stops sending. Keep the current `event["event"] == "error"` and outer `Exception` branches unchanged except for sharing the existing once-only failed guard. Do not add aborted status inference to History or to the model's missing-error case.

- [ ] **Step 5: Run the focused test and verify it passes.**

  Run:

  ```bash
  uv run pytest tests/server/test_generate_teardown.py -q
  ```

  Expected: both the disconnect and captured-error scenarios pass, with exactly one tombstone in each scenario.

---

### Task 2: Expose aborted History payloads at the API seam

**Files:**
- Modify: `tests/server/test_history_routes.py`
- Modify: `server/history/routes.py`

**Interfaces:**
- Consumes: `GenerationRecord.status`, `error`, `params_json`, and `question_json`.
- Produces: list payloads with `status="aborted"`, `error=null`, and `preview="aborted"`; detail payloads with readable `params_json`, `question_json=null`; download endpoint returns 404 for the aborted record.

- [ ] **Step 1: Write one failing list/detail API test.**

  Add a real database fixture row with `status="aborted"`, `error=None`, `question_json=None`, and hand-written params such as `{"subject": "social_studies", "topic": "climate"}`. Through `/api/history` assert:

  ```python
  assert item["status"] == "aborted"
  assert item["preview"] == "aborted"
  assert item["error"] is None
  assert item["verified"] is False
  ```

  Through `/api/history/{id}` assert the same status, the exact params object, and `question_json is None`; through `/download` assert HTTP 404. These assertions must use the literal API contract, not a helper that derives expected output from the route implementation.

- [ ] **Step 2: Run the API test and verify the failure.**

  Run:

  ```bash
  uv run pytest tests/server/test_history_routes.py -q -k aborted
  ```

  Expected: the status/detail/download portions use existing explicit-status behavior, while the list assertion fails because the preview is currently empty for an aborted row.

- [ ] **Step 3: Implement the minimal API preview change.**

  Extend the preview boundary to accept the explicit record status and return the stable string `"aborted"` only when `status == "aborted"`. Keep failed previews sourced from their captured error and completed previews sourced from question content. Pass the row's explicit status from `list_history`; do not use `error is None` as a classifier.

- [ ] **Step 4: Run the API test and verify it passes.**

  Run:

  ```bash
  uv run pytest tests/server/test_history_routes.py -q -k aborted
  ```

  Expected: the aborted list/detail/download contract passes.

---

### Task 3: Render distinct aborted and failed History states

**Files:**
- Modify: `web/src/pages/HistoryPage.test.tsx`
- Modify: `web/src/pages/HistoryPage.tsx`
- Modify: `web/src/pages/HistoryDetail.test.tsx`
- Modify: `web/src/pages/HistoryDetail.tsx`
- Modify: `web/src/i18n/messages.ts`

**Interfaces:**
- Consumes: `HistoryListItem.status`, `HistoryListItem.preview`, `HistoryDetail.status`, `HistoryDetail.params_json`, and `HistoryDetail.question_json` from `web/src/api/client.ts`.
- Produces: a distinct aborted badge (`中斷` in zh-TW, localized equivalent in en-US), an aborted preview note, a detail explanation that the user ended the run, readable params, no `QuestionCard`, and no download button; failed rows keep their red `失敗` badge/error behavior.

- [ ] **Step 1: Write one failing list-render test.**

  Extend the existing `HistoryPage` test fixture with one failed and one aborted item. Assert the literal English test-locale labels `Failed` and `Aborted` are both present, that the aborted row displays `aborted`, and that the two badges have different rendered class names so the visual distinction cannot regress to a shared style.

- [ ] **Step 2: Run the focused list test and verify it fails.**

  Run:

  ```bash
  cd /workspace/exam-generation/web && npx vitest run src/pages/HistoryPage.test.tsx -t "aborted"
  ```

  Expected: the current list has no aborted badge branch and does not render the required distinct label/style.

- [ ] **Step 3: Implement the minimal list and copy changes.**

  Add `history.aborted_badge` and `history.aborted_preview` translations. Render `status === "aborted"` with an amber/yellow badge class distinct from the failed red class, show the API preview token through the localized aborted preview copy, and keep failed rows using their error/preview. Correct the failed detail title copy if necessary so `失敗` and `中斷紀錄` are not conflated.

- [ ] **Step 4: Run the focused list test and verify it passes.**

  Run:

  ```bash
  cd /workspace/exam-generation/web && npx vitest run src/pages/HistoryPage.test.tsx -t "aborted"
  ```

  Expected: the aborted and failed badges are both rendered with distinct copy and classes.

- [ ] **Step 5: Write one failing detail-render test.**

  Add an aborted `HistoryDetail` fixture with `error: null`, `params_json` containing a visible topic, and `question_json: null`. Assert the localized aborted explanation, the serialized topic, no `QuestionCard`, and no download button. The expected explanation must be user-facing copy, not the absence of an error field.

- [ ] **Step 6: Run the focused detail test and verify it fails.**

  Run:

  ```bash
  cd /workspace/exam-generation/web && npx vitest run src/pages/HistoryDetail.test.tsx -t "aborted"
  ```

  Expected: the current component enters its combined interrupted branch and displays the generic missing-error message instead of the user-ended explanation.

- [ ] **Step 7: Implement the minimal detail branch.**

  Add `history.aborted_detail_title` and `history.aborted_explanation` translations. Split `failed` and `aborted` rendering enough to show the aborted explanation without reading `detail.error`; retain readable params and the existing non-completed download suppression. Keep completed details on the existing `QuestionCard` path.

- [ ] **Step 8: Run the focused detail test and verify it passes.**

  Run:

  ```bash
  cd /workspace/exam-generation/web && npx vitest run src/pages/HistoryDetail.test.tsx -t "aborted"
  ```

  Expected: the aborted detail contract passes with no content or download control.

---

### Task 4: Full requested verification

**Files:**
- Read-only verification of all files above.

- [ ] **Step 1: Run the written backend tests plus existing history-related tests.**

  Run:

  ```bash
  uv run pytest tests/server/test_generate_teardown.py tests/server/test_generate_routes.py tests/server/test_history_routes.py tests/server/test_history_write.py tests/server/test_persistence.py tests/server/test_history_retention.py tests/server/test_generation_records_migration.py tests/server/test_generation_record_annotations.py -q
  ```

- [ ] **Step 2: Run the written frontend tests plus existing history-related tests.**

  Run:

  ```bash
  cd /workspace/exam-generation/web && npx vitest run src/pages/HistoryPage.test.tsx src/pages/HistoryDetail.test.tsx src/pages/HistoryDetail.annotation.test.tsx src/api/history.test.ts
  ```

- [ ] **Step 3: Inspect the final diff and report exact results.**

  Run `git status --short` and `git diff --check`; report every created/modified file and copy the exact pass/fail summaries from both test commands. Do not commit.
