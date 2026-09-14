# Update-Flow Prefactor (#769) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a later updater a declared, observable picture of the 出題 and History surfaces (readiness, editable state, results, active operations), narrow export/import seams for the workspace, and an explicit submitting/admitted/rejected outcome for generation and 人工審題修正, without changing any user-visible behaviour.

**Architecture:** One zustand store (`web/src/lib/workspace/workspaceStore.ts`) holds plain participation and operation data; surfaces feed it through `useSurfaceParticipation` and `beginOperation`/`end`. Pure adapter modules under `web/src/lib/workspace/adapters/` define the snapshot shapes and validate imports. `useGenerate` and `useModificationRun` gain an `admission` atom beside their unchanged `status`.

**Tech Stack:** React 19, TypeScript, zustand 5, Vitest 4 + Testing Library, `@microsoft/fetch-event-source`.

**Spec:** `docs/superpowers/specs/2026-09-14-769-update-flow-prefactor-design.md`

## Global Constraints

- Behaviour-preserving: no i18n string added or changed; no change to when any guard (`useBlocker`, `beforeunload`, logout/clear/resubmit confirms) fires; `GenerateStatus`, `RunState`, `ModificationRunStatus` types unchanged; SSE protocol unchanged.
- No persistence: adapters never touch `localStorage`, the router, or `fetch`.
- The workspace store never stores an `AbortController`, promise, or callback that can cancel work.
- Every task: failing test first, minimal implementation, `npx vitest run <file>` green, then `npx tsc -b --noEmit` and `npm run lint` clean (run from `web/`), then commit.
- Existing suites must stay green: draft/history restoration, guards, session renewal, stream handling, export eligibility, 人工審題修正.
- `AGENTS.md` is a symlink to `CLAUDE.md`; edit only `CLAUDE.md`.

---

### Task 1: Workspace store, refresh-safety selector, participation hook

**Files:**
- Create: `web/src/lib/workspace/workspaceStore.ts`
- Create: `web/src/lib/workspace/useSurfaceParticipation.ts`
- Test: `web/src/lib/workspace/workspaceStore.test.ts`
- Test: `web/src/lib/workspace/useSurfaceParticipation.test.tsx`

**Interfaces (produced):**
```ts
export type SurfaceId = "generate.form" | "generate.confirmation" | "generate.results" | "history.list" | "history.detail" | "history.modification";
export type SurfaceReadiness = "hydrating" | "restoring" | "ready";
export interface SurfaceParticipation { id: SurfaceId; readiness: SurfaceReadiness; hasEditableState: boolean; hasReceivedResults: boolean; exportWorkspace?: () => WorkspaceSnapshot | null }
export type OperationKind = "generation" | "modification" | "core_question_planning" | "resolve" | "prompt_preview" | "export_odt" | "export_image" | "export_json";
export type OperationOutcome = "completed" | "failed" | "aborted" | "superseded";
export interface ActiveOperation { id: number; kind: OperationKind; surface: SurfaceId; startedAt: number }
export interface OperationHandle { readonly id: number; end(outcome: OperationOutcome): void }
export type RefreshBlocker = { kind: "no_surface" } | { kind: "hydrating" | "restoring" | "editable" | "results"; surface: SurfaceId } | { kind: "operation"; operation: OperationKind; surface: SurfaceId };
export interface WorkspaceState { surfaces: Partial<Record<SurfaceId, SurfaceParticipation>>; operations: ActiveOperation[]; registerSurface(p: SurfaceParticipation): () => void; updateSurface(id: SurfaceId, patch: Partial<Omit<SurfaceParticipation, "id">>): void; beginOperation(kind: OperationKind, surface: SurfaceId): OperationHandle }
export const useWorkspaceStore: UseBoundStore<StoreApi<WorkspaceState>>;
export function isRefreshSafe(state: Pick<WorkspaceState, "surfaces" | "operations">): { safe: boolean; blockers: RefreshBlocker[] };
export function resetWorkspaceStoreForTests(): void;
export function useSurfaceParticipation(id: SurfaceId, participation: Omit<SurfaceParticipation, "id">): void;
```
`WorkspaceSnapshot` is the union defined in Task 3 (`web/src/lib/workspace/adapters/types.ts`); Task 1 declares it as `import type { WorkspaceSnapshot } from "./adapters/types"` and Task 3 creates that file — to keep Task 1 compiling on its own, create `adapters/types.ts` in Task 1 with the four snapshot interfaces from Task 3's interface block (Task 3 then only adds adapters).

- [ ] **Step 1: Write the failing store tests** (`workspaceStore.test.ts`)

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { isRefreshSafe, resetWorkspaceStoreForTests, useWorkspaceStore } from "./workspaceStore";

const ready = { readiness: "ready" as const, hasEditableState: false, hasReceivedResults: false };

beforeEach(() => resetWorkspaceStoreForTests());

