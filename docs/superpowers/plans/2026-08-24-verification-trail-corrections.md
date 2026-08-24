# Verification Trail Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add initial question snapshots and post-correction snapshots to the ordered verification trail while preserving the existing verdict payload and transport path.

**Architecture:** Keep `VerificationTrailEntry` as the unchanged `kind: "verification"` verdict model and add `kind: "initial"` and `kind: "correction"` models carrying sanitized JSON snapshots. Emit the initial entry immediately before the first verification and correction entries after each corrector/re-render pass immediately before re-verification; the existing server callback, SSE emitter, persistence list, and shared timeline consume the union without protocol changes.

**Tech Stack:** Python 3, Pydantic, pytest, React/TypeScript, Vitest, Testing Library, existing SSE and history mounts.

**Spec:** GitHub issue #431 acceptance criteria and architecture in the user brief.

## Global Constraints

- Keep `VerificationTrailEntry` field shape exactly unchanged.
- Every entry has `code: "verification_trail"`; `kind` discriminates `verification`, `initial`, and `correction`.
- Snapshots exclude `verification`, embedded image payloads, and binary image data while retaining image file-path references.
- Do not change SSE transport, persistence mechanics, or Alembic migrations.
- Skip-verify and dry-run produce no trail entries.
- Every behavior is implemented red-green: write the failing test, run it, implement minimally, and rerun it.

### Task 1: Backend trail union and snapshot chain

**Files:**
- Modify: `tests/test_verification_trail.py`
- Modify: `src/common/verification_trail.py`
- Modify: `src/common/generation_core.py`

**Interfaces:**
- Produces `VerificationTrailInitialEntry`, `VerificationTrailCorrectionEntry`, and a union callback type consumed by the generation core.
- `make_question_snapshot(question)` returns JSON-compatible question data without `verification` or image payload fields.

- [ ] **Step 1: Write failing ordering, metadata, and snapshot tests**

  Add tests that run `generate_with_corrections_core` with a failed first verifier result, a mutating corrector, and a passing re-verifier. Assert the literal kind order `initial`, `verification`, `correction`, `verification`, correction `retry_index == 1`, the resolved `model_correct or model_execute`, parseable correction timestamps, the initial pre-correction value, the correction post-correction value, retained `圖片` path, and absent `verification`/`image_base64` fields.

- [ ] **Step 2: Run the focused tests and verify the expected red failure**

  Run `uv run pytest tests/test_verification_trail.py -q` (or `python -m pytest tests/test_verification_trail.py -q` if `uv` is unavailable). The new expectations must fail because the new entry kinds and snapshot emission do not exist.

- [ ] **Step 3: Write the minimal backend models and emitters**

  Add the two new Pydantic entry models and snapshot sanitizer in `verification_trail.py`. Emit the initial entry only when `not skip_verify` and a trail callback exists, immediately before the first verifier call. Emit one correction entry after the correction/re-rendered question state and before the re-verifier call, using `attempt + 1` and `config.model_correct or config.model_execute`.

- [ ] **Step 4: Run the focused tests and verify green**

  Run the same focused pytest command and confirm the new tests and existing verdict-shape assertion pass.

### Task 2: Backend first-pass, exhaustion, and server seam contracts

**Files:**
- Modify: `tests/test_verification_trail.py`
- Modify: `tests/server/test_verification_trail_stream.py`
- Modify: `tests/server/test_verification_trail_persistence.py`

**Interfaces:**
- Consumes the backend union from Task 1 through the existing `on_trail_entry` callback.
- Verifies the server emits and stores the exact same ordered JSON list.

- [ ] **Step 1: Write failing first-pass/exhaustion and stream/persistence tests**

  Update the existing first-pass test surgically to expect `[initial, verification]` while preserving the exact verdict payload assertion. Add an exhausted-retries test asserting the final item is a failed verification. Extend the existing stream and completed-persistence seam fixtures to emit an initial/correction/verdict list and assert exact payload/order equality.

- [ ] **Step 2: Run the tests and verify red**

  Run `uv run pytest tests/test_verification_trail.py tests/server/test_verification_trail_stream.py tests/server/test_verification_trail_persistence.py -q` (or the Python fallback). The changed pipeline expectations must fail before the implementation is complete.

- [ ] **Step 3: Make only test-support adjustments required by the implemented union**

  Keep server production code unchanged; use the new typed entries in the seam fixtures and retain the existing null-trail skip-verify assertions.

