# 前置整理：集中更新前的工作狀態與生成受理接點 (#769) — Design

**Source:** GitHub issue #769, the first slice of OpenSpec change `frontend-build-update-flow`
(siblings #770–#779 depend on the seams defined here; see
`docs/research/2026-09-14-769-update-flow-prefactor-inventory.md`).
**Kind:** behavior-preserving prefactor of the web frontend. No UI text, no SSE protocol
change, no persistence, no service worker, no refresh behaviour. Every existing guard fires
exactly when it fires today.

## Problem

A later updater (#770 detection, #771 admission by build, #772–#775 snapshot/restore, #777
scheduling) must answer three questions without reaching into component internals:

1. **Is work active?** Which surfaces are mounted, whether each is fully hydrated, whether it
   holds editable input, an open 發送前確認, received results, or unsent 人工審題修正
   annotations, and which long-running operations are in flight. #772 lists exactly these as
   the reasons a save-and-update must be refused.
2. **What is the workspace?** A narrow, typed export of the form, the 發送前確認 payload
   (with 預抽 provenance), the received results, and pending 人工審題修正 annotations, with
   a matching import adapter that validates and reconstructs the same state. #773–#775 extend
   these snapshots; #769 only defines them and proves round trips.
3. **Was the request admitted?** "The browser submitted" versus "the server accepted", for
   generation and 人工審題修正. #771 will keep the confirmation open until admission; #769
   only exposes the outcome.

Today `useGenerate.status` collapses submit and admission into `"generating"`; ParamForm's
核心問題 planning, 預抽 and 提示詞預覽 requests are private effects; exports run as
fire-and-forget promises; readiness is spread across `schemas`, `defaultsReady`,
`modelsResolved`, `draftToRestore`, `historyDraftChoice` in ParamForm and `detail === null`
in HistoryDetail.

## Design

### 1. Workspace registry — `web/src/lib/workspace/workspaceStore.ts`

One zustand store (same pattern as `store/authStore.ts`) holding plain data only.

```ts
export type SurfaceId =
  | "generate.form" | "generate.confirmation" | "generate.results"
  | "history.list" | "history.detail" | "history.modification";
export type SurfaceReadiness = "hydrating" | "restoring" | "ready";
// hydrating: async defaults/schemas/models/detail not loaded yet
// restoring: waiting for the user's draft-vs-History / draft-restore choice (#772 "pending restoration")
export interface SurfaceParticipation {
  id: SurfaceId;
  readiness: SurfaceReadiness;
  hasEditableState: boolean;   // unsaved user input / open 發送前確認 / unsent annotations
  hasReceivedResults: boolean; // received results or a received replacement question
  exportWorkspace?: () => WorkspaceSnapshot | null;   // export seam (section 3)
}
export type OperationKind =
  | "generation" | "modification" | "core_question_planning" | "resolve"
  | "prompt_preview" | "export_odt" | "export_image" | "export_json";
export type OperationOutcome = "completed" | "failed" | "aborted" | "superseded";
export interface ActiveOperation { id: number; kind: OperationKind; surface: SurfaceId; startedAt: number }
export interface OperationHandle { readonly id: number; end(outcome: OperationOutcome): void }

interface WorkspaceState {
  surfaces: Partial<Record<SurfaceId, SurfaceParticipation>>;
  operations: ActiveOperation[];
  registerSurface(p: SurfaceParticipation): () => void;  // returns unregister
  updateSurface(id: SurfaceId, patch: Partial<Omit<SurfaceParticipation, "id">>): void;
  beginOperation(kind: OperationKind, surface: SurfaceId): OperationHandle;
}
export type RefreshBlocker =
  | { kind: "no_surface" }
  | { kind: "hydrating" | "restoring" | "editable" | "results"; surface: SurfaceId }
  | { kind: "operation"; operation: OperationKind; surface: SurfaceId };
export function isRefreshSafe(state: WorkspaceState): { safe: boolean; blockers: RefreshBlocker[] };
export function useSurfaceParticipation(id: SurfaceId, p: Omit<SurfaceParticipation, "id">): void;
```

Rules:
- `end()` is idempotent; the store never holds an `AbortController`, promise, or callback
  that could cancel work. Observing (`getState()`, `subscribe`, selectors) is read-only by
  construction; a test proves a mocked in-flight fetch is never aborted by observation.
- `registerSurface` on an already-registered id replaces the entry (StrictMode-safe); the
  returned unregister removes only the entry it registered (a stale unregister after a
  re-register is a no-op).
- `isRefreshSafe`: zero registered surfaces → `no_surface` (the issue: an unregistered
  surface is unsafe). Every surface must be `ready`, hold no editable state and no results,
  and `operations` must be empty. Blockers are reported in that order, all of them, so the
  updater can explain a refusal. This slice does not act on the answer.
