# History Reload Parameters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let every History detail record open the generator with its saved request parameters, including resolved per-question values, and keep the form clean until the user edits it.

**Architecture:** Keep HistoryDetail's existing router-state `prefillParams` handoff and ParamForm's existing history/draft arbitration. ParamForm will normalize saved wire arrays/nulls for visible controls and retain a validated `per_question_params` override snapshot for the next submit; when present, the snapshot is sent as pinned resolved values instead of being redrawn. Ordinary route prefill and draft persistence continue to use the same controls and save guard.

**Tech Stack:** React, TypeScript, React Testing Library, Vitest, existing i18n and router state, FastAPI history endpoint only if a missing field is demonstrated.

**Spec:** Issue #410 brief supplied in the task request; CONTEXT.md configuration terms and ADR 0001 / 0008 / 0010 / 0013 / 0014.

## Global Constraints

- Work directly on `feat/410-reload-params`; leave all changes uncommitted.
- Use one public-seam failing test, observe the failure, make the smallest implementation, and rerun green before the next behavior slice.
- Previously resolved values remain pinned on reload; do not restore random slots in the #411 sense.
- A route-prefilled form does not create `未送出的輸入` or a draft until a real user edit.
- Preserve saved records from before this feature by falling back to their shared request fields when no per-question snapshot exists.

---

### Task 1: HistoryDetail 重新帶入 action

**Files:**
- Modify: `web/src/pages/HistoryDetail.test.tsx`
- Modify: `web/src/pages/HistoryDetail.tsx`
- Modify: `web/src/i18n/messages.ts`

**Interfaces:**
- Consumes: `HistoryDetail.params_json`, `HistoryDetail.subject`, and `HistoryDetail.status`.
- Produces: a completed, failed, or aborted detail view with one enabled `重新帶入` action after loading; clicking it navigates to `/generate/<subject>` with the exact saved params in `location.state.prefillParams`.

- [x] Write one test covering completed and aborted fixtures at the component/router seam; assert the visible `重新帶入` action and exact topic carried in router state.
- [x] Run `cd web && npx vitest run src/pages/HistoryDetail.test.tsx -t '重新帶入'` and observe failure because the current copy is `帶入產生器重跑`.
- [x] Change the existing history action translation/copy to `重新帶入` (and the English equivalent) without changing its navigation handler or interrupted-view rendering.
- [x] Rerun the focused test and confirm both statuses pass.

### Task 2: 數學 resolved history prefill

**Files:**
- Create: `web/src/components/ParamForm.history-prefill.test.tsx`
- Modify: `web/src/components/ParamForm.tsx`
- Modify: `web/src/lib/formDraft.ts` only if the public prefill type needs a shared validator

**Interfaces:**
- Consumes: a history `params_json` object passed as `ParamForm.initialParams`, including wire arrays, nullable omitted controls, `per_question_params` JSON, `subquestion_configs`, word limits, and curriculum pools.
- Produces: a submit payload whose literal shared fields and parsed `per_question_params` equal the saved resolved values, with no fresh random pool/seed draw.

- [x] Add a math fixture with `count: 2`, distinct per-question seeds/styles/q types/learning pools, a saved text word limit, options, and a literal expected payload; submit through the real form and intercept `onSubmit`.
- [x] Run the single math test and observe failure because the current form redraws values and treats saved arrays as control values.
- [x] Add the smallest normalization for history wire values and a validated per-question override captured by the existing `initialParams` path; use it in the submit builder and mark loaded slots as user/pinned rather than auto-drawn.
- [x] Rerun the math test and confirm the expected literal payload passes.

### Task 3: 社會領域 各小題配置 and pools

**Files:**
- Modify: `web/src/components/ParamForm.history-prefill.test.tsx`
- Modify: `web/src/components/ParamForm.tsx`

**Interfaces:**
- Consumes: saved social-studies top-level pools plus one resolved `subquestion_configs` JSON string per question, including instruction, content/image type, all three word limits, and explicit LC/LP codes.
- Produces: the same shared fields and per-question config rows on submit, with each row preserved in order and no random replacement.

- [x] Add one failing social-studies test with two questions and three literal 各小題配置 rows per question, then run only that test.
- [x] Extend the existing history override mapping to preserve social rows and global fallback pools without adding a separate prefill path.
- [x] Rerun the social test and confirm the exact parsed rows and pools.

### Task 4: 自然科學 Reporting Scale, pools, and rows

**Files:**
- Modify: `web/src/components/ParamForm.history-prefill.test.tsx`
- Modify: `web/src/components/ParamForm.tsx`

**Interfaces:**
- Consumes: natural-sciences context/sub-context, science competency, Reporting Scale, LC/LP pools, and resolved per-小題 word limits/reporting scale/config rows.
- Produces: a successful submit payload matching the saved natural-sciences request and per-question resolution.

- [x] Add one failing natural-sciences test with literal shared and per-question values, then run only that test.
- [x] Extend the same override builder for natural-sciences-only fields and keep subject-specific form gates intact.
- [x] Rerun the natural-sciences test and confirm exact payload equality.

### Task 5: `未送出的輸入` and draft persistence semantics

**Files:**
- Modify: `web/src/components/ParamForm.history-prefill.test.tsx` or `web/src/components/ParamForm.draft-prefill.test.tsx`
- Modify: `web/src/components/ParamForm.tsx`

**Interfaces:**
- Consumes: route-prefilled history values and the existing `onUnsubmittedInput` / localStorage draft callbacks.
- Produces: no callback and no new draft save merely from hydration; after a real field edit, the callback fires and the edited snapshot is saved by the existing debounce.

- [x] Add one failing test that renders a signed-in route-prefilled form, waits past the debounce, asserts no callback and no new draft, edits a field, and asserts the callback plus saved edited field.
- [x] Gate the draft-save effect on the existing real-edit ref for history-prefilled mounts while leaving normal untouched/default and user-edited flows unchanged.
- [x] Rerun the focused test and the existing draft persistence/unsubmitted suites.

### Task 6: Requested verification

**Files:**
- Read-only verification of all modified files.

- [x] Run the new tests and all `ParamForm.*`, `HistoryDetail`, and `HistoryPage` test files.
- [x] Run `cd web && npx tsc -p tsconfig.app.json --noEmit`.
- [x] If backend files changed, run `uv run pytest tests/server -q`.
- [x] Run `git diff --check`, inspect `git status --short`, and report every file and exact test summary without committing.
