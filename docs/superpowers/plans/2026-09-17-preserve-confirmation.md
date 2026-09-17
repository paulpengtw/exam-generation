# Preserve Confirmation Across Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend recovery format v1 so a settled pre-send confirmation reopens with its exact form-independent payload, provenance, edits, and source choice after an update.

**Architecture:** Keep ordinary form state and confirmation state as separate workspace exports. The save controller captures and JSON-clones both exports synchronously before its asynchronous release recheck; it accepts a confirmation only when its export is valid and settled and still refuses operations, results, and modification drafts. The recovery store continues authenticating and exposing one pending snapshot, while `ParamForm` latches the restored form/confirmation at mount, initializes confirmation state from the snapshot, suppresses preview/planner/resolver effects, and retains the captured state after the recovery banner is acknowledged.

**Tech Stack:** TypeScript, React, Zustand, React Testing Library, Vitest, localStorage/sessionStorage recovery v1.

**Spec:** GitHub issue #773, `docs/research/2026-09-17-773-preserve-confirmation.md`, and the existing #772/#769 recovery/workspace contracts.

## Global Constraints

- Preserve `exam-generation.recovery/1`; all new snapshot members are optional so #772 snapshots remain readable.
- Save only JSON-serialisable form/confirmation state; never persist credentials, tokens, raw requests, or recovery telemetry.
- Capture settled state before any awaited release check; reject active operations and any state/revision change during the recheck.
- Restore is inert: no resolver, planner, prompt preview, redraw, or generation call is triggered by hydration.
- Confirmation-only edits never mutate ordinary `FormFields`; the later explicit send uses the captured pending payload and per-question rows.
- New user-facing strings must exist in both locales.
- Run from `web/`: `npx tsc -b --noEmit`, `npm run lint`, `npm test`, and `npm run build`.

---

### Task 1: Define and validate the v1 confirmation snapshot extension

**Files:**
- Modify: `web/src/lib/workspace/adapters/types.ts`
- Modify: `web/src/lib/workspace/adapters/confirmationWorkspace.ts`
- Modify: `web/src/lib/workspace/adapters/confirmationWorkspace.test.ts`
- Modify: `web/src/lib/recovery/format.ts`
- Modify: `web/src/lib/recovery/format.test.ts`

**Interfaces:**
- Consumes: existing `ConfirmationWorkspaceSnapshot`, `exportConfirmationWorkspace`, `importConfirmationWorkspace`, and `RecoverySnapshotV1`.
- Produces: optional `RecoverySnapshotV1.confirmation`, optional confirmation `pendingPrefill`, strict validation of the optional envelope, and backward-compatible parsing when it is absent.

- [ ] **Step 1: Write failing tests** for a confirmation snapshot that round-trips pending top-level/per-question payloads, seed/drawn/redraw/cleared provenance, confirmation edits, pending prefill, and `historyDraftChoice`; add parser tests proving a v1 form-only snapshot remains valid and malformed confirmation is rejected.

- [ ] **Step 2: Run focused tests to verify the new tests fail**:
  `npm test -- src/lib/workspace/adapters/confirmationWorkspace.test.ts src/lib/recovery/format.test.ts`.

- [ ] **Step 3: Implement the optional fields and strict parser path** without changing the format discriminator. Keep old confirmation adapter callers valid by making `pendingPrefill` optional and preserve all exact payload values as JSON data.

- [ ] **Step 4: Run the focused tests again** and confirm they pass.

- [ ] **Step 5: Commit**:
  `git add web/src/lib/workspace/adapters web/src/lib/recovery/format.ts web/src/lib/recovery/format.test.ts && git commit -m "feat(773): extend recovery snapshots with confirmation state"`.

### Task 2: Allow only settled confirmation in the save transaction

**Files:**
- Modify: `web/src/lib/recovery/saveAndUpdate.ts`
- Modify: `web/src/lib/recovery/saveAndUpdate.test.ts`

**Interfaces:**
- Consumes: workspace surface exports and `importConfirmationWorkspace`.
- Produces: `evaluateSaveAndUpdate` allowing a valid settled confirmation, `runSaveAndUpdate` storing both independent workspace exports, cloning before await, and refusing active/unsettled/changed state.

- [ ] **Step 1: Write failing tests** for allowed settled confirmation, refused loading confirmation, snapshot exactness after a late mutation, operation refusal, and target-change refusal with no navigation.

- [ ] **Step 2: Run the focused save tests** and verify the new cases fail for the pre-change confirmation refusal/field omission.

- [ ] **Step 3: Implement the minimum evaluator/controller changes**: validate the confirmation export, require non-loading `coreQuestionResolution`, capture JSON-cloned form and confirmation before `checkNow`, recheck operations/revision/exports after the await, and serialize the optional confirmation in `RecoverySnapshotV1`.

