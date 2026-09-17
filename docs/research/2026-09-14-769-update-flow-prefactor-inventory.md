# 2026-09-14 — Issue #769 Update-Flow Prefactor Inventory

**Branch:** `docs/728-adr-action-feedback-motion` (HEAD `fffdcfa`)
**Author:** research agent (phwu@mail.naer.edu.tw)
**Question source:** GitHub issue #769 "前置整理：集中更新前的工作狀態與生成受理接點"

---

## 1. Where the OpenSpec Change Lives

### OpenSpec workspace

The canonical OpenSpec workspace lives at `/workspace/openspec`. It currently contains
two in-progress changes under `changes/`:

| Path | Change |
|------|--------|
| `changes/fix-history-reload-curriculum-stage-race/` | History-reload LC/LP stage-race fix |
| `changes/split-default-model-tiers/` | Split default model tiers across providers |

Neither directory is named `frontend-build-update-flow`. No copy of that change slug
was found under `/workspace/openspec/` or `/workspace/eg-wt/`.

A sibling directory `/workspace/openspec/769-update-flow-prefactor` exists as a path
on the filesystem but its contents could not be listed (the `ls` command returned
exit code 2 with no output), so no spec file there was readable at research time.

### Git log

`git log --all --grep "frontend-build-update-flow"` and
`git log --all --grep "update-flow"` returned no commits in the checked-out repo.

### GitHub issue family

Searching issues for "更新" created around 2026-09-14 (via `gh issue list --search`)
returned the following eleven issues, all filed on 2026-09-14 by `paulpengtw-aiagent`
with labels `P1, ready-for-agent`:

| # | Title | Blocks / Blocked-by |
|---|-------|---------------------|
| **769** | 前置整理：集中更新前的工作狀態與生成受理接點 | Blocking #771, #772 |
| **770** | 讓長開分頁辨識已發布版本並顯示更新提示 | Blocking #771, #772 |
| **771** | 舊版本出題請求被拒收時，保留發送前確認與既有結果 | Blocked by #762, #742, #770, #769; Blocking #778 |
| **772** | 儲存未送出的輸入後更新，並驗證原表單可還原 | Blocked by #770, #769; Blocking #773, #774, #776 |
| **773** | 更新後保留發送前確認、確認頁修改與預抽結果 | Blocked by #772; Blocking #777 |
| **774** | 更新後保留已收到的題目、圖片與未知狀態 | Blocked by #772; Blocking #775 |
| **775** | 更新後保留人工審題修正的圈選與修改指示 | Blocked by #774; Blocking #777 |
| **776** | 讓更新還原跨登入失效與多分頁時仍歸屬正確 | Blocked by #772; Blocking #777 |
| **777** | 安全排程更新，並防止空白頁與載入失敗反覆重整 | Blocked by #773, #775, #776; Blocking #779 |
| **778** | 讓所有生成入口依同一發布版本受理請求 | Blocked by #741, #771; Blocking #779 |
| **779** | 驗收三科安全更新與發布／回滾，交付可審閱證據 | Blocked by #755, #778, #777 (label: headed environment) |

**What #769's slice is and is not:** #769 is the pure inventory/prefactor layer. It
does not implement the update trigger, build-version metadata, or admission gating —
those are #770, #778. It does not implement cross-session snapshot portability (#772,
#773, #774) or scheduled update logic (#777). Its output is the set of seams
(participation definitions, operation registry, form/confirmation/result export
adapters, and the submitting/admitted/rejected outcome split) that every downstream
issue depends on.

---

## 2. Inventory of Editable State per Surface

### 2a. GeneratePage (`web/src/pages/GeneratePage.tsx`)

GeneratePage holds a thin shell of state; its form state lives entirely in ParamForm.

| State | Type | Owner | Persisted? | Restored via |
|-------|------|-------|-----------|--------------|
| `hasUnsubmittedInput` | `boolean` | GeneratePage:73 | No | `onUnsubmittedInput` callback from ParamForm |
| `pendingAction` | `PendingAction \| null` | GeneratePage:74 | No | n/a |
| `requestedTotal` | `number` | GeneratePage:71 | No | Reset to 0 on `handleReset` |
| `submittedSubQuestionCount` | `number \| null` | GeneratePage:72 | No | Reset on `handleReset` |
| `prefillParams` | `Record<string,unknown> \| null` | GeneratePage:47 (from `location.state`) | Via router location.state | Navigate to `/generate/<subject>` with `state: { prefillParams: ... }` |

The `displayResults` and `status` arrays live in `useGenerate` (delegated).

### 2b. ParamForm (`web/src/components/ParamForm.tsx`)

**Primary form fields** — all collected in one `formFields` / `formSnapshot` state
object (`FormFields`) initialized at lines ~1300–1385:

