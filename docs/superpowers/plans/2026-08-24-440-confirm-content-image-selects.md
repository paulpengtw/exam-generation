# Confirmation Content and Image Selects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make 題目內容類型 and 圖片生成模式 editable on each 發送前確認 各小題配置 card, preserving blank image-mode inheritance and per-題組 payload isolation.

**Architecture:** Extract the two existing Generate-form subquestion selects into badge-aware field components beside the existing instruction and question-type fields. Confirmation cards render those shared controls only when their matching optional callback exists, otherwise retaining the DraftSummary static fallback. ParamForm updates the matching nested row through `updatePendingSubquestionConfig`, leaving undefined fields absent so the renderer receives per-小題 mode → request-level mode precedence unchanged.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, existing `useT` i18n and schema types.

**Spec:** User-provided GitHub issue #440 brief and `CONTEXT.md` / `CLAUDE.md` Image Rendering Architecture.

## Global Constraints

- 題目內容類型 options come from `schemas.題目內容類型`; do not hardcode that pool.
- 圖片生成模式 options are blank `沿用文本設定`, `html` / `HTML 渲染`, and `gpt_image` / `GPT 生圖`.
- A blank per-小題 image mode must remain absent from the submitted row and inherit the request-level mode in the backend.
- Confirmation edits are per 題組 and never write back to shared form configuration.
- DraftSummary must continue using read-only static fallbacks when edit callbacks are absent.
- Add every new label key to both `en-US` and `zh-TW` in `web/src/i18n/messages.ts`.

---

### Task 1: Extract shared content/image fields and render editable card controls

**Files:**
- Modify: `web/src/components/SubQuestionConfigEditor.tsx`
- Modify: `web/src/components/SubquestionConfigCards.tsx`
- Modify: `web/src/components/ParamForm.tsx`
- Modify: `web/src/i18n/messages.ts`
- Test: `web/src/components/ParamForm.confirmation-display.test.tsx`

**Interfaces:**
- `SubQuestionContentTypeField({ config, contentTypes, onChange, badge? })` emits `Partial<SubQuestionConfig>` patches with `content_type`.
- `SubQuestionImageGenerationModeField({ config, onChange, badge? })` emits `Partial<SubQuestionConfig>` patches with `image_generation_mode`.
- `SubquestionConfigCards` accepts optional `onContentTypeChange` and `onImageModeChange`; absent callbacks render the current static text.

- [x] **Step 1: Write the failing option-pool test**

  Add a confirmation test with schema content types `純文字`, `含圖片`, and a schema-only value, then assert every social-studies card exposes labelled content/image selects with option values `""`, those schema values, and `""`, `"html"`, `"gpt_image"` respectively. Assert the Generate-form subquestion editor still exposes the same pools through its extracted controls.

- [x] **Step 2: Run the focused test to verify it fails**

  Run `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "content type and image mode selects"`.

  Expected: FAIL because the confirmation cards still render static content/image text and the Generate editor still owns inline markup.

- [x] **Step 3: Extract the two fields and wire card rendering**

  Move the existing inline subquestion content/image select markup into exported components with `useId` labels and optional badge rendering. Replace the inline markup in `SubQuestionConfigEditor` with those components. Extend cards with the two optional callbacks and static fallbacks, and pass edit callbacks from the confirmation path using the existing pending-row updater seam. Add both field-label translation keys to both locales.

- [x] **Step 4: Run the focused test to verify it passes**

  Run `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "content type and image mode selects"`.

  Expected: PASS.

- [x] **Step 5: Refactor without changing behavior**

  Keep the field option arrays and badge markup in the extracted components, remove all duplicate inline select markup, and confirm the DraftSummary call still supplies no edit callbacks.

### Task 2: Preserve blank image-mode inheritance and explicit pinning

**Files:**
- Modify: `web/src/components/ParamForm.tsx`
- Test: `web/src/components/ParamForm.confirmation-display.test.tsx`

**Interfaces:**
- `updatePendingSubquestionImageMode(questionIndex, subquestionIndex, imageMode)` calls `updatePendingSubquestionConfig` with `image_generation_mode: imageMode || undefined`.

