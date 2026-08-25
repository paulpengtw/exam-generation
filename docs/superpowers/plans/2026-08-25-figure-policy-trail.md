# Figure-Policy Trail Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the 社會領域 圖像種類 policy story incrementally so completed and interrupted History records expose effective kinds, collisions, repair attempts, and duplicate-image warnings.

**Architecture:** Define a typed `figure_policy` event union parallel to `verification_trail`. Social-studies policy enforcement emits spec observations, collision detections, repair outcomes, and final warnings through a callback. The server captures those events for SSE, commits an aggregate staging list on the existing `GenerationLog` after every callback, and copies the list into the nullable `GenerationRecord.figure_policy_trail_json` on completion, failure, or shielded abort. History detail exposes the sibling field and mounts a compact policy timeline without changing downloaded question JSON.

**Tech Stack:** Python 3.11, Pydantic, SQLAlchemy async ORM, Alembic, FastAPI, pytest, React, TypeScript, Vitest, Testing Library.

**Spec:** `docs/adr/0015-figure-kind-diversity-is-a-layered-guarantee.md`, `docs/adr/0016-verification-trail-is-persisted-first-class.md`, and GitHub issue #550.

## Global Constraints

- Use the ADR 0015 layered guarantee: declaration, normalization, collision detection, one repair budget, degrade-never-block.
- Use `figure_policy` as the event code and a discriminated `kind` union; retain effective `圖像種類` as a JSON value, including the empty string for an explicitly visual spec with no comparable kind.
- `figure_policy_trail_json` is a nullable JSON sibling of `question_json` and `verification_trail_json`; it is exposed only by History detail and never nested in downloaded question JSON.
- Every callback event is committed to the `GenerationLog` staging column before the callback returns; a completion/failed/aborted `GenerationRecord` receives the captured prefix.
- Runs without visual specs persist `null`/empty and render no policy section; no visual-policy SSE noise is emitted.
- Use zh-TW labels and domain vocabulary: 題幹, 小題, 圖像種類, 碰撞, 修補嘗試, duplicate image shipped warning.
- Do not run `uv run pytest` for the entire repository; run affected files plus `tests/server/`. If web files change, run `cd web && npm test` and `npx tsc -b`.
- For each acceptance criterion: write a genuinely failing test, run it, commit `test: red — <behavior> (#550)`, implement minimally, rerun, commit `feat: <behavior> (#550)`, then push that commit to `origin`.

---

### Task 1: Completed trail schema, capture, History API, and completed History detail

**Files:**
- Create: `src/common/figure_policy_trail.py`
- Create: `tests/test_figure_policy_trail.py`
- Create: `tests/server/test_figure_policy_trail_persistence.py`
- Modify: `src/common/subject_spec.py`, `src/common/generation_core.py`
- Modify: `src/social_studies/cli.py`, `server/generate/subjects.py`, `server/generate/service.py`
- Modify: `server/models.py`, `server/generate/persistence.py`, `server/history/routes.py`
- Modify: `web/src/api/client.ts`, `web/src/hooks/useGenerate.ts`, `web/src/components/QuestionCard.tsx`, `web/src/pages/HistoryDetail.tsx`
- Create: `web/src/components/FigurePolicyTrailTimeline.tsx`
- Modify: `web/src/pages/HistoryDetail.test.tsx`

**Interfaces:**
- `FigurePolicyTrailEvent` is the Pydantic union of `spec`, `collision`, `repair`, and `warning` entries with `code: "figure_policy"`, `question_id`, timestamps, and JSON-safe fields.
- Social generation accepts `on_figure_policy_entry: Callable[[FigurePolicyTrailEvent], None] | None` and emits the effective `圖像種類` for 題幹 and every visual 小題, each detected collision pair, each one-shot repair result, and final duplicate-image warnings.
- `GenerationRecord.figure_policy_trail_json: Mapped[list | None]` and `persist_generation_record(..., figure_policy_trail_json=...)` mirror the verification trail.
- History detail returns `figure_policy_trail`; list and download payloads remain unchanged.
- `FigurePolicyTrailTimeline` accepts `FigurePolicyTrailEntry[] | null` and renders spec/collision/repair/warning entries; the initial implementation may render an empty section, which Task 3 tightens to no noise.

- [ ] **Step 1: Write failing completed-run and History-detail tests.** Assert a social policy callback produces spec/collision/repair/warning event shapes, a completed persistence seam stores the exact list, `/api/history/{id}` returns it, and `HistoryDetail` passes it to the rendered card.
- [ ] **Step 2: Run the focused tests and verify red.**

  ```bash
  uv run pytest tests/test_figure_policy_trail.py tests/server/test_figure_policy_trail_persistence.py tests/server/test_history_routes.py -q
  cd web && npx vitest run src/pages/HistoryDetail.test.tsx
  ```

  Expected: failure from missing trail callback/models/API field/History prop, not a test typo.