| Field | Type | Persisted | Restored via |
|-------|------|-----------|--------------|
| `grade` | `number \| ""` | Draft + history prefill | `loadDraft` / `fromInit` |
| `style` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `contentType` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `customContentType` | `string` | Draft only | `loadDraft` |
| `context` | `string[]` | Draft + history prefill | `loadDraft` / `fromInit` |
| `setType` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `qType` | `string[]` | Draft + history prefill | `loadDraft` / `fromInit` |
| `count` | `number` | Draft + history prefill | `loadDraft` / `fromInit` |
| `coverageMode` | `"balanced"\|"random"` | Draft + history prefill | `loadDraft` / `fromInit` |
| `skipVerify` | `boolean` | Draft + history prefill | `loadDraft` / `fromInit` |
| `disableReferenceFewshot` | `boolean` | Draft + history prefill | `loadDraft` / `fromInit` |
| `coreQuestionCallback` | `boolean` | Draft + history prefill | `loadDraft` / `fromInit` |
| `imageGenerationMode` | `"html"\|"gpt_image"` | Draft + history prefill | `loadDraft` / `fromInit` |
| `difficulty` | `""\|"easy"\|"medium"\|"hard"` | Draft + history prefill | `loadDraft` / `fromInit` |
| `reportingScale` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `subjectFilter` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `passage` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `textWordLimit` | `number \| null` | Draft + history prefill | `loadDraft` / `fromInit` |
| `textInstruction` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `options` | `string[]` | Draft + history prefill | `loadDraft` / `fromInit` |
| `topic` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `coreQuestion` | `string \| null` | Draft + history prefill | `loadDraft` / `fromInit` |
| `subContext` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `scienceCompetency` | `string[]` | Draft + history prefill | `loadDraft` / `fromInit` |
| `learningPerformance` | `string[]` | Draft + history prefill | `loadDraft` / `fromInit` |
| `learningContent` | `string[]` | Draft + history prefill | `loadDraft` / `fromInit` |
| `subQuestionCount` | `number \| ""` | Draft + history prefill | `loadDraft` / `fromInit` |
| `subquestionConfigs` | `SubQuestionConfig[]` | Draft + history prefill | `loadDraft` / `subquestionConfigsFromInit` |
| `contentDomain` | `string` | Draft + history prefill | `loadDraft` / `fromInit` |
| `targetSurface` | `"紙本"\|"數位"` | Draft + history prefill | `loadDraft` / `fromInit` |
| `modelPlan` | `string` | localStorage directly (`model_plan`) + draft | `localStorage.getItem` at init |
| `modelExecute` | `string` | localStorage directly (`model_execute`) + draft | `localStorage.getItem` at init |
| `modelVerify` | `string` | localStorage directly (`model_verify`) + draft | `localStorage.getItem` at init |
| `modelCorrect` | `string` | localStorage directly (`model_correct`) + draft | `localStorage.getItem` at init |
| `effortPlan` | `string` | localStorage directly (`effort_plan`) + draft | `localStorage.getItem` at init |
| `effortExecute` | `string` | localStorage directly (`effort_execute`) + draft | `localStorage.getItem` at init |
| `effortVerify` | `string` | localStorage directly (`effort_verify`) + draft | `localStorage.getItem` at init |
| `effortCorrect` | `string` | localStorage directly (`effort_correct`) + draft | `localStorage.getItem` at init |
| `allowDuplicateFigureKinds` | `boolean` | Draft + history prefill | `loadDraft` / `fromInit` |

**Confirmation-screen / resolver state** (not persisted in draft):

| State | Type | Lines | Notes |
|-------|------|-------|-------|
| `pendingParams` | `FormParams \| null` | 1257 | Resolved payload for 發送前確認; cleared on send |
| `pendingPerQuestionParams` | `Record<string,unknown>[] \| null` | 1258 | Per-題組 override rows |
| `clearedPaths` | `string[]` | 1262 | Paths the resolver removed |
| `hasPendingConfirmationEdits` | `boolean` | 1263 | True when 確認頁修改 are outstanding |
| `resolverLoading` | `boolean` | 1264 | Resolver in-flight |
| `resolverError` | `string \| null` | 1265 | Resolver error display |
| `confirmInvalidFields` | `Map<string,true>` | 1266 | Gates 確認送出 button |
| `coreQuestionResolution` | `"idle"\|"loading"\|"generated"\|"failed"` | 1267 | 核心問題 planning state |
| `promptPreviews` | `PromptPreview[]` | 1268 | 提示詞預覽 results |
| `stalePreviewIndices` | `Set<number>` | 1281 | Which 題組 previews are stale |
| `previewRefetchLoading` | `boolean` | 1279 | Preview re-fetch in-flight |

**Draft lifecycle state:**

| State | Type | Lines | Notes |
|-------|------|-------|-------|
| `draftToRestore` | `FormDraft \| null` | 1293 | Offer shown until user chooses |
| `historyDraftChoice` | `"draft"\|"history"\|"defaults"\|null` | 1296–1299 | Three-way choice when both exist |
| `defaultsReady` | `boolean` | 1383 | Gates draft-restore prompt display |
| `defaultsSnapshotRef` | `useRef<FormFields\|null>` | 1385 | Snapshot of form at defaults-ready time for dirty detection |