describe("registerSurface", () => {
  it("registers, patches and unregisters a surface", () => {
    const unregister = useWorkspaceStore.getState().registerSurface({ id: "generate.results", ...ready });
    expect(useWorkspaceStore.getState().surfaces["generate.results"]?.readiness).toBe("ready");
    useWorkspaceStore.getState().updateSurface("generate.results", { hasReceivedResults: true });
    expect(useWorkspaceStore.getState().surfaces["generate.results"]?.hasReceivedResults).toBe(true);
    unregister();
    expect(useWorkspaceStore.getState().surfaces["generate.results"]).toBeUndefined();
  });
  it("a stale unregister after a re-register is a no-op", () => {
    const first = useWorkspaceStore.getState().registerSurface({ id: "history.detail", ...ready });
    useWorkspaceStore.getState().registerSurface({ id: "history.detail", ...ready, readiness: "hydrating" });
    first();
    expect(useWorkspaceStore.getState().surfaces["history.detail"]?.readiness).toBe("hydrating");
  });
  it("updateSurface on an unregistered id is a no-op", () => {
    useWorkspaceStore.getState().updateSurface("history.list", { readiness: "ready" });
    expect(useWorkspaceStore.getState().surfaces["history.list"]).toBeUndefined();
  });
});

describe("operations", () => {
  it("beginOperation adds an active operation and end removes it once", () => {
    const handle = useWorkspaceStore.getState().beginOperation("resolve", "generate.form");
    expect(useWorkspaceStore.getState().operations).toEqual([
      expect.objectContaining({ id: handle.id, kind: "resolve", surface: "generate.form" }),
    ]);
    handle.end("completed");
    handle.end("failed");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
  });
  it("observing the store never aborts in-flight work", () => {
    const controller = new AbortController();
    const abort = vi.spyOn(controller, "abort");
    const handle = useWorkspaceStore.getState().beginOperation("generation", "generate.results");
    const unsubscribe = useWorkspaceStore.subscribe(() => undefined);
    isRefreshSafe(useWorkspaceStore.getState());
    useWorkspaceStore.getState().operations.forEach((op) => expect(op).not.toHaveProperty("controller"));
    unsubscribe();
    expect(abort).not.toHaveBeenCalled();
    handle.end("aborted");
  });
});

