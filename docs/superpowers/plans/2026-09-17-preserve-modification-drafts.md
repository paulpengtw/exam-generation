# Preserve History Modification Drafts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a settled History manual-review draft survive Save Draft & Update, while refusing to submit it unless the exact authorized base question version is still current and eligible.

**Architecture:** Extend `exam-generation.recovery/1` with an optional, strictly validated `modification` workspace. The History detail page boots recovery before rendering its card, re-fetches the route record through the existing authenticated History API, and compares the saved immutable record anchor, question ID, canonical content identity, and eligibility evidence before enabling modification submission. The live card and modification hook remain the independent modification protocol; restore only seeds local state and never starts admission or SSE work.

**Tech Stack:** React 18, TypeScript, Zustand, React Router, Vitest, Testing Library, existing `apiFetch`/History API, localStorage/sessionStorage recovery transaction.

**Spec:** User brief for GitHub issue #775; compatible with `docs/research/2026-09-15-772-save-draft-and-update.md`, `docs/research/2026-09-17-773-preserve-confirmation.md`, and `docs/research/2026-09-17-774-preserve-results.md`.

## Global Constraints

- Keep `schema: "exam-generation.recovery/1"`; `modification` is optional so #772–#774 snapshots remain readable.
- Preserve the existing modification request shape, server protocol, frozen-field rules, UTF-16 selection offsets, and latest-child behavior.
- Save only when the History modification workspace is settled; any active `modification` operation still blocks Save Draft & Update and is never aborted by release detection.
- Validate the saved base against current authorized History data before enabling submission; changed identity, unavailable/unauthorized data, or ineligibility keeps the draft and blocks it.
- Do not reconnect old runs, submit a batch during restore, store AbortControllers/callbacks/tokens/diagnostics, or put recovery content in telemetry.
- Keep existing final-only download constraints, selection masking, localization, keyboard behavior, and form/confirmation/results recovery behavior unchanged.
- Every test added for the feature must exercise the real History detail/card flow where the requirement is behavioral; serializer tests supplement but do not replace those flows.

---

### Task 1: Define and validate the modification recovery workspace

**Files:**
- Modify: `web/src/lib/workspace/adapters/types.ts`
- Modify: `web/src/lib/workspace/adapters/modificationWorkspace.ts`
- Test: `web/src/lib/workspace/adapters/modificationWorkspace.test.ts`
- Modify: `web/src/lib/recovery/format.ts`
- Test: `web/src/lib/recovery/format.test.ts`

**Interfaces:**
- Produces `ModificationBaseEvidence`, the canonical identity/eligibility record captured with a History draft.
- Produces `ModificationWorkspaceSnapshot` with route, subject, base evidence, annotations, and optional received replacement.
- Produces `canonicalQuestionIdentity(question)` for both capture and current-record comparison.
- `importModificationWorkspace(raw)` returns a JSON-safe live workspace or `null`; malformed optional members make the recovery snapshot invalid rather than falling back to form hydration.

- [ ] **Step 1: Write failing adapter and parser tests.**

  Extend the existing fixtures with a route, subject, base record/question identity, known content revision, and eligibility evidence. Assert that JSON round-trip preserves two annotations containing multiple segments, an unfinished instruction, and a settled replacement. Assert that the parser accepts an older form-only snapshot and rejects missing/invalid route, identity, revision, eligibility, annotation, and replacement fields.

  Add a behavior test that two objects with different key insertion order produce the same canonical identity, while a changed answer/text/image produces a different identity. Derive expected strings from literal fixtures rather than calling the production identity helper for both sides.

- [ ] **Step 2: Run the focused tests and verify they fail for the missing modification fields/parser branch.**

  Run from `web/`:

  ```bash
  npm test -- src/lib/workspace/adapters/modificationWorkspace.test.ts src/lib/recovery/format.test.ts --run
  ```

  Expected: the new assertions fail because the current adapter has no base evidence/route/subject contract and `RecoverySnapshotV1` has no `modification` validation.

- [ ] **Step 3: Implement the minimal v1 extension.**

  Add an optional `modification?: ModificationWorkspaceSnapshot` to `RecoverySnapshotV1`. Define the base evidence as the saved route, subject, exact record ID, question ID, canonical content identity, optional positive `contentRevision`, and `eligible`/`status`/`verified` evidence. Keep the record ID as the immutable version anchor when no transport content revision is available. Validate all scalar fields, segment offsets, annotations, and replacement question shape. Keep `replacement` nullable and preserve every JSON-safe question field, including image bytes.

  Validate the optional member in `parseRecoverySnapshot` through `importModificationWorkspace`, returning the existing privacy-preserving `invalid_form` result on failure. Do not make `form`, `confirmation`, or `results` conditional.