**Schema / model state:**

| State | Type | Lines | Notes |
|-------|------|-------|-------|
| `schemas` | `Schemas \| null` | 1255 | Subject schemas; null while loading |
| `models` | `AvailableModels \| null` | 1270 | Server model list |
| `modelsResolved` | `boolean` | 1271 | True after getAvailableModels() completes |

### 2c. HistoryPage (`web/src/pages/HistoryPage.tsx`)

No user-editable form state. Read-only list with filter controls:

| State | Type | Lines | Notes |
|-------|------|-------|-------|
| `data` | `HistoryListResponse \| null` | 35 | Fetched list; null while loading |
| `error` | `string \| null` | 36 | Fetch error |
| `offset` | `number` | 37 | Pagination |
| `subject` | `string` | 38 | Filter selection |

### 2d. HistoryDetail (`web/src/pages/HistoryDetail.tsx`)

No user-editable fields except through QuestionCard's annotation affordance.

| State | Type | Lines | Notes |
|-------|------|-------|-------|
| `detail` | `HistoryDetailPayload \| null` | 34 | Fetched detail; null while loading |
| `error` | `string \| null` | 35 | Fetch error |

### 2e. QuestionCard (`web/src/components/QuestionCard.tsx`) — 人工審題修正

| State | Type | Lines | Notes |
|-------|------|-------|-------|
| `annotations` | `ModificationAnnotation[]` | 432 | Text selections + instructions; cleared on result |
| `selectionError` | `string \| null` | 433 | Selection validation |
| `submitError` | `ModificationSubmitError \| null` | 434 | Pre-flight / submission error |
| `showSolution` | `boolean` | 429 | UI toggle; not editable payload |
| `modificationRun` (from `useModificationRun`) | hook | 436 | Status, result, error |

`annotations` is cleared automatically when `modificationRun.result` becomes non-null
(lines ~440–448: `useEffect` on `modificationRun.result`). It is not persisted.

---

## 3. Readiness / Hydration Signals

### GeneratePage

| Signal | Condition for "not ready" | Source |
|--------|---------------------------|--------|
| Auth token | `useAuthStore.getState().token === null` (redirected by `AuthGuard`) | `web/src/components/AuthGuard.tsx:8` |
| `prefillParams` | Always available synchronously from `location.state` | `GeneratePage.tsx:47` |
| ParamForm mounted | ParamForm always renders; its own hydration applies | see below |

GeneratePage delegates all form hydration to ParamForm. GeneratePage itself is
"hydrated" as soon as it mounts and auth passes.

### ParamForm

A ParamForm instance is **not fully hydrated** until all of the following are true:

| Condition | State variable | Source |
|-----------|---------------|--------|
| Schema loaded | `schemas !== null` | `ParamForm.tsx:1255`; set by `getSchemas()` at ~1727 |
| Models resolved | `modelsResolved === true` | `ParamForm.tsx:1271`; set at ~1936,1966 |
| `defaultsReady === true` | Both `schemas !== null` AND `modelsResolved` | `ParamForm.tsx:1383,1461` — gate: `if (modelsResolved && !defaultsReady) setDefaultsReady(true)` |
| Draft/history conflict resolved | `hasDraftHistoryConflict === false` OR user has chosen | `ParamForm.tsx:~1463–1465` — `hasDraftHistoryConflict = draftToRestore !== null && hasInitialParams && historyDraftChoice === null` |
| Draft restore prompt dismissed | `showDraftPrompt === false` | `ParamForm.tsx:~1500–1507` — visible when `draftToRestore !== null && defaultsReady && !hasInitialParams && !hasUserEditedRef.current` |

`defaultsReady` is the single public gate the draft-restore prompt tests against
(`ParamForm.tsx:~1503`). Until `defaultsReady` is true the form is in an intermediate
state where the draft prompt should not appear and draft saving should not fire.

**Session renewal at mount:** `renewSessionIfNeeded(() => cancelled)` is called in a
`useEffect` at `ParamForm.tsx:1448` with no dependency array (runs once on mount). This
is fire-and-forget (errors swallowed). The form is usable regardless of whether this
resolves.

### HistoryDetail

| Signal | Condition for "not ready" |
|--------|--------------------------|
| `detail === null` | Data not yet fetched (or fetch in flight) — renders spinner text only |
| `error !== null` | Fetch failed — annotation affordances not shown |

HistoryDetail is "not ready" whenever `detail === null && error === null`. The
`QuestionCard` and download/regenerate controls are only rendered when `detail` is
non-null (lines 129–183).

### Auth store token hydration

`useAuthStore` is a Zustand store initialized synchronously from `localStorage` at
module load time (`authStore.ts:38–39`: `token: readPersistedToken()`). There is no
async hydration step; the token is available immediately on first render. `AuthGuard`
redirects to `/` synchronously if `isAuthenticated()` is false.