- [ ] **Step 4: Run the three backend files and verify green**

  Confirm the full focused backend command passes with the same list at the SSE and persistence boundaries.

### Task 3: Frontend union and live trail accumulation

**Files:**
- Modify: `web/src/hooks/useGenerate.ts`
- Modify: `web/src/hooks/useGenerate.test.ts`
- Modify: `web/src/api/client.ts`

**Interfaces:**
- `VerificationTrailEntry` becomes a TypeScript discriminated union with `verification`, `initial`, and `correction` members.
- `GeneratedQuestion.trail` and `HistoryDetail.verification_trail` carry that union without mount-specific adapters.

- [ ] **Step 1: Write the failing type-and-accumulation test**

  Add typed initial and correction fixtures to the hook test and assert the matching question lane accumulates them in stream order with verdicts. Type the fixtures as `VerificationTrailEntry` so the current verdict-only type rejects their snapshot/retry fields.

- [ ] **Step 2: Run the frontend type test and verify red**

  Run `cd web && npx tsc --ignoreConfig --noEmit --target es2023 --lib ES2023,DOM --module esnext --moduleResolution bundler --jsx react-jsx --verbatimModuleSyntax --skipLibCheck --types vite/client src/hooks/useGenerate.test.ts`; it must fail on the missing union members before production type changes because the project build intentionally excludes `*.test.*`. Run the focused hook Vitest file as well to capture the runtime baseline.

- [ ] **Step 3: Implement the minimal discriminated union and API typing**

  Add exact fields for the three kinds, preserve verdict fields, and keep the existing `code`/`question_id` stream guard. Update the API client import/field typing only if required by the shared union.

- [ ] **Step 4: Run focused hook tests and typecheck green**

  Run `cd web && npx vitest run src/hooks/useGenerate.test.ts && npx tsc -b`.

### Task 4: Timeline rendering and user-facing strings

**Files:**
- Modify: `web/src/components/VerificationTrailTimeline.tsx`
- Modify: `web/src/components/VerificationTrailTimeline.test.tsx`
- Modify: `web/src/i18n/messages.ts`

**Interfaces:**
- The existing shared timeline renders initial, verification, and correction entries for both live and history mounts.
- Each initial/correction snapshot has its own per-entry toggle and pretty-printed `<pre>` content; the outer trail toggle remains unchanged.

- [ ] **Step 1: Write failing timeline tests**

  Render a trail containing initial, failed verification, correction, and terminal failed verification. Assert initial-version and 修正 labels, retry index, corrector model, timestamps, terminal failed styling/status, and snapshot `<pre>` content only after clicking each per-entry toggle.

- [ ] **Step 2: Run the focused timeline test and verify red**

  Run `cd web && npx vitest run src/components/VerificationTrailTimeline.test.tsx`; the current verdict-only renderer must fail to find the new labels/snapshot toggles.

- [ ] **Step 3: Implement minimal kind branches and i18n translations**

  Branch on `entry.kind`, render neutral initial/correction cards with required metadata and per-entry disclosure buttons, retain failed verdict styling even when it is the last entry, and add matching English/zh-TW `card.trail…` messages following the existing map order.

- [ ] **Step 4: Run timeline, QuestionCard, and HistoryDetail tests plus typecheck**

  Run `cd web && npx vitest run src/components/VerificationTrailTimeline.test.tsx src/components/QuestionCard.test.tsx src/pages/HistoryDetail.test.tsx && npx tsc -b`.

### Task 5: Full verification, review, and commit

**Files:**
- Review all changed files from Tasks 1–4.

- [ ] **Step 1: Run the requested backend focused suite and full pytest**

  Run `uv run pytest tests/test_verification_trail.py tests/server/test_verification_trail_stream.py tests/server/test_verification_trail_persistence.py` and then `uv run pytest` (using `python -m pytest` for either command only if `uv` is unavailable).

- [ ] **Step 2: Run the requested frontend suites**

  From `web`, run `npx tsc -b`, `npx vitest run`.

- [ ] **Step 3: Inspect the diff and request review**

  Check `git diff --check`, `git status`, and the complete diff for unchanged transport/persistence mechanics, no Alembic edits, and preserved verdict fields. Request a focused code review against issue #431 and fix any critical/important findings with another red-green cycle.

- [ ] **Step 4: Commit the verified implementation**

  Commit all scoped changes with `feat: add correction snapshots to verification trail (#431)` and do not push.