- [ ] **Step 4: Run the focused tests and verify they pass.**

  ```bash
  npm test -- src/lib/workspace/adapters/modificationWorkspace.test.ts src/lib/recovery/format.test.ts --run
  ```

- [ ] **Step 5: Commit the self-contained workspace-format change.**

  ```bash
  git add web/src/lib/workspace/adapters/types.ts web/src/lib/workspace/adapters/modificationWorkspace.ts web/src/lib/workspace/adapters/modificationWorkspace.test.ts web/src/lib/recovery/format.ts web/src/lib/recovery/format.test.ts
  git commit -m "feat(775): define modification recovery workspace\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  ```

### Task 2: Capture settled History drafts in the recovery transaction

**Files:**
- Modify: `web/src/lib/recovery/saveAndUpdate.ts`
- Test: `web/src/lib/recovery/saveAndUpdate.test.ts`
- Modify: `web/src/components/ReleaseNotice.tsx`

**Interfaces:**
- Consumes `history.modification.exportWorkspace()` and the v1 modification adapter from Task 1.
- Produces a complete v1 snapshot for either a normal generate workspace or a History-only modification workspace.
- `evaluateSaveAndUpdate` allows a valid settled modification surface, but rejects malformed/missing exports and active operations.

- [ ] **Step 1: Write failing evaluator/controller tests.**

  Replace the old blanket `history.modification` refusal with tests that assert:

  - a valid settled History workspace with two annotations is allowed;
  - a settled replacement is allowed and is persisted with the latest result;
  - an invalid/missing modification export is refused;
  - an active modification operation is refused and remains active after the attempted save;
  - a History-only save writes the route/subject/modification member, uses a valid empty form envelope, persists the pointer, navigates once, and leaves `freezeInput` true on success;
  - a storage/quota failure leaves the live annotations and replacement untouched, does not navigate, clears the freeze/approval state, and leaves any previously saved snapshot/pointer available; and
  - a late mutation or release target change refuses navigation without writing the captured draft.

  Use the real exported adapter shape in fixtures and assert observable storage/pointer/navigation outcomes, not only mock calls.

- [ ] **Step 2: Run the focused tests and verify the old refusal/unsupported-form behavior fails against the new requirements.**

  ```bash
  npm test -- src/lib/recovery/saveAndUpdate.test.ts --run
  ```

- [ ] **Step 3: Implement the narrow eligibility exception and capture path.**

  Read and deep-clone form, confirmation, results, and modification exports before `checkNow()`. Permit `history.modification` only when its adapter validates and no operation is active; allow its `hasReceivedResults` flag only for that validated settled workspace. Preserve the existing refusal for all other non-`generate.results` received results. When the page has no `generate.form`, create only the valid empty form snapshot needed by the still-required v1 envelope; never pretend it contains a form draft. Derive the envelope subject from the modification export and keep the actual History pathname as `route`.

  After the release recheck, compare operations, target build/revision, reader support, account, workspace revision, and fresh exports for all captured workspaces. Include `modification` only when present. Reuse the existing cleanup/error behavior; do not log or interpolate recovery contents.

- [ ] **Step 4: Run the focused tests and verify they pass.**

  ```bash
  npm test -- src/lib/recovery/saveAndUpdate.test.ts --run
  ```

- [ ] **Step 5: Commit the capture change.**

  ```bash
  git add web/src/lib/recovery/saveAndUpdate.ts web/src/lib/recovery/saveAndUpdate.test.ts web/src/components/ReleaseNotice.tsx
  git commit -m "feat(775): capture settled modification drafts\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  ```

### Task 3: Restore annotations and replacement content without replaying the run

**Files:**
- Modify: `web/src/hooks/useModificationRun.ts`
- Modify: `web/src/components/QuestionCard.tsx`
- Test: `web/src/components/QuestionCard.workspace.test.tsx`
- Test: `web/src/components/QuestionCard.lifecycle.test.tsx`

**Interfaces:**
- Consumes a mount-latched `ModificationWorkspaceSnapshot` and a restore eligibility state from History detail.
- Produces a card that displays restored multi-segment annotations/instructions and replacement content, while only a current eligible base can add/delete/submit annotations.
- `useModificationRun(recordId?, initialResult?)` initializes a settled result without opening a network stream; later `start()` still uses the existing admission/SSE protocol and child record ID.