- [ ] **Step 4: Run all recovery tests**:
  `npm test -- src/lib/recovery/saveAndUpdate.test.ts src/lib/recovery/format.test.ts src/lib/recovery/recoveryStore.test.ts`.

- [ ] **Step 5: Commit**:
  `git add web/src/lib/recovery/saveAndUpdate.ts web/src/lib/recovery/saveAndUpdate.test.ts && git commit -m "feat(773): save settled confirmation with form recovery"`.

### Task 3: Restore the exact confirmation before hydration effects

**Files:**
- Modify: `web/src/components/ParamForm.tsx`
- Modify: `web/src/pages/GeneratePage.tsx`
- Modify: `web/src/components/ParamForm.recovery.test.tsx`
- Modify: `web/src/pages/GeneratePage.workspace.test.tsx`
- Modify: `web/src/recoveryFlow.test.tsx`

**Interfaces:**
- Consumes: `RecoverySnapshotV1.confirmation`, `importConfirmationWorkspace`, and existing recovery callbacks.
- Produces: `ParamForm.recoveredConfirmation`, exact initial pending confirmation state, inert restore behavior, latched recovery banner, and the same explicit `onSubmit` payload after restore.

- [ ] **Step 1: Write failing real-flow tests** that mount the form/page with a stored snapshot for math, social studies, and natural sciences, including multiple question rows, per-subquestion configs, text instructions, curriculum/model/effort/media fields, random values, parent/child changes, redraw provenance, and History choice; assert delayed schema/model promises cannot replace visible values and no resolver/planner/preview call occurs.

- [ ] **Step 2: Run the recovery-flow tests** and verify they fail because only `form` is restored.

- [ ] **Step 3: Implement latched recovery inputs**: initialize pending params/rows/provenance/core resolution from the confirmation export, set the preview guard before effects run, render the recovery banner in the confirmation surface, retain local state after the store clears, and pass the confirmation through `GeneratePage`. On explicit send, acknowledge the stored snapshot and call the existing submit callback with the exact payload/rows.

- [ ] **Step 4: Add confirmation invalid-value visibility/gating** for values not admitted by the currently loaded schema; do not discard them during delayed schema/model discovery. Keep correction explicit and do not silently redraw or resolve.

- [ ] **Step 5: Run focused component/page/flow tests** and confirm all pass.

- [ ] **Step 6: Commit**:
  `git add web/src/components/ParamForm.tsx web/src/pages/GeneratePage.tsx web/src/components/ParamForm.recovery.test.tsx web/src/pages/GeneratePage.workspace.test.tsx web/src/recoveryFlow.test.tsx && git commit -m "feat(773): restore confirmation workspace after update"`.

### Task 4: Wire boot restoration and document the contract

**Files:**
- Modify: `web/src/pages/GeneratePage.tsx`
- Modify: `web/src/i18n/messages.ts`
- Modify: `CLAUDE.md`
- Create: `docs/research/2026-09-17-773-preserve-confirmation.md`

**Interfaces:**
- Consumes: existing `initRecoveryStore`, localized #772 recovery strings, and the implemented confirmation flow.
- Produces: automatic route-scoped recovery initialization, localized restore/invalid-state copy in both locales, and a research note matching the #772 format.

- [ ] **Step 1: Write failing localization/boot assertions** for the new confirmation recovery copy and route-mounted initialization.

- [ ] **Step 2: Run the focused tests** and verify the assertions fail.

- [ ] **Step 3: Implement boot initialization and copy** with no telemetry content; document compatibility, capture timing, settled-operation gate, restore precedence, and verification evidence placeholders to be filled after the final run.

- [ ] **Step 4: Run the complete required verification suite** from `web/`.

- [ ] **Step 5: Review the diff and commit**:
  `git add CLAUDE.md docs/research/2026-09-17-773-preserve-confirmation.md web/src/i18n/messages.ts web/src/pages/GeneratePage.tsx && git commit -m "feat(773): document confirmation recovery flow"`.

### Task 5: Final review and handoff

**Files:**
- Review: all changes since the #772 base commit.

- [ ] **Step 1: Run `git diff feat/772-save-draft-and-update..HEAD` and inspect every changed file.**
- [ ] **Step 2: Dispatch a read-only reviewer with the issue requirements and commit range.**
- [ ] **Step 3: Fix any Critical or Important findings, rerun affected tests, and commit fixes with the `feat(773): ` prefix.**
- [ ] **Step 4: Run the complete verification suite once more after all fixes.**
- [ ] **Step 5: Confirm the final commit message ends with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`, do not push, and report exact counts.**