- `useSurfaceParticipation` registers on mount, patches when any value changes (compare by
  value; `exportWorkspace` by identity), unregisters on unmount.
- Call sites use `beginOperation` + `end` explicitly (no wrapper helper) so each outcome
  mapping is visible at the call site.

### 2. Admission outcomes

**`useGenerate`** gains
```ts
export type AdmissionState = "idle" | "submitting" | "admitted" | "rejected";
export type AdmissionOutcome = { outcome: "admitted" } | { outcome: "rejected"; reason: string };
admission: AdmissionState;
admissionError: string | null;   // reason when rejected
generate(params): Promise<AdmissionOutcome>;   // never rejects
```
Transitions are added beside (not instead of) the existing `setStatus`/`setErrorMessage`/
`setFinishedAt` calls, which do not move:
- `generate()` → `submitting` in the same tick as `setStatus("generating")`.
- `onopen` not ok (both the 401 logout path and the HTTP-detail path) → `rejected`,
  `admissionError = msg`, promise resolves `{ outcome: "rejected", reason: msg }`.
- SSE `started` → `admitted`, promise resolves `{ outcome: "admitted" }`.
- `onerror` while `submitting` → `rejected` with the error message; `onerror` after
  `admitted` leaves admission alone (`status` already reports `error`).
- SSE `error` / `done` do not change admission. `reset()` → `idle`, `admissionError = null`.
- A new `generate()` while one is live resets admission to `submitting` and resolves the
  superseded promise as rejected with reason `"superseded"` if it had not settled.
`GeneratePage.handleSubmit` returns the promise; `ParamForm` keeps calling `onSubmit` and
ignoring the return value, so 發送前確認 still closes synchronously on send until #771.
The `runState` derivation in GeneratePage and `GenerateStatus`/`RunState` types are
untouched.

**`useModificationRun`** gains `admission: AdmissionState` and `admissionError`:
`submitting` when `start()` runs, `admitted` when `submitModificationBatch` returns a
`run_id`, `rejected` when that call throws or returns no `run_id` (existing error message
unchanged), reset to `submitting` on the next `start()`. Stream failures after admission
keep `admitted`. `status` transitions are unchanged.

### 3. Export / import seams — `web/src/lib/workspace/adapters/`

Pure modules, one per surface: `export<X>Workspace(live) → snapshot` and
`import<X>Workspace(raw: unknown) → state | null` (null on any shape violation, never
throws). No localStorage, no router, no fetch, no navigation. Every snapshot carries
`{ kind, version: 1 }` so #772's recovery format can wrap them.