- [x] **Step 1: Write the failing inheritance test**

  Submit a social-studies confirmation with request-level `image_generation_mode: "gpt_image"` and two blank per-小題 image modes. Assert both submitted rows omit `image_generation_mode`; then select `html` for only the first row and assert only that row contains `image_generation_mode: "html"`.

- [x] **Step 2: Run the focused test to verify it fails**

  Run `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "blank image mode inherits"`.

  Expected: FAIL because the new card select has no image-mode pending updater wired through ParamForm yet.

- [x] **Step 3: Add the thin image-mode wrapper**

  Add `updatePendingSubquestionImageMode` beside the existing instruction/question-type wrappers and connect `onImageModeChange` to it. Do not copy `imageGenerationMode` into a blank row or alter renderer code.

- [x] **Step 4: Run the focused test to verify it passes**

  Run `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "blank image mode inherits"`.

  Expected: PASS.

### Task 3: Pin edited content/image values and flip per-field badges

**Files:**
- Modify: `web/src/components/ParamForm.tsx`
- Modify: `web/src/components/SubquestionConfigCards.tsx`
- Test: `web/src/components/ParamForm.confirmation-display.test.tsx`

**Interfaces:**
- `updatePendingSubquestionContentType(questionIndex, subquestionIndex, contentType)` calls the generic updater with `content_type: contentType || undefined`.
- Both new editable card fields use green `form.confirm_badge_user` when their row value is present and amber `form.confirm_badge_random` when absent; their blank select option remains `form.confirm_inherit_text` because an empty value means inheritance, not a materialised request-level value.

- [x] **Step 1: Write the failing per-題組 edit test**

  Edit content type and image mode in one 小題 of the first of two 題組, assert both badges flip to user-selected while sibling cards remain amber, and assert 確認送出 places both values in only the matching first `subquestion_configs` row while preserving the existing instruction and limits.

- [x] **Step 2: Run the focused test to verify it fails**

  Run `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "content and image edits land"`.

  Expected: FAIL because content type has no pending updater and the new card fields do not yet receive badge/callback wiring for this assertion.

- [x] **Step 3: Add the content-type wrapper and badge-aware card fields**

  Add `updatePendingSubquestionContentType`, wire both callbacks into the confirmation card, and render each new shared field with the same green/amber badge semantics as #439. Keep the absent-callback static text for DraftSummary.

- [x] **Step 4: Run the focused test to verify it passes**

  Run `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "content and image edits land"`.

  Expected: PASS.

### Task 4: Prove untouched 小題 remain unchanged

**Files:**
- Test: `web/src/components/ParamForm.confirmation-display.test.tsx`

- [x] **Step 1: Write the failing untouched-row test**

  Provide distinct content/image/instruction/limit values across two 題組 and three 小題, edit only one first-row field, and assert every other row in both 題組 submits byte-equivalent parsed configuration values and retains its original badge/value.

- [x] **Step 2: Run the focused test to verify it fails**

  Run `cd web && npx vitest run src/components/ParamForm.confirmation-display.test.tsx -t "untouched 小題"`.

  Expected: FAIL before the generic patch path is verified by this case.

- [x] **Step 3: Run the test after the completed patch path**

  Run the same focused command and keep the existing field-agnostic updater if it passes; no special-case synchronization or confirmation metadata should be added.

### Task 5: Full verification and handoff

**Files:**
- Modify: files from Tasks 1–3 only, plus this plan if retained in the commit.

- [x] **Step 1: Run the whole web Vitest suite**

  Run `cd web && npm test -- --run` and require all tests to pass.

- [x] **Step 2: Run TypeScript verification**

  Run `cd web && npx tsc -b --noEmit` and require a clean exit.

- [x] **Step 3: Run lint and inspect touched-file scope**

  Run `cd web && npm run lint`, record only the six pre-existing errors named in the issue if they remain, and run ESLint on touched files to ensure no new errors.

- [x] **Step 4: Inspect the final diff and commit**

  Confirm only the intended shared fields, card callbacks, ParamForm wrappers, locale labels, focused tests, and plan are changed. Commit with `feat: make confirmation subquestion selects editable (#440)` and do not push, open a PR, or merge.