---

## 4. Active Operations Inventory

### 4a. Generation stream (`useGenerate`)

| Aspect | Detail |
|--------|--------|
| Start | `generate(params)` called from `GeneratePage.handleSubmit` |
| In-flight marker | `status === "generating"` (`useGenerate.ts:519`) |
| AbortController | `controllerRef.current` (`useGenerate.ts:528`); new controller per call, previous aborted immediately |
| Sequence pattern | None (single `controllerRef`; old stream is imperatively aborted before new one starts) |
| Completion | `"done"` SSE event sets `status = "idle"`, records `finishedAt`, aborts controller |
| Error | `"error"` SSE event or `onerror` sets `status = "error"`, records `finishedAt` |
| Abort user-visible? | Aborting via 清除 button shows confirm dialog before calling `handleReset()` which calls `reset()` which calls `controllerRef.current?.abort()` |
| `startedAt` / `finishedAt` | Set at start; `finishedAt` set on done/error/onerror (lines 586, 617, 635, 796, 814) |

### 4b. 人工審題修正 (`useModificationRun` + QuestionCard)

| Aspect | Detail |
|--------|--------|
| Start | `QuestionCard.handleSubmit` → `modificationRun.start(batch)` |
| Admission | `submitModificationBatch(activeRecordId, batch)` → `admission.run_id`; this HTTP POST returning a `run_id` is the server-admission event (`useModificationRun.ts:~150`) |
| In-flight marker | `modificationRun.status === "running"` (`useModificationRun.ts` status state) |
| AbortController | `controllerRef.current` in `useModificationRun`; aborted on `start` call and on unmount |
| Sequence pattern | `runSequenceRef` (`useModificationRun.ts:~122`); every start increments it; callbacks check `isCurrent()` |
| Completion | `"done"` SSE event with a result payload → `status = "completed"`, result stored |
| Error | `"error"` SSE event or `onerror` → `status = "error"` |
| Abort user-visible? | No UI to cancel mid-run; unmount aborts silently |

### 4c. 核心問題 planning (`planCoreQuestions`)

| Aspect | Detail |
|--------|--------|
| Start | Triggered by `useEffect` at `ParamForm.tsx:~1623` when `coreQuestionResolution === "loading"` |
| In-flight marker | `coreQuestionResolution === "loading"` |
| AbortController | No — uses `cancelled` boolean ref pattern |
| Sequence pattern | None; cancelled via `let cancelled = false` closure |
| Completion | Sets `coreQuestionResolution = "generated"` and updates `pendingParams/pendingPerQuestionParams` |
| Error | Sets `coreQuestionResolution = "failed"` |
| User-visible abort? | No |

`coreQuestionResolution` is also checked as a gate in the preview-fetch effect
(`ParamForm.tsx:1566`: `if (coreQuestionResolution === "loading") return`).

### 4d. 預抽 / resolver (`resolveForConfirmation`)

| Aspect | Detail |
|--------|--------|
| Start | `ParamForm.handleSubmit` → `resolveForConfirmation(payload, {}, false)` |
| In-flight marker | `resolverLoading === true` (ParamForm:1264) |
| AbortController | None — uses `resolveRequestSeqRef` sequence counter (ParamForm:1287) |
| Sequence counter | `resolveRequestSeqRef` (ParamForm:1286): incremented on each call; stale callbacks check `if (sequence !== resolveRequestSeqRef.current) return` |
| Last-request ref | `resolveRequestRef` (ParamForm:1281–1286): stores `{ payload, redraws, rebuildSubquestionSlots }` for `retryResolver` |
| Retry | `retryResolver()` re-calls `resolveForConfirmation` with stored ref if `resolverLoading` is false |
| Completion | `storeResolvedResponse` → sets `pendingParams`, `pendingPerQuestionParams`, clears `resolverLoading` |
| Error | Sets `resolverError` string, clears `resolverLoading` |

`storeResolvedResponse` (`ParamForm:2278`) clears `previewRequestedRef.current = false`
and `promptPreviews` so a fresh preview fetch runs after resolution.

### 4e. 提示詞預覽 (`previewGenerate`)

There are two preview-fetch effects:

**Initial preview** (ParamForm:~1565–1580): fires when `pendingParams` becomes non-null
and `coreQuestionResolution !== "loading"`. Uses `previewRequestedRef` boolean to
fire once per confirmation open. No abort controller; `cancelled` boolean. No
sequence counter beyond `previewRequestedRef`.

**Debounced re-fetch after 確認頁修改** (ParamForm:~1582–1620): fires when
`hasPendingConfirmationEdits` is true. Uses `previewRefetchSeqRef` (ParamForm:1278)
as sequence counter; 500 ms debounce via `setTimeout`. Stale previews tracked per-題組
in `stalePreviewIndices` (ParamForm:1281).