- [ ] **Step 3: Add the typed event union and social callback emission.** Keep `find_figure_kind_collisions` as the sole collision detector; emit policy events around the existing repair calls without changing the one-repair/degrade-never-block behavior.
- [ ] **Step 4: Add the nullable record field, completed persistence argument, internal worker capture, and History detail response.** Keep trail data out of `question_to_event` and downloads.
- [ ] **Step 5: Add the API type, card prop, and History-detail timeline mount with bilingual strings.**
- [ ] **Step 6: Run the focused backend/web tests and commit/push the green criterion.**

### Task 2: Incremental staging and interrupted-run durability

**Files:**
- Modify: `server/models.py`, `server/generate/persistence.py`, `server/generate/service.py`, `server/generate/routes.py`
- Modify: `tests/server/test_figure_policy_trail_persistence.py`, `tests/server/test_generate_teardown.py`

**Interfaces:**
- `GenerationLog.figure_policy_trail_json: Mapped[list | None]` stores the aggregate prefix for all workers in a run.
- `make_figure_policy_trail_recorder(...)` returns a thread-safe callback/snapshot pair; each callback serializes and commits the full prefix before returning.
- `persist_failed_generation_record` and `persist_aborted_generation_record` copy the staged log prefix into the tombstone record, while route cleanup remains inside the existing `anyio.CancelScope(shield=True)`.

- [ ] **Step 1: Write a failing disconnect test.** Drive a real SQLite generation stream whose fake 社會領域 worker emits a policy entry, then simulate client disconnect before `result`; assert the aborted History record retains that exact prefix and the staged log write occurred before the worker callback returned.
- [ ] **Step 2: Run the test and verify red.**

  ```bash
  uv run pytest tests/server/test_figure_policy_trail_persistence.py::test_interrupted_generation_persists_policy_prefix -q
  ```

- [ ] **Step 3: Implement serialized incremental log writes and tombstone copy.** Do not re-solve cancellation shielding; only feed the existing shielded abort helper from durable staged state.
- [ ] **Step 4: Run interruption, teardown, stream, and persistence tests; commit/push the green criterion.**

### Task 3: No-visual-spec silence

**Files:**
- Modify: `src/social_studies/cli.py`, `server/generate/service.py`, `web/src/components/FigurePolicyTrailTimeline.tsx`, `web/src/pages/HistoryDetail.tsx`
- Create/modify: `tests/test_figure_policy_trail.py`, `web/src/components/FigurePolicyTrailTimeline.test.tsx`

**Interfaces:**
- Non-visual 社會領域 runs do not invoke the policy callback and completed records carry `null` or an empty list.
- The timeline returns `null` for `null` and `[]`, including interrupted details with no visual events.

- [ ] **Step 1: Write a failing no-noise test** for a no-chart social run and for the timeline’s empty/absent input.
- [ ] **Step 2: Run it and verify red.**

  ```bash
  uv run pytest tests/test_figure_policy_trail.py::test_nonvisual_social_run_emits_no_policy_events -q
  cd web && npx vitest run src/components/FigurePolicyTrailTimeline.test.tsx
  ```

- [ ] **Step 3: Make empty/absent behavior silent without suppressing visual policy events.**
- [ ] **Step 4: Run the focused tests and commit/push the green criterion.**

### Task 4: Backend scenario coverage, migration, and final verification

**Files:**
- Create: `alembic/versions/c8d4f1a2b6e0_add_figure_policy_trails.py`
- Modify: `tests/server/test_generation_records_migration.py`, `tests/server/test_figure_policy_trail_persistence.py`, `tests/test_figure_kind_diversity_social_studies.py`
- Review: all files from Tasks 1–3

- [ ] **Step 1: Write failing migration and scenario assertions** covering clean, collision-repaired, collision-shipped-with-warning, and interrupted runs at persisted/public seams.
- [ ] **Step 2: Run those tests and verify red** because the new column/revision and any missing scenario contract are not yet complete.
- [ ] **Step 3: Add the nullable `GenerationLog`/`GenerationRecord` migration with SQLite-safe batch alteration and finish any minimal integration fixes.**
- [ ] **Step 4: Run the required scoped verification.**

  ```bash
  uv run pytest tests/server/ tests/test_figure_policy_trail.py tests/test_figure_kind_diversity_social_studies.py tests/test_figure_policy.py -q
  cd web && npm test && npx tsc -b
  git diff --check
  git status --short --branch
  ```

- [ ] **Step 5: Confirm the branch is clean, push the final green commit, and report exact tallies and the baseline environment setup note.**