- [ ] **Step 1: Write failing real-card tests.**

  Add tests that render the real `QuestionCard` with a verified History question and a recovered workspace, then assert:

  - two selected annotations and their instructions are visible after mount;
  - a recovered replacement is rendered and its question/image/download behavior remains the existing final behavior;
  - acknowledging the parent recovery state (simulated by rerendering without the prop) does not erase the latched annotation/result state;
  - no admission fetch or `fetchEventSource` call occurs on restore;
  - an eligible restored draft can be edited and submitted exactly once using the independent existing batch shape; and
  - an ineligible restore keeps selections/instructions visible but disables selection mutation, delete, and submit.

  Add an active-run test that checks the workspace operation remains registered while the stream is gated and that Save Draft & Update cannot begin a second transaction; releasing the stream records the settled replacement for a later export.

- [ ] **Step 2: Run the focused tests and verify they fail because QuestionCard does not consume recovery state.**

  ```bash
  npm test -- src/components/QuestionCard.workspace.test.tsx src/components/QuestionCard.lifecycle.test.tsx --run
  ```

- [ ] **Step 3: Implement mount-latched restore state.**

  Add an optional recovery workspace/eligibility prop to `QuestionCard`. Initialize annotation IDs and `useModificationRun` from the snapshot, and change the result-clearing effect to clear only when a new live result arrives—not on the initial restored result. Use the returned replacement record ID as the next modification target while retaining the History route identity.

  Extend `ModificationParticipation` to export the current route, subject, current target record/question IDs, canonical content identity, known revision, eligibility evidence, annotations, and replacement. Gate new selection/deletion/instruction editing/submission on `restoreEligible !== false`, but render captured controls disabled when the saved base is blocked. Preserve current masking, UTF-16 segment serialization, keyboard behavior, final-only downloads, and server-side field/qualification checks.

- [ ] **Step 4: Run the focused tests and verify they pass.**

  ```bash
  npm test -- src/components/QuestionCard.workspace.test.tsx src/components/QuestionCard.lifecycle.test.tsx --run
  ```

- [ ] **Step 5: Commit the card/stream restore change.**

  ```bash
  git add web/src/hooks/useModificationRun.ts web/src/components/QuestionCard.tsx web/src/components/QuestionCard.workspace.test.tsx web/src/components/QuestionCard.lifecycle.test.tsx
  git commit -m "feat(775): restore modification card state without replay\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  ```

### Task 4: Re-fetch and authorize the saved base in History detail

**Files:**
- Create: `web/src/lib/recovery/modificationValidation.ts`
- Test: `web/src/lib/recovery/modificationValidation.test.ts`
- Modify: `web/src/pages/HistoryDetail.tsx`
- Test: `web/src/pages/HistoryDetail.test.tsx`
- Test: `web/src/pages/HistoryDetail.annotation.test.tsx`
- Modify: `web/src/lib/recovery/recoveryStore.ts`

**Interfaces:**
- `validateModificationBase(snapshot, detail, requestedRoute)` returns `valid` or a localized-independent reason: `route_changed`, `record_changed`, `question_changed`, `content_changed`, `ineligible`, or `unauthorized`.
- History detail boots `initRecoveryStore` before card hydration, selects only a matching route modification snapshot, and exposes restore status/retry/acknowledge actions.

- [ ] **Step 1: Write failing validation and real History-flow tests.**

  Test the pure validator with literal History payloads for matching base, latest descendant/record change, changed question ID, changed canonical content, failed/unverified/incomplete base, and route mismatch.

  Extend the real `HistoryDetail` flow to cover multiple selections and unsent instructions, successful settled replacement, changed base version, and 401/403/404 authorization loss. Assert that the saved draft remains in the recovery store/storage on blocked/failure states, the localized explanation is visible, and the submit button is disabled. Assert that a valid restore shows the captured values and allows a later explicit submit without any restore-time POST/SSE activity. Add a retry test for a transient History fetch failure and a storage-failure integration test that leaves the original card state and existing downloads available.

- [ ] **Step 2: Run the focused tests and verify they fail because HistoryDetail does not boot/validate modification recovery.**

  ```bash
  npm test -- src/lib/recovery/modificationValidation.test.ts src/pages/HistoryDetail.test.tsx src/pages/HistoryDetail.annotation.test.tsx --run
  ```

- [ ] **Step 3: Implement the conservative History restore gate.**

  Add a canonical question identity comparison that excludes only non-content verification/status decoration while retaining question text, answers, curriculum fields, chart specs, and normalized image bytes. Treat the current detail response’s exact `id` as the record-version check; because the API follows the latest descendant, any changed child is explicitly blocked. Require current route, status `completed`, question JSON present, matching question ID/content identity/revision, and the saved/current eligibility evidence before enabling submission. Classify `ApiError` 401/403/404 (and no-detail restore failure) as blocked without logging recovery data.

  In `HistoryDetail`, call `initRecoveryStore` in a layout-gated boot path, fetch the requested record normally (which is the authorized re-fetch), validate the latched modification snapshot, and pass it plus the gate state to `QuestionCard`. Render a localized recovery notice with retry and explicit acknowledge/discard. Acknowledge/discard may delete the stored snapshot only after the card/data hydration succeeds; blocked or failed validation keeps the snapshot and leaves the current workspace non-submittable. Never call `submitModificationBatch` or reconnect an old stream during restore.