**Manual retry** `retryPreviewFetch()` (ParamForm:2886–2910): user-triggered; increments
`previewRefetchSeqRef`; available when `stalePreviewIndices.size > 0 &&
!previewRefetchLoading`. In-flight marker: `previewRefetchLoading`.

None of these hold an AbortController. Staleness/abort is handled by sequence-counter
comparisons. Failures are user-invisible except for the stale badge on affected 題組.

### 4f. ODT export (`buildExamOdt`)

| Surface | Handler | In-flight marker |
|---------|---------|-----------------|
| GeneratePage (all results) | `handleDownloadAllOdt` | None — fire-and-forget Promise |
| GeneratePage (per-card) | `QuestionCard.handleDownloadOdt` | None |
| HistoryDetail (per-card) | `QuestionCard.handleDownloadOdt` | None |

No AbortController, no status state, no user-visible in-flight indication. The
export is synchronous relative to the user action (Promise resolves quickly for small
batches).

### 4g. JSON / PNG download (QuestionCard lines 510–530)

`handleDownloadJson` and `handleDownloadPng` are fully synchronous (Blob construction
from in-memory data). No async, no abort, no state.

### 4h. Session renewal (`renewSessionIfNeeded`)

| Call site | Location | When |
|-----------|----------|------|
| Mount-time | `ParamForm.tsx:1448` | Once on ParamForm mount (with cancellation guard) |
| Submit-time | `ParamForm.tsx:2518` | Concurrent with `onSubmit(submittedParams)` in `handleConfirmSend` |

No AbortController; no in-flight state visible in UI. Fire-and-forget with
`.catch(() => undefined)`. On 401 during renewal, `apiFetch` calls `logout()` and
the signout reason/destination are saved for the login page banner.

### Existing sequence-counter patterns (for prefactor to reuse)

| Counter | File:line | Guards |
|---------|-----------|--------|
| `previewRefetchSeqRef` | `ParamForm.tsx:1278` | Preview re-fetch debounce + retry |
| `resolveRequestSeqRef` | `ParamForm.tsx:1286` | Resolver concurrency |
| `runSequenceRef` | `useModificationRun.ts:~122` | Modification run concurrency |

---

## 5. Submit vs Admitted vs Rejected in the Generation Flow

### Main generation flow

```
ParamForm.handleConfirmSend (ParamForm.tsx:2511)
  → clears draft, increments resolveRequestSeqRef (invalidates pending resolver)
  → calls onSubmit(submittedParams)          ← ParamForm.tsx:2529
  → GeneratePage.handleSubmit (GeneratePage.tsx:100)
      → [resubmit guard check — dormant, ADR 0010]
      → setRequestedTotal / setSubmittedSubQuestionCount
      → useGenerate.generate(generateParams)  ← GeneratePage.tsx:113
          ← useGenerate.ts:566
```

**Inside `generate()`** (useGenerate.ts:566–840):

| Step | What happens | State change |
|------|-------------|-------------|
| Synchronous on call | `setStatus("generating")`, `setStartedAt(Date.now())`, `setFinishedAt(null)`, clear results/progress | status → "generating" |
| HTTP request sent | `fetchEventSource("/api/generate", { method: "POST", ... })` | — |
| `onopen` — non-OK, 401 | `useAuthStore.getState().logout()`, `setErrorMessage(msg)`, `setFinishedAt(Date.now())`, throw `FatalStreamError` | status stays "generating" until `onerror` fires, then → "error" |
| `onopen` — non-OK, other (e.g. 422) | Reads JSON body, formats `detail` via `formatHttpErrorDetail`, `setErrorMessage(msg)`, `setFinishedAt(Date.now())`, throw `FatalStreamError` | status → "error" via onerror |
| `onopen` — OK | No state change (connection admitted by TCP/HTTP layer, not yet SSE-admitted) | — |
| `"started"` SSE event | `setStatus("generating")` (no-op, already "generating") | **SSE-admitted** |
| `"error"` SSE event | `setErrorMessage(...)`, `setStatus("error")`, `setFinishedAt(Date.now())` | status → "error" |
| `"done"` SSE event | `setStatus("idle")`, `setFinishedAt(Date.now())`, abort controller | status → "idle" |
| `onerror` | `setErrorMessage(...)`, `setStatus("error")`, `setFinishedAt(Date.now())`, rethrow | status → "error" |

**Key gap for #769:** There is no distinct "submitting" state between `generate()` being
called and `onopen` completing. `status === "generating"` covers both the HTTP request
flight and the streaming phase. The `"started"` SSE event is server-admission but only
sets the same `"generating"` status. A finer-grained outcome (`"submitting"` /
`"admitted"` / `"rejected"`) would need to be added alongside (not replacing) the
existing `GenerateStatus` type.

**`GenerationStatusBar` derivation** (GeneratePage.tsx:147–155):

```ts
const runState: RunState =
  status === "error"
    ? "error"
    : status === "generating"
      ? "running"
      : startedAt !== null && finishedAt !== null
        ? "done"
        : "idle";
```