| Seam | Export input | Snapshot fields | Import output |
|---|---|---|---|
| form (`formWorkspace.ts`) | `FormFields` | `fields` | `FormFields` via `parseFormFields(raw)` — the type guard + normalisation extracted from `formDraft.loadDraft`; `loadDraft` is refactored to call it (existing formDraft tests pin equivalence) |
| confirmation (`confirmationWorkspace.ts`) | ParamForm `{ pendingParams, pendingPerQuestionParams, clearedPaths, redraws, hasPendingConfirmationEdits, coreQuestionResolution, historyDraftChoice }` | the same, `redraws` being the last resolver request's counters (`resolveRequestRef`) or `{}` | same shape, validated (pendingParams must be an object with `subject`; per-question rows an array of objects; paths string arrays) |
| results (`resultsWorkspace.ts`) | `useGenerate` state + GeneratePage `{ requestedTotal, submittedSubQuestionCount }` | `results, displayResults, progressLines, errorMessage, startedAt, finishedAt, subQuestionTotal, requestedTotal, submittedSubQuestionCount, completion: "settled" \| "error" \| "unknown"` (`settled` when finishedAt set and status idle, `error` when status error, else `unknown`). `llmCalls` are excluded (#774: no diagnostic-only provider payloads) | validated snapshot; applied via `useGenerate.restoreResults(snapshot): boolean` — refused (false, no state change) while `status === "generating"`; otherwise sets the fields, `status` = `"error"` if completion is `error` else `"idle"`, `admission = "idle"`, clears `llmCalls` |
| modification (`modificationWorkspace.ts`) | QuestionCard `{ recordId, questionId, annotations, replacement: modificationResult }` | the same (segments validated against `ModificationSegmentRequest`, instruction string) | validated `{ recordId, questionId, annotations, replacement }` |

Live wiring in this slice: every surface exposes `exportWorkspace` through its participation
entry; import is wired only where a hook already owns the state (`useGenerate.restoreResults`).
Feeding the form/confirmation/modification imports into mounted components is left to
#772/#773/#775 (no new props on ParamForm or QuestionCard for that).

### 4. Observed operations

| Kind | Where | begin | end |
|---|---|---|---|
| generation | `useGenerate.generate` | before `fetchEventSource` | `done` → completed; SSE `error` / `onerror` / onopen-reject → failed; `reset()` or unmount abort → aborted; superseded by a newer `generate()` → superseded |
| modification | `useModificationRun.start` | at start | `done` → completed; `error`/throw → failed; abort/unmount → aborted; older sequence → superseded |
| core_question_planning | ParamForm planning effect | when `planCoreQuestions` is called | then → completed (0 candidates → failed); catch → failed; cleanup with `cancelled` → aborted |
| resolve (預抽) | `ParamForm.resolveForConfirmation` | at sequence increment | current-sequence response → completed; stale sequence → superseded; catch → failed |
| prompt_preview | ParamForm initial preview effect, debounced refetch effect, `retryPreviewFetch` | when `previewGenerate` is called | then → completed; catch → failed; cleanup / stale sequence → superseded |
| export_odt | `GeneratePage.handleDownloadAllOdt`, `QuestionCard.handleDownloadOdt` | before `buildExamOdt` | then → completed; catch → failed (add a `.catch` that only ends the operation; no new UI) |
| export_json / export_image | `GeneratePage.handleDownloadAll`, `QuestionCard.handleDownloadJson/Png` | synchronous begin/end around the blob build | completed |

Session renewal is not an operation (not in the issue's list; it only touches the auth store).

### 5. Page participation

| Surface | Owner | `ready` when | `restoring` when | hasEditableState | hasReceivedResults |
|---|---|---|---|---|---|
| `generate.form` | ParamForm | `schemas !== null && defaultsReady && modelsResolved` and not restoring | `hasDraftHistoryConflict` or the draft-restore prompt is showing (`draftToRestore !== null` and no choice yet) | `hasUserEditedRef.current` mirrored into state, i.e. the same moment `onUnsubmittedInput` fires | false |
| `generate.confirmation` | ParamForm, registered only while `pendingParams !== null` | ready | — | true (an open 發送前確認 is editable state) | false |
| `generate.results` | GeneratePage | ready | — | false | `displayResults.length > 0` (identical to `hasResults`) |
| `history.list` | HistoryList | `data !== null \|\| error !== null` | — | false | false |
| `history.detail` | HistoryDetail | `detail !== null \|\| error !== null` | — | false | false |
| `history.modification` | QuestionCard when `recordId` is set | ready | — | `annotations.length > 0` | `modificationResult !== null` |

The guards keep reading `hasUnsubmittedInput`, `hasResults`, `status` exactly as now; the
registry is fed from the same values and never feeds back into them. A running
modification is reported as an operation, not as editable state.

## Tests (characterization)

- `lib/workspace/workspaceStore.test.ts`: register/patch/unregister; StrictMode double
  register and stale unregister; `isRefreshSafe` truth table incl. zero surfaces, each
  blocker kind, ordering; `beginOperation`/`end` idempotence; observing during a mocked
  in-flight fetch never calls `abort`.
- `hooks/useGenerate.test.ts` additions: admission for `started`, 401, 422, 500,
  onerror-before/after-started, reset, superseded run; promise resolution; `restoreResults`
  round trip, refusal while generating, completion mapping; operation begin/end outcomes.
  Existing `status`/`startedAt`/`finishedAt` assertions unchanged.
- `hooks/useModificationRun.test.ts` (new): admission transitions and operation outcomes.
- `components/ParamForm.workspace.test.tsx` (new): readiness flips after schemas + models +
  defaults; `restoring` while the draft/History choice is pending; editable flag on first
  edit; confirmation surface appears/disappears with 發送前確認; planning/resolve/preview
  operations begin and end with the right outcome, superseded resolve; confirmation export
  round trip through the adapter.
- `pages/GeneratePage.workspace.test.tsx` (new): results participation mirrors `hasResults`;
  export operations; `handleSubmit` returns the admission promise. Existing guard tests
  untouched and green.
- `pages/HistoryDetail.*` / `HistoryPage.*` / `components/QuestionCard.*` additions:
  readiness on load and on error; modification editable/results flags and export.
- `lib/workspace/adapters/*.test.ts`: export→import round trips; malformed input → null;
  `parseFormFields` equivalence with `loadDraft` on the existing fixtures.

## Out of scope (explicit)

SSE protocol changes; service worker / background recovery; any automatic refresh; build
identity headers (#771); new i18n strings; changing when any guard fires; persisting
snapshots; wiring import adapters into ParamForm/QuestionCard props.

## Documentation

- ADR `docs/adr/0030-workspace-participation-is-declared-by-each-surface.md`: a declared
  registry rather than inference from DOM/router; zero surfaces is unsafe; the registry
  holds no cancellation authority; admission is a separate atom beside `status`.
- `CONTEXT.md` glossary: 工作區參與 (surface participation), 受理 (admission), 可觀察作業
  (observed operation).
- `CLAUDE.md` (AGENTS.md is a symlink to it): a short "Workspace registry" subsection under
  Architecture Decisions.
