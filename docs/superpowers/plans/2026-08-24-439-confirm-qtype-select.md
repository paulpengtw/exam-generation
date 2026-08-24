# Confirmation 題型 Select (#439) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each confirmation-screen 各小題配置 card expose the schema-backed 題型 select, preserve its badge semantics, and submit confirmation-only edits in the correct per-題組 row.

**Architecture:** Extract the 題型 select into `SubQuestionQuestionTypeField` beside the existing `SubQuestionInstructionField`. The field receives the loaded `questionTypes` pool and applies the existing `questionTypeOptions(subject, questionTypes)` helper, so the Generate form and confirmation cards share one control. Confirmation cards keep their existing field-specific callback shape, while `ParamForm` routes both instruction and 題型 edits through one partial-config updater over `pendingPerQuestionParams`.

**Tech Stack:** React, TypeScript, Testing Library, Vitest, existing i18n and schema APIs.

**Spec:** Ticket #439 requirements in the user request; `CONTEXT.md` glossary entries for 全域池, 預抽, 釘選, 確認頁修改, and 強制值.

## Global Constraints

- The 題型 option pool is schema-driven; do not duplicate or hardcode a second option list.
- Natural-science options use the existing `questionTypeOptions(subject, questionTypes)` PISA mapping.
- Confirmation edits are per-題組 draft state and never write back to the shared form configuration.
- Edited values are user-supplied/釘選; untouched values and badges remain unchanged.
- Submitted per-小題 題型 retains the existing 強制值 behavior and wire shape.
- Each acceptance criterion gets a failing Vitest test before its production change, followed by a focused green run and refactor only after green.

---

### Task 1: Extract and render the schema-backed confirmation 題型 field

**Files:**
- Modify: `web/src/components/SubQuestionConfigEditor.tsx`
- Modify: `web/src/components/SubquestionConfigCards.tsx`
- Modify: `web/src/components/ParamForm.tsx`
- Modify: `web/src/i18n/messages.ts`
- Test: `web/src/components/ParamForm.confirmation-display.test.tsx`

**Interfaces:**
- `SubQuestionQuestionTypeField` consumes `config`, `subject`, `questionTypes`, `onChange`, and optional badge props, then renders the same select in both consumers.
- `SubquestionConfigCards` consumes the loaded `questionTypes` pool and an optional `onQuestionTypeChange` callback for confirmation mode.

- [ ] **Step 1: Write the failing test**

Add a confirmation-screen test that loads a Social Studies schema containing two distinct `題型` entries, opens two 題組 with blank per-小題 configs, and asserts every card has a labelled 題型 select whose option values are exactly `""` plus the two schema values.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "renders a schema-backed 題型 select"`

Expected: FAIL because the confirmation card currently renders static 題型 text and no labelled select.

- [ ] **Step 3: Write minimal implementation**

Export the sibling field from `SubQuestionConfigEditor.tsx`, move the existing editor 題型 select markup into it, and let that field call the existing `questionTypeOptions(subject, questionTypes)` helper. Pass `availableQuestionTypes` from `ParamForm` into the editable confirmation cards and render the new field when its question-type callback is supplied. Add the field label key to both locale objects if the shared control needs one.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "renders a schema-backed 題型 select"`

Expected: PASS.

- [ ] **Step 5: Refactor after green**

Keep one select implementation and one call to `questionTypeOptions`; update the Generate editor to consume the extracted field without changing its existing behavior.

### Task 2: Route confirmation 題型 edits through per-題組 state and badges

**Files:**
- Modify: `web/src/components/SubquestionConfigCards.tsx`
- Modify: `web/src/components/ParamForm.tsx`
- Test: `web/src/components/ParamForm.confirmation-display.test.tsx`

**Interfaces:**
- `updatePendingSubquestionConfig(questionIndex, subquestionIndex, patch)` updates only the addressed serialized `subquestion_configs` row.
- Existing `updatePendingSubquestionInstruction` remains as a thin wrapper over that generic updater.
- `onQuestionTypeChange` supplies `{ question_type: value || undefined }` to the same seam.

- [ ] **Step 1: Write the failing test**

Add a test that changes the first card’s 題型 in the first 題組 and asserts only that select changes, the first card’s 題型 badge changes from 隨機抽取 to 使用者選擇, and sibling cards plus the corresponding card in the second 題組 retain their random badges.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "updates only the edited 題型"`

Expected: FAIL because the card has no editable callback and the updater is instruction-specific.

- [ ] **Step 3: Write minimal implementation**

Add `onQuestionTypeChange`, derive the 題型 badge from whether `config.question_type` is present, and replace the instruction updater body with a field-agnostic partial patch operation. Wire both field callbacks from the confirmation question block to that operation.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "updates only the edited 題型"`

Expected: PASS.

### Task 3: Verify edited 題型 submission and 強制值 preservation

**Files:**
- Modify: `web/src/components/ParamForm.confirmation-display.test.tsx`
- Modify: `web/src/components/ParamForm.tsx` only if the test exposes a serialization gap.

**Interfaces:**
- `handleConfirmSend` serializes the edited `pendingPerQuestionParams` exactly as it does for instruction confirmation edits.

- [ ] **Step 1: Write the failing test**

Add a payload assertion that edits one 題型, clicks 確定發送, and checks the edited value is in the correct `per_question_params[questionIndex].subquestion_configs[subquestionIndex]` row, all untouched config fields remain intact, and no confirmation-only metadata is added.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "submits the edited 題型"`

Expected: FAIL because the new select cannot currently update the pending payload.

- [ ] **Step 3: Write minimal implementation**

Use the generic updater’s serialized row result as the existing `handleConfirmSend` input; do not add a new payload flag or modify backend enforcement semantics.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "submits the edited 題型"`

Expected: PASS.

### Task 4: Lock untouched resolved 題型 and badge behavior

**Files:**
- Modify: `web/src/components/ParamForm.confirmation-display.test.tsx`
- Modify: production files only if this regression test identifies a missing preservation rule.

- [ ] **Step 1: Write the failing test**

Add a test with one explicitly supplied 題型, one different supplied 題型, and one blank 題型; edit only the first card and assert the other two values and their 使用者選擇/隨機抽取 badges remain unchanged.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "keeps untouched 題型"`

Expected: FAIL until the confirmation field preserves each row’s independent value and badge.

- [ ] **Step 3: Write minimal implementation and refactor**

Fix only the addressed row if needed; otherwise keep the production implementation unchanged and retain the regression test.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "keeps untouched 題型"`

Expected: PASS.

### Task 5: Full verification and handoff

**Files:**
- Verify: all changed files and the final git diff.

- [ ] **Step 1: Run the complete web test suite**

Run: `cd web && npm test -- --run`

Expected: exit 0 with no failed Vitest tests.

- [ ] **Step 2: Run the TypeScript build check**

Run: `cd web && npx tsc -b --noEmit`

Expected: exit 0.

- [ ] **Step 3: Run lint**

Run: `cd web && npm run lint`

Expected: exit 0 with no lint errors.

- [ ] **Step 4: Inspect the diff and commit**

Run: `git diff --check && git status --short && git diff --stat`

Commit with: `git add web/src/components/SubQuestionConfigEditor.tsx web/src/components/SubquestionConfigCards.tsx web/src/components/ParamForm.tsx web/src/components/ParamForm.confirmation-display.test.tsx web/src/i18n/messages.ts docs/superpowers/plans/2026-08-24-439-confirm-qtype-select.md && git commit -m "feat: make confirmation question types editable (#439)"`

Do not push, merge, or open a pull request.