`RunState` is `"idle" | "running" | "done" | "error"` (GenerationStatusBar.tsx:44).
Changing `GenerateStatus` does not automatically change `RunState`; the derivation
expression would need updating for any new outcome.

### 人工審題修正 flow

```
QuestionCard.handleSubmit
  → modificationRun.start(batch)              ← useModificationRun.ts:133
      → submitModificationBatch(activeRecordId, batch)   ← HTTP POST
          ← admission = { run_id: string }     ← SERVER ADMISSION
      → fetchEventSource(.../${run_id}/stream)
```

`submitModificationBatch` returning a `run_id` is the explicit admission event. The
`start` function propagates `status = "running"` before the POST, so "submitting" and
"running" are also collapsed here. There is no "rejected" outcome modeled other than
through `setError + setStatus("error")`.

---

## 6. Guards and Their Inputs

### Navigation guard (in-page exits)

**Inputs:** `hasUnsubmittedInput`, `hasResults` (GeneratePage.tsx:159–161)

**Trigger:** `handleNavigation(target)` — called from back-arrow button and history
link. If either input is true, sets `pendingAction = { kind: "navigate", target }`;
otherwise calls `navigate(target)` immediately.

**Tests:** `GeneratePage.navigation-guard.test.tsx` — 12 cases covering:
immediate navigation on pristine form, modal appearance on edit/results, confirmation
body copy variants (params only / results only / both), cancel/confirm paths, Esc
cancel.

### Back guard (useBlocker, ADR 0008, ADR 0013)

**Inputs:** `hasUnsubmittedInput`, `hasResults`, `historyAction === "POP"` (GeneratePage.tsx:76–79)

**Trigger:** React Router `useBlocker` intercepts history-pop events. The
`effectivePending` derivation at GeneratePage.tsx:84 falls through to
`{ kind: "back" }` when `blocker.state === "blocked"`.

**Tests:** `GeneratePage.back-guard.test.tsx` — 7 cases covering: no-guard on
untouched form, blocking on input/results, cancel keeps page, re-blocking after
cancel, confirming proceeds, confirming in-page exit does not double-block.

### Beforeunload guard

**Inputs:** `hasUnsubmittedInput`, `hasResults` (GeneratePage.tsx:87–94)

**Trigger:** `beforeunload` event handler added when either input is true; removed when
both become false.

**Tests:** `GeneratePage.unload-guard.test.tsx` — 4 cases covering: warns with
unsubmitted input, no warn on clean form, warns with results, handler removed on
unmount.

### Logout confirm

**Inputs:** Always triggers (GeneratePage.tsx:270–315). Body additionally lists work
loss when `hasUnsubmittedInput || hasResults`.

**Trigger:** Logout button → `setPendingAction({ kind: "logout" })`.