- [ ] **Step 4: Run the focused tests and verify they pass.**

  ```bash
  npm test -- src/lib/recovery/modificationValidation.test.ts src/pages/HistoryDetail.test.tsx src/pages/HistoryDetail.annotation.test.tsx --run
  ```

- [ ] **Step 5: Commit the History restore gate.**

  ```bash
  git add web/src/lib/recovery/modificationValidation.ts web/src/lib/recovery/modificationValidation.test.ts web/src/pages/HistoryDetail.tsx web/src/pages/HistoryDetail.test.tsx web/src/pages/HistoryDetail.annotation.test.tsx web/src/lib/recovery/recoveryStore.ts
  git commit -m "feat(775): validate restored History modification bases\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  ```

### Task 5: Localize, document, and exercise the complete transaction

**Files:**
- Modify: `web/src/i18n/messages.ts`
- Test: `web/src/i18n/messages.coverage-mode.test.ts` or a focused recovery-message test
- Create: `docs/research/2026-09-17-775-preserve-modification-drafts.md`
- Modify: `CLAUDE.md`
- Modify: `web/src/recoveryFlow.test.tsx`

**Interfaces:**
- Produces localized strings for restored, checking, blocked-base, unavailable/unauthorized, retry, and settled replacement states in both `en-US` and `zh-TW`.
- Produces the issue #775 research record, with every claim tied to a passing real-flow test.

- [ ] **Step 1: Write failing end-to-end recovery-flow assertions and locale coverage.**

  Add a real-router scenario that saves through the rendered ReleaseNotice on `/history/:id`, navigates/reloads, delays the History response, restores two selections plus instructions and a received replacement, verifies no automatic modification admission/SSE, then explicitly submits after a matching base check. Add separate scenarios for changed descendant, authorization loss, storage failure, and retry/restore failure. Assert current download controls remain unchanged. Add locale assertions that every new `recovery.modification.*` key exists and is non-empty in both dictionaries.

- [ ] **Step 2: Run the focused integration tests and verify the new cases fail.**

  ```bash
  npm test -- src/recoveryFlow.test.tsx src/i18n/messages.coverage-mode.test.ts --run
  ```

- [ ] **Step 3: Finish localization and documentation.**

  Add only localized UI strings; keep server error details out of recovery notices. Document the optional envelope member, capture/restore sequence, exact base-version comparison, conservative blocked states, active-run refusal, independent protocol, failure retention, privacy boundary, and the real test files/counts (updated after verification). Add a concise `### Manual-review modification draft recovery (issue #775)` note immediately after the #774 note in `CLAUDE.md`.

- [ ] **Step 4: Run the focused integration tests and verify they pass.**

  ```bash
  npm test -- src/recoveryFlow.test.tsx src/i18n/messages.coverage-mode.test.ts --run
  ```

- [ ] **Step 5: Commit the user-facing/docs change.**

  ```bash
  git add web/src/i18n/messages.ts web/src/i18n/messages.coverage-mode.test.ts web/src/recoveryFlow.test.tsx docs/research/2026-09-17-775-preserve-modification-drafts.md CLAUDE.md
  git commit -m "feat(775): document modification draft recovery\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
  ```

### Task 6: Review and verify the complete branch

**Files:**
- Modify: any implementation/test/docs files identified by review or verification failures

- [ ] **Step 1: Re-read this plan and inspect the complete diff.**

  Confirm every acceptance criterion maps to code and a real flow test, especially the exact base-version check, active-run behavior, restoration failure retention, and no-replay protocol.

- [ ] **Step 2: Request a focused code review of the completed branch.**

  Review the diff against the issue brief and this plan. Fix every Critical/Important finding before final verification; do not weaken tests to make them pass.

- [ ] **Step 3: Run the required full web verification from `web/`.**

  ```bash
  npx tsc -b --noEmit
  npm run lint
  npm test
  npm run build
  ```

  Record exact exit status, TypeScript error count, lint error/warning counts, test file/test totals, and Vite module count/warnings in the research document and final report.

- [ ] **Step 4: Confirm branch and tree state.**

  ```bash
  git status --short --branch
  git log --oneline -10
  ```

  The branch must be `feat/775-preserve-modification-drafts`, the tree must be clean, and no push or PR may be performed.