describe("isRefreshSafe", () => {
  it("is unsafe with no registered surface", () => {
    expect(isRefreshSafe(useWorkspaceStore.getState())).toEqual({ safe: false, blockers: [{ kind: "no_surface" }] });
  });
  it("is safe with one ready, empty surface and no operations", () => {
    useWorkspaceStore.getState().registerSurface({ id: "history.list", ...ready });
    expect(isRefreshSafe(useWorkspaceStore.getState())).toEqual({ safe: true, blockers: [] });
  });
  it.each([
    ["hydrating", { readiness: "hydrating" }, { kind: "hydrating", surface: "generate.form" }],
    ["restoring", { readiness: "restoring" }, { kind: "restoring", surface: "generate.form" }],
    ["editable", { hasEditableState: true }, { kind: "editable", surface: "generate.form" }],
    ["results", { hasReceivedResults: true }, { kind: "results", surface: "generate.form" }],
  ])("reports %s as a blocker", (_label, patch, blocker) => {
    useWorkspaceStore.getState().registerSurface({ id: "generate.form", ...ready, ...patch });
    expect(isRefreshSafe(useWorkspaceStore.getState())).toEqual({ safe: false, blockers: [blocker] });
  });
  it("lists every blocker, surfaces before operations", () => {
    useWorkspaceStore.getState().registerSurface({ id: "generate.form", ...ready, hasEditableState: true });
    useWorkspaceStore.getState().registerSurface({ id: "generate.results", ...ready, hasReceivedResults: true });
    useWorkspaceStore.getState().beginOperation("prompt_preview", "generate.confirmation");
    expect(isRefreshSafe(useWorkspaceStore.getState()).blockers).toEqual([
      { kind: "editable", surface: "generate.form" },
      { kind: "results", surface: "generate.results" },
      { kind: "operation", operation: "prompt_preview", surface: "generate.confirmation" },
    ]);
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run src/lib/workspace/workspaceStore.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement `workspaceStore.ts`**

```ts
import { create } from "zustand";
import type { WorkspaceSnapshot } from "./adapters/types";

export type SurfaceId = /* as in Interfaces */;
/* ...types from the Interfaces block... */

let nextOperationId = 1;

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  surfaces: {},
  operations: [],
  registerSurface(participation) {
    const entry = { ...participation };
    set((state) => ({ surfaces: { ...state.surfaces, [entry.id]: entry } }));
    return () => {
      set((state) => {
        if (state.surfaces[entry.id] !== entry) return state;   // stale unregister → no-op
        const { [entry.id]: _removed, ...rest } = state.surfaces;
        return { surfaces: rest };
      });
    };
  },
  updateSurface(id, patch) {
    set((state) => {
      const current = state.surfaces[id];
      if (!current) return state;
      return { surfaces: { ...state.surfaces, [id]: { ...current, ...patch } } };
    });
  },
  beginOperation(kind, surface) {
    const id = nextOperationId++;
    set((state) => ({ operations: [...state.operations, { id, kind, surface, startedAt: Date.now() }] }));
    let ended = false;
    return {
      id,
      end(_outcome) {
        if (ended) return;
        ended = true;
        set((state) => ({ operations: state.operations.filter((op) => op.id !== id) }));
      },
    };
  },
}));
```
Note: the stale-unregister check compares the stored entry by identity, so `updateSurface` must keep that identity stable — implement `updateSurface` with `Object.assign(current, patch)` on a fresh copy AND re-point the unregister closure? Simpler: track a registration token instead of identity: keep a module-level `Map<SurfaceId, symbol>`; `registerSurface` stores a new symbol, the returned unregister removes the surface only if the map still holds its symbol. Use the token approach.

`isRefreshSafe` iterates `Object.values(state.surfaces)` in registration order (insertion order of the object), pushing `hydrating`/`restoring` (from `readiness`), then `editable`, then `results` per surface, then one `operation` blocker per active operation; `no_surface` when there are no surfaces. `resetWorkspaceStoreForTests` sets `{ surfaces: {}, operations: [] }` and clears the token map.

- [ ] **Step 4: Run store tests** → PASS.

- [ ] **Step 5: Write the failing hook test** (`useSurfaceParticipation.test.tsx`)

```tsx
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "./workspaceStore";
import { useSurfaceParticipation } from "./useSurfaceParticipation";

beforeEach(() => resetWorkspaceStoreForTests());

describe("useSurfaceParticipation", () => {
  it("registers on mount, patches on change, unregisters on unmount", () => {
    const { rerender, unmount } = renderHook(
      ({ ready }: { ready: boolean }) => useSurfaceParticipation("history.detail", {
        readiness: ready ? "ready" : "hydrating", hasEditableState: false, hasReceivedResults: false,
      }),
      { initialProps: { ready: false } },
    );
    expect(useWorkspaceStore.getState().surfaces["history.detail"]?.readiness).toBe("hydrating");
    rerender({ ready: true });
    expect(useWorkspaceStore.getState().surfaces["history.detail"]?.readiness).toBe("ready");
    unmount();
    expect(useWorkspaceStore.getState().surfaces["history.detail"]).toBeUndefined();
  });
  it("keeps the export seam callable from the store", () => {
    const snapshot = { kind: "modification", version: 1, recordId: "r1", questionId: "q1", annotations: [], replacement: null } as const;
    renderHook(() => useSurfaceParticipation("history.modification", {
      readiness: "ready", hasEditableState: false, hasReceivedResults: false, exportWorkspace: () => snapshot,
    }));
    expect(useWorkspaceStore.getState().surfaces["history.modification"]?.exportWorkspace?.()).toEqual(snapshot);
  });
});
```

- [ ] **Step 6: Implement `useSurfaceParticipation.ts`**

```ts
import { useEffect } from "react";
import { useWorkspaceStore, type SurfaceId, type SurfaceParticipation } from "./workspaceStore";

export function useSurfaceParticipation(id: SurfaceId, participation: Omit<SurfaceParticipation, "id">): void {
  const { readiness, hasEditableState, hasReceivedResults, exportWorkspace } = participation;
  useEffect(() => {
    const unregister = useWorkspaceStore.getState().registerSurface({ id, readiness, hasEditableState, hasReceivedResults, exportWorkspace });
    return unregister;
    // Register once per id; value changes are patched by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useEffect(() => {
    useWorkspaceStore.getState().updateSurface(id, { readiness, hasEditableState, hasReceivedResults, exportWorkspace });
  }, [id, readiness, hasEditableState, hasReceivedResults, exportWorkspace]);
}
```

- [ ] **Step 7: Run both test files, then `npx tsc -b --noEmit` and `npm run lint`** → all green.
- [ ] **Step 8: Commit** — `git add web/src/lib/workspace && git commit -m "feat(769): workspace registry with refresh-safety selector and participation hook"`

---

### Task 2: `parseFormFields` extraction and the form adapter

**Files:**
- Modify: `web/src/lib/formDraft.ts` (`isFormFields`, `loadDraft`)
- Create: `web/src/lib/workspace/adapters/formWorkspace.ts`
- Test: `web/src/lib/formDraft.test.ts` (existing — must stay green unchanged)
- Test: `web/src/lib/workspace/adapters/formWorkspace.test.ts`

**Interfaces (produced):**
```ts
// formDraft.ts
export function parseFormFields(raw: unknown): FormFields | null;   // guard + the normalisation loadDraft applies today
// adapters/types.ts (already created in Task 1)
export interface FormWorkspaceSnapshot { kind: "form"; version: 1; fields: FormFields }
// adapters/formWorkspace.ts
export function exportFormWorkspace(fields: FormFields): FormWorkspaceSnapshot;
export function importFormWorkspace(raw: unknown): FormFields | null;
```

- [ ] **Step 1: Write the failing adapter test**

```ts
import { describe, expect, it } from "vitest";
import { exportFormWorkspace, importFormWorkspace } from "./formWorkspace";
import { loadDraft, saveDraft } from "../../formDraft";
import type { FormFields } from "../../../components/ParamForm";

// Reuse the FormFields fixture builder from formDraft.test.ts: copy its `makeFields()` helper verbatim here
// (name it `makeFields`) so this test does not import from a test file.

describe("form workspace adapter", () => {
  it("round-trips FormFields", () => {
    const fields = makeFields();
    expect(importFormWorkspace(exportFormWorkspace(fields))).toEqual(fields);
  });
  it("normalises exactly like loadDraft for an older draft shape", () => {
    const legacy = { ...makeFields() } as Record<string, unknown>;
    delete legacy.modelVerify; delete legacy.effortVerify; delete legacy.allowDuplicateFigureKinds;
    saveDraft("u1", legacy as unknown as FormFields);
    const viaDraft = loadDraft("u1")?.fields ?? null;
    expect(importFormWorkspace({ kind: "form", version: 1, fields: legacy })).toEqual(viaDraft);
  });
  it.each([null, 42, { kind: "form" }, { kind: "results", version: 1, fields: makeFields() }, { kind: "form", version: 2, fields: makeFields() }, { kind: "form", version: 1, fields: { grade: "x" } }])(
    "rejects malformed input %#", (raw) => { expect(importFormWorkspace(raw)).toBeNull(); },
  );
});
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** In `formDraft.ts`, move the body of the `return { savedAt, fields: { ...normalisation } }` block into `parseFormFields(raw)`: it returns `null` unless `isFormFields(raw)`, otherwise the normalised `FormFields` object exactly as `loadDraft` builds today. `loadDraft` becomes: parse JSON, check `savedAt` finite and age, `const fields = parseFormFields(parsed.fields); if (!fields) { clearDraft; return null }`, return `{ savedAt, fields }`. In `formWorkspace.ts`:

```ts
import { parseFormFields } from "../../formDraft";
import type { FormFields } from "../../../components/ParamForm";
import type { FormWorkspaceSnapshot } from "./types";

export function exportFormWorkspace(fields: FormFields): FormWorkspaceSnapshot {
  return { kind: "form", version: 1, fields: { ...fields } };
}
export function importFormWorkspace(raw: unknown): FormFields | null {
  if (typeof raw !== "object" || raw === null) return null;
  const snapshot = raw as Record<string, unknown>;
  if (snapshot.kind !== "form" || snapshot.version !== 1) return null;
  return parseFormFields(snapshot.fields);
}
```

- [ ] **Step 4: Run `npx vitest run src/lib/formDraft.test.ts src/lib/workspace/adapters/formWorkspace.test.ts`** → PASS; tsc + lint clean.
- [ ] **Step 5: Commit** — `git commit -m "refactor(769): extract parseFormFields and add the form workspace adapter"`

---

### Task 3: Confirmation, results and modification adapters

**Files:**
- Modify: `web/src/lib/workspace/adapters/types.ts`
- Create: `web/src/lib/workspace/adapters/confirmationWorkspace.ts`, `resultsWorkspace.ts`, `modificationWorkspace.ts`
- Test: one `*.test.ts` beside each adapter

**Interfaces (produced):**
```ts
// types.ts
import type { FormParams } from "../../../components/ParamForm";
import type { ExamQuestion, GeneratedQuestion } from "../../../hooks/useGenerate";
import type { ModificationSegmentRequest } from "../../../api/client";
import type { ModificationRunResult } from "../../../hooks/useModificationRun";
export type CoreQuestionResolution = "idle" | "loading" | "generated" | "failed";
export type HistoryDraftChoice = "draft" | "history" | "defaults" | null;
export interface ConfirmationWorkspaceSnapshot { kind: "confirmation"; version: 1; pendingParams: FormParams; pendingPerQuestionParams: Record<string, unknown>[] | null; clearedPaths: string[]; redraws: Record<string, number>; hasPendingConfirmationEdits: boolean; coreQuestionResolution: CoreQuestionResolution; historyDraftChoice: HistoryDraftChoice }
export type ResultsCompletion = "settled" | "error" | "unknown";
export interface ResultsWorkspaceSnapshot { kind: "results"; version: 1; results: ExamQuestion[]; displayResults: GeneratedQuestion[]; progressLines: string[]; errorMessage: string | null; startedAt: number | null; finishedAt: number | null; subQuestionTotal: number | null; requestedTotal: number; submittedSubQuestionCount: number | null; completion: ResultsCompletion }
export interface ModificationAnnotationSnapshot { segments: ModificationSegmentRequest[]; instruction: string }
export interface ModificationWorkspaceSnapshot { kind: "modification"; version: 1; recordId: string; questionId: string; annotations: ModificationAnnotationSnapshot[]; replacement: ModificationRunResult | null }
export type WorkspaceSnapshot = FormWorkspaceSnapshot | ConfirmationWorkspaceSnapshot | ResultsWorkspaceSnapshot | ModificationWorkspaceSnapshot;

// each adapter
export function exportConfirmationWorkspace(live: Omit<ConfirmationWorkspaceSnapshot, "kind" | "version">): ConfirmationWorkspaceSnapshot;
export function importConfirmationWorkspace(raw: unknown): Omit<ConfirmationWorkspaceSnapshot, "kind" | "version"> | null;
export interface ResultsWorkspaceLive { results; displayResults; progressLines; errorMessage; startedAt; finishedAt; subQuestionTotal; requestedTotal; submittedSubQuestionCount; status: "idle" | "generating" | "error" }
export function exportResultsWorkspace(live: ResultsWorkspaceLive): ResultsWorkspaceSnapshot;   // completion: status==="error" → "error"; finishedAt!==null && status==="idle" → "settled"; else "unknown"
export function importResultsWorkspace(raw: unknown): ResultsWorkspaceSnapshot | null;
export function exportModificationWorkspace(live: Omit<ModificationWorkspaceSnapshot, "kind" | "version">): ModificationWorkspaceSnapshot;
export function importModificationWorkspace(raw: unknown): Omit<ModificationWorkspaceSnapshot, "kind" | "version"> | null;
```
Validation rules (import returns `null` otherwise): `kind`/`version` exact; confirmation `pendingParams` is a non-null object with string `subject`; `pendingPerQuestionParams` null or array of non-null objects; `clearedPaths` string array; `redraws` object of finite numbers; `coreQuestionResolution` one of the four; `historyDraftChoice` one of the four. Results: `results` and `displayResults` arrays of non-null objects, `displayResults[i]` having integer `index`, object `question`, boolean `isFinal`; `progressLines` string array; numbers finite or null; `completion` one of three. Modification: `recordId`/`questionId` non-empty strings; each annotation `segments` an array of objects with string `path`, integer `start`/`end`, string `text` (mirror `ModificationSegmentRequest` fields exactly — read `api/client.ts` and copy its keys) and string `instruction`; `replacement` null or object with object `question`.

- [ ] **Step 1: Write failing tests** — for each adapter: (a) round trip of a realistic fixture (`results` fixture from `useGenerate.test.ts`'s sample `ExamQuestion`; annotation fixture from `HistoryDetail.annotation.test.tsx`), (b) wrong `kind`, (c) wrong `version`, (d) one malformed nested field, (e) for results: `completion` mapping for the three `status`/`finishedAt` combinations.
- [ ] **Step 2: Run → FAIL. Step 3: Implement with small `isRecord`/`isStringArray` helpers in a shared `adapters/guards.ts`. Step 4: Run adapter tests → PASS; tsc + lint clean.**
- [ ] **Step 5: Commit** — `git commit -m "feat(769): confirmation, results and modification workspace adapters"`

---

### Task 4: `useGenerate` admission, observed operation, `restoreResults`

**Files:**
- Modify: `web/src/hooks/useGenerate.ts` (`UseGenerateReturn`, `useGenerate`, `generate`, `reset`)
- Test: `web/src/hooks/useGenerate.test.ts` (append a `describe("admission")`, `describe("restoreResults")`, `describe("workspace operation")`)

**Interfaces (produced):**
```ts
export type AdmissionState = "idle" | "submitting" | "admitted" | "rejected";
export type AdmissionOutcome = { outcome: "admitted" } | { outcome: "rejected"; reason: string };
// added to UseGenerateReturn
admission: AdmissionState;
admissionError: string | null;
generate: (params: GenerateParams) => Promise<AdmissionOutcome>;
restoreResults: (snapshot: ResultsWorkspaceSnapshot) => boolean;
```

- [ ] **Step 1: Write failing tests** using the file's existing `fetchEventSource` mock helpers (look at how existing tests drive `onopen`/`onmessage`/`onerror`; reuse the same helper names):
  - `admission` is `"idle"` initially; `"submitting"` synchronously after `generate()`; `"admitted"` after the `started` event and the promise resolves `{ outcome: "admitted" }`.
  - 401, 422 (JSON detail), 500 at `onopen` → `"rejected"`, `admissionError` equals the existing `errorMessage`, promise resolves `{ outcome: "rejected", reason }`; existing `status`/`finishedAt` expectations unchanged.
  - `onerror` before `started` → `"rejected"`; `onerror` after `started` → still `"admitted"`.
  - SSE `error` after `started` → still `"admitted"`; `done` → still `"admitted"`; `reset()` → `"idle"`, `admissionError` null.
  - a second `generate()` while the first is unsettled resolves the first promise `{ outcome: "rejected", reason: "superseded" }`.
  - operation: after `generate()`, `useWorkspaceStore.getState().operations` contains `{ kind: "generation", surface: "generate.results" }`; it is removed on `done`, on SSE `error`, on `onopen` rejection, on `reset()`, and on unmount.
  - `restoreResults`: returns false and changes nothing while `status === "generating"`; otherwise returns true, sets `results`/`displayResults`/`progressLines`/`errorMessage`/`startedAt`/`finishedAt`/`subQuestionTotal`, `status` `"error"` for completion `"error"` else `"idle"`, `admission` `"idle"`, `llmCalls` `[]`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** Add `const [admission, setAdmission] = useState<AdmissionState>("idle")`, `const [admissionError, setAdmissionError] = useState<string | null>(null)`, `const admissionResolveRef = useRef<((o: AdmissionOutcome) => void) | null>(null)`, `const operationRef = useRef<OperationHandle | null>(null)`. Helper inside the hook:
```ts
const settleAdmission = (outcome: AdmissionOutcome) => {
  setAdmission(outcome.outcome);
  setAdmissionError(outcome.outcome === "rejected" ? outcome.reason : null);
  admissionResolveRef.current?.(outcome);
  admissionResolveRef.current = null;
};
const endOperation = (outcome: OperationOutcome) => { operationRef.current?.end(outcome); operationRef.current = null; };
```
In `generate`: first `admissionResolveRef.current?.({ outcome: "rejected", reason: "superseded" }); endOperation("superseded");` then existing abort/reset lines, `setAdmission("submitting"); setAdmissionError(null); operationRef.current = useWorkspaceStore.getState().beginOperation("generation", "generate.results");` and `const admissionPromise = new Promise<AdmissionOutcome>((resolve) => { admissionResolveRef.current = resolve; });`. In `onopen` non-ok branches, after the existing `setFinishedAt`: `settleAdmission({ outcome: "rejected", reason: msg }); endOperation("failed");`. In `case "started"`: `settleAdmission({ outcome: "admitted" })`. In `case "error"`: `endOperation("failed")`. In `case "done"`: `endOperation("completed")`. In `onerror`, before the throw: `if (admissionResolveRef.current) settleAdmission({ outcome: "rejected", reason: message }); endOperation("failed");` (compute `message` once and reuse for `setErrorMessage`). Return `admissionPromise` from `generate`. In `reset`: `admissionResolveRef.current?.({ outcome: "rejected", reason: "reset" }); admissionResolveRef.current = null; endOperation("aborted"); setAdmission("idle"); setAdmissionError(null);`. In the unmount effect: `endOperation("aborted")`. Add `restoreResults` with `useCallback` reading a `statusRef` (add `const statusRef = useRef(status); statusRef.current = status;` — or check `controllerRef.current !== null` which is non-null exactly while a stream is live; use the controller check to avoid a render-phase ref write).
- [ ] **Step 4: Run `npx vitest run src/hooks/useGenerate.test.ts src/api/generate-transport.test.tsx`** → PASS; tsc + lint clean.
- [ ] **Step 5: Commit** — `git commit -m "feat(769): expose admission outcome, observed operation and restoreResults on useGenerate"`

---

### Task 5: `useModificationRun` admission and observed operation

**Files:**
- Modify: `web/src/hooks/useModificationRun.ts`
- Test: `web/src/hooks/useModificationRun.test.ts` (new; mock `../api/client` `submitModificationBatch` and `@microsoft/fetch-event-source` the way `useGenerate.test.ts` does)

**Interfaces (produced):** `admission: AdmissionState; admissionError: string | null` added to `UseModificationRunReturn` (import `AdmissionState` from `./useGenerate`).

- [ ] **Step 1: Failing tests:** `"idle"` initially; `"submitting"` synchronously after `start()`; `"admitted"` once `submitModificationBatch` resolves with `run_id`; `"rejected"` with the thrown message when it rejects, and with `"Modification admission did not return a run id"` when `run_id` is missing (existing message — assert `error` unchanged too); stream `error` after admission keeps `"admitted"`; operation `{ kind: "modification", surface: "history.modification" }` present from `start()` until `done` (completed) / error (failed) / unmount (aborted); `start()` without a record id registers nothing.
- [ ] **Step 2: Run → FAIL. Step 3: Implement** mirroring Task 4: `setAdmission("submitting")` beside `setStatus("running")`; after `admission.run_id` check passes → `setAdmission("admitted")`; in the `catch` and the missing-run-id path → if still submitting, `setAdmission("rejected"); setAdmissionError(message)`; operation begun after the `activeRecordId` guard, ended in `done` (completed), `error` event / `onerror` / catch (failed), unmount effect (aborted), and when a newer sequence supersedes (superseded). Guard every `set` with the existing `isCurrent()`.
- [ ] **Step 4: Run the new test plus `HistoryDetail.annotation.test.tsx`, `QuestionCard.*.test.tsx`** → PASS; tsc + lint clean.
- [ ] **Step 5: Commit** — `git commit -m "feat(769): expose admission outcome and observed operation on useModificationRun"`

---

### Task 6: Surface participation on GeneratePage, HistoryList, HistoryDetail, QuestionCard; export operations

**Files:**
- Modify: `web/src/pages/GeneratePage.tsx`, `web/src/pages/HistoryPage.tsx` (HistoryList), `web/src/pages/HistoryDetail.tsx`, `web/src/components/QuestionCard.tsx`
- Test: `web/src/pages/GeneratePage.workspace.test.tsx` (new), `web/src/pages/HistoryPage.test.tsx` and `HistoryDetail.test.tsx` (append), `web/src/components/QuestionCard.workspace.test.tsx` (new)

- [ ] **Step 1: Failing tests.**
  - GeneratePage (mock `ParamForm` and `useGenerate` the way `GeneratePage.resubmit-guard.test.tsx` does): `generate.results` registers ready with `hasReceivedResults === false`; becomes true when the mocked `displayResults` is non-empty; `exportWorkspace()` returns a `results` snapshot with `requestedTotal` from the last submit; `handleSubmit` (captured `onSubmit`) returns the mocked `generate` promise; clicking the JSON download button begins and ends an `export_json` operation (assert via a `beginOperation` spy on the store); the ODT button begins `export_odt` and ends `completed` after the mocked `buildExamOdt` resolves, `failed` when it rejects (and nothing else changes — no error UI).
  - HistoryList: `history.list` is `hydrating` until `listHistory` resolves or rejects, then `ready`.
  - HistoryDetail: `history.detail` is `hydrating` until `getHistoryDetail` resolves or rejects, then `ready`; `recordId` change goes back to `hydrating`.
  - QuestionCard with `recordId`: registers `history.modification`; `hasEditableState` false → true after a selection creates an annotation (reuse the selection-driving helper from `HistoryDetail.annotation.test.tsx`); `hasReceivedResults` true after a mocked completed run; `exportWorkspace()` returns a `modification` snapshot with the annotation's segments and instruction; without `recordId` nothing is registered; download buttons begin/end `export_json` / `export_image` / `export_odt`.
- [ ] **Step 2: Run → FAIL. Step 3: Implement.** `useSurfaceParticipation` calls at the top level of each component (never conditional — for QuestionCard, wrap the participation in a tiny child component `ModificationParticipation` rendered only when `recordId` is set, so hook order stays stable). Memoise `exportWorkspace` with `useCallback` over the live values. Export operations: `const op = useWorkspaceStore.getState().beginOperation("export_odt", "generate.results"); buildExamOdt(...).then((blob) => { downloadBlob(...); op.end("completed"); }).catch(() => op.end("failed"));` — surfaces: GeneratePage → `generate.results`; QuestionCard → `history.modification` when `recordId` is set, else `generate.results`.
- [ ] **Step 4: Run all `GeneratePage.*`, `HistoryPage.*`, `HistoryDetail.*`, `QuestionCard.*` tests** → PASS (the guard tests must pass unmodified); tsc + lint clean.
- [ ] **Step 5: Commit** — `git commit -m "feat(769): register generate/history surfaces and observe export operations"`

---

### Task 7: ParamForm participation, confirmation export, planning/預抽/preview operations

**Files:**
- Modify: `web/src/components/ParamForm.tsx`
- Test: `web/src/components/ParamForm.workspace.test.tsx` (new; copy the schema/models fetch mocks and the "open the confirmation screen" helper from `ParamForm.preview-refetch.test.tsx`)

- [ ] **Step 1: Failing tests.**
  - `generate.form` registers `hydrating`; becomes `ready` once schemas, models and defaults resolve (drive the same mocks the preview-refetch test uses).
  - With a saved draft and default fields, readiness is `restoring` while the draft prompt shows; `ready` after 「還原草稿」/「重新開始」 (drive via the buttons `ParamForm.draft-restore.test.tsx` clicks); with a draft AND `initialParams`, `restoring` while the draft-vs-History choice shows.
  - `hasEditableState` false, then true after typing in a field (same interaction as `ParamForm.unsubmitted-input.test.tsx`).
  - Opening 發送前確認 registers `generate.confirmation` with `hasEditableState: true`; sending or cancelling unregisters it.
  - `generate.confirmation.exportWorkspace()` returns a `confirmation` snapshot whose `pendingParams` equals the resolved payload, `redraws` equals `{}` before any 重抽 and `{ [path]: 1 }` after one 重抽 click, `historyDraftChoice` mirrors the choice.
  - Operations: opening the confirmation begins `resolve` on `generate.confirmation` and ends when the mocked resolver resolves; a second resolve issued before the first settles ends the first as `superseded` (spy on `end` via a `beginOperation` wrapper spy); `core_question_planning` begins when the planning effect fires and ends `completed`/`failed`; `prompt_preview` begins for the initial preview and for the debounced refetch and ends `superseded` when a newer refetch is issued.
- [ ] **Step 2: Run → FAIL. Step 3: Implement.**
  - State: add `const [hasUserEdited, setHasUserEdited] = useState(false)` and set it in `markUnsubmittedInput` (keep the ref; the state is only for participation). Reset to false where `hasUserEditedRef.current = false` is assigned today (draft restore / defaults handlers).
  - `const formReadiness: SurfaceReadiness = hasDraftHistoryConflict || showDraftPrompt ? "restoring" : schemas !== null && defaultsReady && modelsResolved ? "ready" : "hydrating";` placed after `showDraftPrompt` is computed.
  - `useSurfaceParticipation("generate.form", { readiness: formReadiness, hasEditableState: hasUserEdited, hasReceivedResults: false, exportWorkspace: exportForm })` where `exportForm = useCallback(() => exportFormWorkspace(formSnapshot), [formSnapshot])`.
  - Confirmation participation: a small child component `ConfirmationParticipation({ exportWorkspace })` rendered inside the `if (pendingParams)` branch's JSX that calls `useSurfaceParticipation("generate.confirmation", { readiness: "ready", hasEditableState: true, hasReceivedResults: false, exportWorkspace })`; `exportWorkspace` built with `exportConfirmationWorkspace({ pendingParams, pendingPerQuestionParams, clearedPaths, redraws: redrawsRef.current, hasPendingConfirmationEdits, coreQuestionResolution, historyDraftChoice })`.
  - Operations (store access via `useWorkspaceStore.getState().beginOperation`):
    - `resolveForConfirmation`: after `const sequence = ++resolveRequestSeqRef.current;` add `resolveOperationRef.current?.end("superseded"); const op = useWorkspaceStore.getState().beginOperation("resolve", "generate.confirmation"); resolveOperationRef.current = op;` and in both the success path (after the `sequence` check) and the catch path call `op.end("completed" | "failed")` and null the ref if it is still `op`. In the stale-sequence early returns nothing is needed (already ended as superseded). In `handleConfirmSend` and the confirmation-cancel handler where `resolveRequestSeqRef.current += 1` is done, also `resolveOperationRef.current?.end("superseded"); resolveOperationRef.current = null`.
    - Planning effect: `const op = beginOperation("core_question_planning", "generate.confirmation")` right before `void planCoreQuestions(...)`; `.then` → `op.end(selected ? "completed" : "failed")` (before the `cancelled` check use: cleanup `return () => { cancelled = true; op.end("aborted"); }` — `end` is idempotent so ordering is safe); `.catch` → `op.end("failed")`.
    - Initial preview effect: begin `prompt_preview` before `void previewGenerate(...)`, end `completed` in `.then`, `failed` in `.catch`, `superseded` in cleanup.
    - Debounced refetch effect: begin inside the timeout callback right before `void previewGenerate(fetchParams)`; end `completed`/`failed` in the handlers; in the `seq !== previewRefetchSeqRef.current` early-return branches end `superseded`; cleanup only clears the timeout (an operation begun inside the timeout is ended by its own handlers).
    - `retryPreviewFetch`: same begin/end pattern.
- [ ] **Step 4: Run the new test plus every `ParamForm.*.test.tsx`** → PASS; tsc + lint clean (watch `react-hooks/refs` — read `redrawsRef.current` inside the `exportWorkspace` callback, not during render).
- [ ] **Step 5: Commit** — `git commit -m "feat(769): ParamForm surface participation, confirmation export and observed 預抽/planning/preview operations"`

---

### Task 8: Documentation and full verification

**Files:**
- Create: `docs/adr/0030-workspace-participation-is-declared-by-each-surface.md`
- Modify: `CONTEXT.md` (glossary), `CLAUDE.md` (Architecture Decisions)
- Verify: `docs/superpowers/specs/2026-09-14-769-update-flow-prefactor-design.md`, `docs/superpowers/plans/2026-09-14-769-update-flow-prefactor.md`, `docs/research/2026-09-14-769-update-flow-prefactor-inventory.md` are committed

- [ ] **Step 1: ADR 0030** in the style of `docs/adr/0010-*.md` (title line, one context paragraph, `## Considered Options`, `## Consequences`): decision = each surface declares its participation in `web/src/lib/workspace/workspaceStore.ts` (readiness, editable state, results, export seam) and operations are begun/ended at the call site; rejected = inferring activity from the router/DOM, and a wrapper that owns AbortControllers; consequences = zero surfaces is unsafe, `isRefreshSafe` reports every blocker, admission lives beside `status` and never replaces it, #770–#779 consume these seams.
- [ ] **Step 2: CONTEXT.md** — add under 設定 (or a new `### 更新 (Update)` section if none fits) three entries in the existing `**term**: definition / _Avoid_:` format: 工作區參與 (a surface's declared readiness, editable state, received results and export seam), 受理 (the moment the server accepts a submitted generation or 人工審題修正 request — `started` event / `run_id` — as distinct from submitting), 可觀察作業 (an in-flight operation an updater can see but not abort).
- [ ] **Step 3: CLAUDE.md** — add a `### Workspace registry (issue #769)` subsection after the "Web confirmation dialog pre-draw" section: four sentences on the store, participation, admission and the no-cancellation rule, pointing to ADR 0030.
- [ ] **Step 4: Full verification from `web/`:** `npx tsc -b --noEmit && npm run lint && npm test` — all green; then `git status` shows only intended files.
- [ ] **Step 5: Commit** — `git commit -m "docs(769): ADR 0030 workspace participation, glossary and architecture notes"`