**Tests:** Inside `GeneratePage.navigation-guard.test.tsx` (describe "logout
confirmation") — 5 cases.

### Clear-results confirm

**Inputs:** `status === "generating"` (adds streaming-interruption warning). `hasResults`
gates whether the button is shown.

**Tests:** `GeneratePage.clear-results-guard.test.tsx` — 8 cases.

### Resubmit guard (ADR 0010)

**Inputs:** `status === "generating"` in `handleSubmit` (GeneratePage.tsx:108).

**Status:** Dormant — both submit buttons are `disabled` when `status === "generating"`.
Guard code kept as belt-and-braces (ADR 0010).

**Tests:** `GeneratePage.resubmit-guard.test.tsx` — covers the handler-level guard
even though unreachable from UI.

### Summary table

| Guard | Reads | Test file |
|-------|-------|-----------|
| Navigation (in-page exits) | `hasUnsubmittedInput`, `hasResults` | `GeneratePage.navigation-guard.test.tsx` |
| Back (useBlocker) | `hasUnsubmittedInput`, `hasResults`, `historyAction` | `GeneratePage.back-guard.test.tsx` |
| Beforeunload | `hasUnsubmittedInput`, `hasResults` | `GeneratePage.unload-guard.test.tsx` |
| Logout confirm | `hasUnsubmittedInput`, `hasResults` | `GeneratePage.navigation-guard.test.tsx` |
| Clear-results confirm | `hasResults`, `status` | `GeneratePage.clear-results-guard.test.tsx` |
| Resubmit (dormant) | `status` | `GeneratePage.resubmit-guard.test.tsx` |

---

## 7. Existing Tests That Must Stay Green

### How to run

From `web/`:
```
npx tsc -b --noEmit     # type-check
npm run lint            # eslint
npm test                # vitest run (all 103 test files)
```

`node_modules` exists in `web/` (confirmed: `ls web/node_modules` returns entries).
Tests can be run locally without a network install.

### Test file registry

| Test file | What it asserts |
|-----------|----------------|
| `web/src/lib/formDraft.test.ts` | `saveDraft`/`loadDraft` round-trip, backward-compat field normalization (textInstruction, reportingScale, coreQuestionCallback, allowDuplicateFigureKinds), 7-day expiry, per-user isolation |
| `web/src/pages/GeneratePage.history-prefill.test.tsx` | History prefill with saved draft conflict: choosing history over draft, aborted-run payload reload, partial-payload prefill notice |
| `web/src/components/ParamForm.draft-restore.test.tsx` | Draft restore prompt shown, field restoration on click, 重新開始 clears draft, no prompt when no draft, route-prefill suppresses draft, no resave of untouched restored fields |
| `web/src/components/ParamForm.draft-persistence.test.tsx` | Draft saves after 1 s of typing, no save on untouched form, debouncing, no save on model-reconciliation-only changes, saves user input during pending model discovery, never persists 確認頁修改 |
| `web/src/components/ParamForm.draft-generation.test.tsx` | Draft cleared on confirmed send, pending save cancelled on confirmed send, no recreation after model discovery |
| `web/src/components/ParamForm.draft-vs-history.test.tsx` | Three-way dialog with draft vs. history, choosing each option, starting from defaults, using history without saved draft |
| `web/src/pages/GeneratePage.back-guard.test.tsx` | useBlocker behavior, 7 cases (see §6) |
| `web/src/pages/GeneratePage.navigation-guard.test.tsx` | In-page navigation + logout confirm, 12+ cases (see §6) |
| `web/src/pages/GeneratePage.unload-guard.test.tsx` | beforeunload behavior, 4 cases (see §6) |
| `web/src/pages/GeneratePage.resubmit-guard.test.tsx` | Dormant resubmit guard, handler-level |
| `web/src/pages/GeneratePage.clear-results-guard.test.tsx` | Clear-results confirm, 8 cases |
| `web/src/components/ParamForm.session-renewal.test.tsx` | Mount-time session renewal: refreshes within threshold, no-op when plenty of time, swallows 401, no repeated scheduling, unauthenticated skips |
| `web/src/components/ParamForm.session-renewal-submit.test.tsx` | Submit-time session renewal: refreshes when near threshold, skips when plenty of time, proceeds on refresh failure, fires exactly once from submit path |
| `web/src/lib/sessionRenewal.test.ts` | `shouldRenew` logic: threshold comparison, server-time independence |
| `web/src/lib/sessionRenewal.signout.test.ts` | 401 sign-out behavior: saves reason + destination for /generate routes, skips destination for other routes, 30day_limit path, non-401 errors do not save state |
| `web/src/hooks/useGenerate.test.ts` | Trail accumulation, run timestamps (start/clear/finish/error/onerror/onopen-fail), subQuestionTotal plan event, model/effort overrides in buildQueryString, parseErrorEventData |
| `web/src/api/generate-transport.test.tsx` | POST stream cancellation, 422 rejection with field address, nested field validation message |
| `web/src/pages/HistoryDetail.test.tsx` | Stored question render, download, 重新帶入 params, latest record identity from modification, verification trail, figure-policy trail, download clean of trail, failed/aborted renders, reference-example-record in failed/aborted panels, figure-policy degradation badge |
| `web/src/pages/HistoryDetail.annotation.test.tsx` | No-trail state, verified record annotation affordances, `not_latest_version` pre-flight rejection |
| `web/src/pages/HistoryDetail.reference-record.test.tsx` | Failed detail with/without record, aborted detail with disabled record |
| `web/src/components/QuestionCard.test.tsx` | Draft card rendering, agent 自主驗證修正歷程 collapse/expand, 圖像種類 degradation warnings, FigureRenderer swap |
| `web/src/components/QuestionCard.lifecycle.test.tsx` | 人工審題修正 run stage sequence, question update in place, failure details, submit enable/disable |
| `web/src/components/ParamForm.preview-refetch.test.tsx` | 確認頁修改 preview re-fetch debounce, loading indicator, stale badge, retry (6 cases) |

---

## 8. Repo Conventions Relevant to the Change

### ADR format

All Architecture Decision Records live in `docs/adr/` as numbered markdown files
(`0001-…md` through `0029-…md`). Each states the decision, considered alternatives, and
consequences. Behavior-preserving refactors and guard designs reference ADRs directly
in source comments (e.g. `GeneratePage.tsx:98`: `// See docs/adr/0010-...`).

The ADR relevant to this prefactor are:
- `0008-navigation-guarding-requires-the-data-router.md` — useBlocker contract
- `0010-the-resubmit-guard-is-dormant-by-design.md` — do not delete dormant guard
- `0013-the-back-guard-blocks-only-history-navigation.md` — historyAction === "POP"
- `0018-every-drawn-value-is-resolved-before-confirmation.md` — resolver invariant
- `0019-the-resolve-step-is-one-pure-function.md` — resolver purity

### Plan format

Implementation plans live in `docs/superpowers/plans/` as markdown files with
checkbox task steps. The existing effort-tier plan is the reference for plan structure
and the TDD requirement.

### i18n message location

All i18n strings live in `web/src/i18n/messages.ts`. The file exports
`MESSAGES: Record<Lang, Record<string, string>>` where `Lang = "zh-TW" | "en-US"`.
Both locales must be kept in parity (enforced by `messages.statusbar.test.ts`).
New keys for any boundary labels or export adapter results must be added here, not
inline.

### ESLint rules that bite

`web/eslint.config.js` enables `reactHooks.configs.flat.recommended`. The rule
`react-hooks/rules-of-hooks` and `react-hooks/exhaustive-deps` are enforced. Several
`useEffect` blocks in ParamForm carry explicit `// eslint-disable-next-line
react-hooks/set-state-in-effect` comments where `setState` inside `useEffect` is
intentional (e.g. `ParamForm.tsx:1461`, `1693`). Any new effects that call setState
for async-fetch reasons should document the same suppression pattern.

### MEMORY.md

The repo has `MEMORY.md` at its root. It is committed and shared by all agents. It
carries durable gotchas (Playwright binary, worktree venv shebangs, uv sync flags,
NS corpus bucketing, renderer leak fix). If #769 produces durable findings about the
hydration model or boundary conventions, they should be appended to `MEMORY.md`.

---

## 9. Open Questions / Ambiguities

1. **What constitutes "page participation" as a data structure?**
   The issue says "define page participation for editable state, received results,
   readiness/hydration, and active operations." It is ambiguous whether this is a
   runtime object, a module export, or a documentation-only convention. *Conservative
   option:* a module-level exported constant or class per surface, with no runtime
   overhead, that describes the participation shape and is referenced by the
   later updater. Do not add a global registry or context unless #770 or #772 require
   it.

2. **Should `"submitting"` be a new `GenerateStatus` value or a separate atom?**
   Adding `"submitting"` to `GenerateStatus` changes the `runState` derivation in
   GeneratePage and every mock in the 103-file test suite that asserts `status === "idle"
   | "generating" | "error"`. *Conservative option:* introduce a separate
   `generationOutcome` atom (`null | "submitting" | "admitted" | "rejected"`) alongside
   the existing `status`, and derive it from `onopen` success/failure and the `"started"`
   event. Leave `GenerateStatus` and `RunState` unchanged.

3. **Where do export/import seams live — as React context, module functions, or prop callbacks?**
   "Narrow export/import seams" for form, confirmation, results, and annotation state
   could be prop-based callbacks (easiest, least coupling), React context (accessible
   to deeply nested surfaces), or module-level imperative adapters. *Conservative
   option:* prop-based callbacks or module-level functions that read/write a known
   state shape. Avoid context if the surface can wire directly.

4. **What is the boundary between "adapters exercised" and actual persistence?**
   The acceptance criteria say "adapters exercised without navigating or adding
   persistence." This means test coverage only, not a real save path to localStorage
   or a new API endpoint. *Conservative option:* unit tests that call the adapter with
   the current state shape and assert the snapshot is round-trippable.

5. **Does `useModificationRun` need a `"submitting"` phase?**
   The HTTP POST to `submitModificationBatch` is the admission gate. If the HTTP POST
   fails (server rejects the batch), the current code transitions to `status = "error"`
   without a distinct "rejected" state. For parity with the generation flow, a
   `"rejected"` outcome may be needed. *Conservative option:* add `"rejected"` as a
   terminal status alongside `"error"` only if #771 specifically requires distinguishing
   rejected-by-server from stream-error. Leave it as `"error"` otherwise.

6. **Which surfaces are "registered"?**
   GeneratePage, HistoryDetail (as QuestionCard host), and the confirmation panel
   (inside ParamForm) are the obvious candidates. HistoryPage (list view) has no
   user-editable state and is safe to reload unconditionally. *Conservative option:*
   only register surfaces that have user-editable state or active operations: GeneratePage
   and HistoryDetail.

7. **What happens to `previewRefetchSeqRef` and `resolveRequestSeqRef` on a prefactor boundary?**
   These counters currently live in ParamForm component scope. If the updater needs to
   observe "resolve in-flight" from outside ParamForm, the `resolverLoading` state
   would need to be lifted or exposed via a callback. *Conservative option:* expose
   `resolverLoading` via a new optional callback prop (e.g. `onResolverState`) rather
   than lifting the counter.

8. **Should `renewSessionIfNeeded` be in the operation registry?**
   It is not user-visible and is fire-and-forget. Including it would add noise; excluding
   it means an updater cannot know if a session check is in progress. *Conservative
   option:* exclude from the operation registry. It completes within seconds and has no
   side effects on the question workspace.

9. **Does the `annotations` state in QuestionCard need to survive a page reload?**
   The issue (#775) explicitly asks to preserve annotations across update. But #775 is
   blocked by #774, not #769. *Conservative option:* #769 only documents the annotation
   state shape (owner, fields) and provides the export adapter; persistence is left to
   #775.

---

*Research performed on branch `docs/728-adr-action-feedback-motion`, HEAD `fffdcfa`,
2026-09-14. No source or test files were modified.*
