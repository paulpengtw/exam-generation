# Effort Tier Dropdowns — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add effort-tier dropdowns (規劃 Effort / 出題 Effort) beside the existing model selects, persisted to localStorage, reconciled on model change, hidden on discovery failure, and sent as effort_plan/effort_execute on the generate request.

**Architecture:** Follows the exact same pattern as model_plan/model_execute: initialise from localStorage (fallback "medium"), persist via useEffect, reconcile against the live effort map when models resolve or when model changes, hide + clear when /api/models fails, send on submit. Confirmation screen shows two extra rows alongside the existing model rows, visible only when models.effort is present.

**Tech Stack:** React 18, TypeScript 5, Vitest + @testing-library/react, Tailwind CSS.

## Global Constraints

- Strict TDD: failing test written before every implementation step.
- Do NOT edit existing `*.test.tsx` files unless an assertion breaks due to the new FormFields fields.
- Baseline: 435 tests, 60 files — all must stay green plus the new ones.
- Work on branch `staging`, no commits needed.
- i18n key style must match existing model keys: short dotted namespaces.
- `effort` field on AvailableModels must be optional (backwards-compatible with existing test mocks).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `web/src/api/client.ts` | Add `effort?: Record<string,string[]>` and `defaults.effort_plan?` / `defaults.effort_execute?` to `AvailableModels` |
| Modify | `web/src/i18n/messages.ts` | Add 4 new keys (en-US + zh-TW): `form.effort_plan`, `form.effort_execute`, `form.confirm_effort_plan`, `form.confirm_effort_execute` |
| Modify | `web/src/lib/formDraft.ts` | Add `effortPlan`/`effortExecute` to `isFormFields` validator |
| Modify | `web/src/components/ParamForm.tsx` | Add FormFields fields, state management, localStorage, UI dropdowns, confirmation rows |
| Create | `web/src/components/ParamForm.effort-selection.test.tsx` | All new test seams |

---

### Task 1: Type scaffolding + i18n keys

**Files:**
- Modify: `web/src/api/client.ts`
- Modify: `web/src/i18n/messages.ts`
- Modify: `web/src/lib/formDraft.ts`

**Interfaces:**

Produces:
- `AvailableModels.effort?: Record<string, string[]>`
- `AvailableModels.defaults.effort_plan?: string`
- `AvailableModels.defaults.effort_execute?: string`
- i18n keys `form.effort_plan` / `form.effort_execute` / `form.confirm_effort_plan` / `form.confirm_effort_execute` (en-US + zh-TW)
- `isFormFields` accepts `effortPlan: string` and `effortExecute: string`

- [ ] **Step 1: Update AvailableModels in api/client.ts**

Replace:
```typescript
export interface AvailableModels {
  allowed: string[];
  defaults: { plan: string; execute: string };
}
```
With:
```typescript
export interface AvailableModels {
  allowed: string[];
  effort?: Record<string, string[]>;
  defaults: { plan: string; execute: string; effort_plan?: string; effort_execute?: string };
}
```

- [ ] **Step 2: Add i18n keys in messages.ts**

In `"en-US"` block, after `"params.model_execute_label"`:
```typescript
"form.effort_plan": "Planning effort",
"form.effort_execute": "Execution effort",
"form.confirm_effort_plan": "Planning effort",
"form.confirm_effort_execute": "Execution effort",
```

In `"zh-TW"` block, after `"params.model_execute_label"`:
```typescript
"form.effort_plan": "規劃 Effort",
"form.effort_execute": "出題 Effort",
"form.confirm_effort_plan": "規劃 Effort",
"form.confirm_effort_execute": "出題 Effort",
```

- [ ] **Step 3: Update isFormFields in formDraft.ts**

After `typeof value.modelExecute === "string"` add:
```typescript
&& typeof value.effortPlan === "string"
&& typeof value.effortExecute === "string"
```

- [ ] **Step 4: Verify TypeScript**
```bash
cd /workspace/exam-generation/web && npx tsc --noEmit 2>&1 | head -30
```

---

### Task 2: Write failing tests

**Files:**
- Create: `web/src/components/ParamForm.effort-selection.test.tsx`

**Interfaces:**
- Consumes: `AvailableModels` with `effort` field (from Task 1)
- Consumes: i18n keys `form.effort_plan`, `form.effort_execute`, `form.confirm_effort_plan`, `form.confirm_effort_execute`

- [ ] **Step 1: Write the test file**

```typescript
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));

import ParamForm from "./ParamForm";

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "standard", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

const MODELS_WITH_EFFORT = {
  allowed: ["claude-opus-4-6", "claude-sonnet-4-6"],
  effort: {
    "claude-opus-4-6": ["low", "medium", "high", "max", "xhigh"],
    "claude-sonnet-4-6": ["low", "medium", "high", "max"],
  },
  defaults: {
    plan: "claude-opus-4-6",
    execute: "claude-sonnet-4-6",
    effort_plan: "medium",
    effort_execute: "medium",
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(MATH_SCHEMA);
  getAvailableModelsMock.mockResolvedValue(MODELS_WITH_EFFORT);
});

describe("ParamForm — effort-tier selection", () => {
  describe("options filtered per model", () => {
    it("plan effort dropdown shows xhigh when plan model is claude-opus-4-6", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const planModelSelect = await screen.findByLabelText("Planner model");
      await user.selectOptions(planModelSelect, "claude-opus-4-6");
      const planEffortSelect = screen.getByLabelText("Planning effort");
      const options = Array.from(
        planEffortSelect.querySelectorAll("option"),
      ).map((o) => (o as HTMLOptionElement).value);
      expect(options).toContain("xhigh");
    });

    it("execute effort dropdown does NOT show xhigh when execute model is claude-sonnet-4-6", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const execModelSelect = await screen.findByLabelText("Execution model");
      await user.selectOptions(execModelSelect, "claude-sonnet-4-6");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      const options = Array.from(
        execEffortSelect.querySelectorAll("option"),
      ).map((o) => (o as HTMLOptionElement).value);
      expect(options).not.toContain("xhigh");
      expect(options).toContain("max");
    });
  });

  describe("reconcile on model change", () => {
    it("effort_execute falls back to medium when switching from opus to sonnet with xhigh selected", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

      // Set execute model to opus (which supports xhigh)
      const execModelSelect = await screen.findByLabelText("Execution model");
      await user.selectOptions(execModelSelect, "claude-opus-4-6");

      // Select xhigh for effort
      const execEffortSelect = screen.getByLabelText("Execution effort");
      await user.selectOptions(execEffortSelect, "xhigh");
      expect((execEffortSelect as HTMLSelectElement).value).toBe("xhigh");

      // Switch execute model to sonnet (which doesn't support xhigh)
      await user.selectOptions(execModelSelect, "claude-sonnet-4-6");

      // effort_execute should fall back to medium
      expect((execEffortSelect as HTMLSelectElement).value).toBe("medium");
    });
  });

  describe("localStorage persistence round-trip", () => {
    it("persists effort_plan and effort_execute to localStorage when selected", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const planEffortSelect = await screen.findByLabelText("Planning effort");
      await user.selectOptions(planEffortSelect, "high");
      expect(window.localStorage.getItem("effort_plan")).toBe("high");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      await user.selectOptions(execEffortSelect, "max");
      expect(window.localStorage.getItem("effort_execute")).toBe("max");
    });

    it("hydrates effortPlan and effortExecute from localStorage on mount", async () => {
      window.localStorage.setItem("effort_plan", "high");
      window.localStorage.setItem("effort_execute", "max");
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const planEffortSelect = await screen.findByLabelText("Planning effort");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      expect((planEffortSelect as HTMLSelectElement).value).toBe("high");
      expect((execEffortSelect as HTMLSelectElement).value).toBe("max");
    });
  });

  describe("discovery failure", () => {
    it("hides effort dropdowns when /api/models fails", async () => {
      getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
      await waitFor(() => {
        expect(screen.queryByLabelText("Planning effort")).toBeNull();
        expect(screen.queryByLabelText("Execution effort")).toBeNull();
      });
    });

    it("does not send effort_plan/effort_execute when /api/models fails", async () => {
      window.localStorage.setItem("effort_plan", "high");
      window.localStorage.setItem("effort_execute", "max");
      getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));
      const onSubmit = vi.fn();
      render(
        <ParamForm subject="math" onSubmit={onSubmit} disabled={false} />,
      );
      await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
      await waitFor(() => {
        expect(screen.queryByLabelText("Planning effort")).toBeNull();
      });
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_plan).toBeUndefined();
      expect(submitted.effort_execute).toBeUndefined();
    });
  });

  describe("confirmation screen rows", () => {
    it("shows Planning effort and Execution effort rows with selected values (en-US)", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={vi.fn()} disabled={false} />);
      const planEffortSelect = await screen.findByLabelText("Planning effort");
      await user.selectOptions(planEffortSelect, "high");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      await user.selectOptions(execEffortSelect, "max");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await screen.findByRole("heading", { name: /review settings/i });
      // Labels appear as <dt> elements
      expect(
        screen.getByText("Planning effort", { selector: "dt" }),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Execution effort", { selector: "dt" }),
      ).toBeInTheDocument();
    });
  });

  describe("generate request params", () => {
    it("sends effort_plan and effort_execute in onSubmit payload", async () => {
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(
        <ParamForm subject="math" onSubmit={onSubmit} disabled={false} />,
      );
      const planEffortSelect = await screen.findByLabelText("Planning effort");
      await user.selectOptions(planEffortSelect, "high");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      await user.selectOptions(execEffortSelect, "max");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_plan).toBe("high");
      expect(submitted.effort_execute).toBe("max");
    });

    it("defaults effort_plan and effort_execute to medium when nothing set", async () => {
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(
        <ParamForm subject="math" onSubmit={onSubmit} disabled={false} />,
      );
      // Don't change the effort dropdowns — should send "medium"
      await screen.findByLabelText("Planning effort");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_plan).toBe("medium");
      expect(submitted.effort_execute).toBe("medium");
    });
  });
});
```

- [ ] **Step 2: Run tests to confirm they all fail**
```bash
cd /workspace/exam-generation/web && npx vitest run src/components/ParamForm.effort-selection.test.tsx 2>&1 | tail -20
```
Expected: all tests fail with "Cannot find element" or similar.

---

### Task 3: Implement FormFields + state management in ParamForm.tsx

**Files:**
- Modify: `web/src/components/ParamForm.tsx`

Key changes:
1. Add `effortPlan: string` and `effortExecute: string` to `FormFields`
2. Initialize from localStorage (fallback "medium")
3. Add localStorage persistence `useEffect` blocks
4. Update `defaultFormFields` to accept + return `effortPlan`/`effortExecute`
5. Update `handleStartWithDefaults` to pass effort values
6. Replace the model-reconcile `setField` calls in the models `useEffect` with a single `restoreFormSnapshot` call that reconciles both models and efforts atomically
7. Update the catch block to clear effort fields
8. Update `defaultsSnapshotRef.current` updates to include effort fields
9. Add `effortPlan`/`effortExecute` to baseParams in `handleSubmit` (conditional on `models?.effort`)

- [ ] **Step 1: Add fields to FormFields interface**

In the `FormFields` interface, after `modelExecute: string;`:
```typescript
effortPlan: string;
effortExecute: string;
```

- [ ] **Step 2: Initialize from localStorage**

In the `useState<FormFields>()` initializer, after `modelExecute: window.localStorage.getItem("model_execute") ?? "",`:
```typescript
effortPlan: window.localStorage.getItem("effort_plan") ?? "medium",
effortExecute: window.localStorage.getItem("effort_execute") ?? "medium",
```

- [ ] **Step 3: Destructure effortPlan/effortExecute**

In the destructuring block after `modelExecute,`:
```typescript
effortPlan,
effortExecute,
```

- [ ] **Step 4: Add localStorage persistence effects**

After the existing `useEffect` blocks for `model_plan` and `model_execute`:
```typescript
useEffect(() => {
  window.localStorage.setItem("effort_plan", effortPlan);
}, [effortPlan]);
useEffect(() => {
  window.localStorage.setItem("effort_execute", effortExecute);
}, [effortExecute]);
```

- [ ] **Step 5: Update defaultFormFields**

Change signature to:
```typescript
function defaultFormFields(
  subject: string,
  schemas: Schemas,
  modelPlan: string,
  modelExecute: string,
  effortPlan: string,
  effortExecute: string,
): FormFields {
```

And add to the return object:
```typescript
effortPlan,
effortExecute,
```

- [ ] **Step 6: Update handleStartWithDefaults call**

Change:
```typescript
restoreFormSnapshot(
  defaultFormFields(subject, schemas, modelPlan, modelExecute),
);
```
To:
```typescript
restoreFormSnapshot(
  defaultFormFields(subject, schemas, modelPlan, modelExecute, effortPlan, effortExecute),
);
```

- [ ] **Step 7: Replace model reconciliation in getAvailableModels useEffect**

Replace the existing pattern:
```typescript
if (defaultsSnapshotRef.current) {
  defaultsSnapshotRef.current = {
    ...defaultsSnapshotRef.current,
    modelPlan: ...,
    modelExecute: ...,
  };
}
setField("modelPlan", (prev) => (prev && !allowed.has(prev) ? "" : prev));
setField("modelExecute", (prev) => (prev && !allowed.has(prev) ? "" : prev));
setModelsResolved(true);
```

With:
```typescript
const reconcileEffort = (
  effortValue: string,
  modelId: string,
  effortMap: Record<string, string[]> | undefined,
  defaultEffort: string,
): string => {
  if (!effortMap || !modelId || !effortMap[modelId]) return effortValue;
  const levels = effortMap[modelId];
  return levels.includes(effortValue) ? effortValue : defaultEffort;
};

restoreFormSnapshot((current) => {
  const reconciledPlan = current.modelPlan && !allowed.has(current.modelPlan) ? "" : current.modelPlan;
  const reconciledExecute = current.modelExecute && !allowed.has(current.modelExecute) ? "" : current.modelExecute;
  const defaultEffort = m.defaults.effort_plan ?? "medium";
  const reconciledEffortPlan = reconcileEffort(current.effortPlan, reconciledPlan, m.effort, defaultEffort);
  const defaultEffortEx = m.defaults.effort_execute ?? "medium";
  const reconciledEffortExecute = reconcileEffort(current.effortExecute, reconciledExecute, m.effort, defaultEffortEx);
  return {
    ...current,
    modelPlan: reconciledPlan,
    modelExecute: reconciledExecute,
    effortPlan: reconciledEffortPlan,
    effortExecute: reconciledEffortExecute,
  };
});

if (defaultsSnapshotRef.current) {
  const snap = defaultsSnapshotRef.current;
  const reconciledPlanSnap = snap.modelPlan && !allowed.has(snap.modelPlan) ? "" : snap.modelPlan;
  const reconciledExecuteSnap = snap.modelExecute && !allowed.has(snap.modelExecute) ? "" : snap.modelExecute;
  defaultsSnapshotRef.current = {
    ...snap,
    modelPlan: reconciledPlanSnap,
    modelExecute: reconciledExecuteSnap,
    effortPlan: reconcileEffort(snap.effortPlan, reconciledPlanSnap, m.effort, m.defaults.effort_plan ?? "medium"),
    effortExecute: reconcileEffort(snap.effortExecute, reconciledExecuteSnap, m.effort, m.defaults.effort_execute ?? "medium"),
  };
}
setModelsResolved(true);
```

- [ ] **Step 8: Update catch block**

After existing `setField("modelExecute", "");`, add:
```typescript
setField("effortPlan", "");
setField("effortExecute", "");
```

And in `defaultsSnapshotRef.current` update within catch:
```typescript
defaultsSnapshotRef.current = {
  ...defaultsSnapshotRef.current,
  modelPlan: "",
  modelExecute: "",
  effortPlan: "",
  effortExecute: "",
};
```

- [ ] **Step 9: Add effort_plan/effort_execute to baseParams in handleSubmit**

After `model_execute: modelExecute || undefined,`:
```typescript
effort_plan: models?.effort ? effortPlan : undefined,
effort_execute: models?.effort ? effortExecute : undefined,
```

- [ ] **Step 10: Run tests to confirm effort defaults test passes**
```bash
cd /workspace/exam-generation/web && npx vitest run src/components/ParamForm.effort-selection.test.tsx 2>&1 | tail -20
```

---

### Task 4: Render effort dropdowns in the UI

**Files:**
- Modify: `web/src/components/ParamForm.tsx`

- [ ] **Step 1: Add computed effort level arrays**

After the `availableLearningContent` useMemo, add:
```typescript
const planEffortLevels = useMemo((): string[] => {
  if (!models?.effort) return [];
  if (modelPlan && models.effort[modelPlan]) return models.effort[modelPlan];
  // No model selected: show union of all levels
  return [...new Set(Object.values(models.effort).flat())];
}, [models, modelPlan]);

const executeEffortLevels = useMemo((): string[] => {
  if (!models?.effort) return [];
  if (modelExecute && models.effort[modelExecute]) return models.effort[modelExecute];
  return [...new Set(Object.values(models.effort).flat())];
}, [models, modelExecute]);
```

- [ ] **Step 2: Replace the model dropdowns UI section**

Replace the existing model dropdowns block:
```tsx
{models && models.allowed.length > 0 && (
  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
    <label className="flex flex-col gap-1 text-xs text-gray-700">
      <span>{t("params.model_plan_label")}</span>
      <select
        aria-label={t("params.model_plan_label")}
        value={modelPlan}
        onChange={(e) => setField("modelPlan", e.target.value)}
        className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
      >
        <option value="">
          {t("params.model_default_option")} ({models.defaults.plan})
        </option>
        {models.allowed.map((m) => (
          <option key={`plan-${m}`} value={m}>
            {m}
          </option>
        ))}
      </select>
    </label>
    <label className="flex flex-col gap-1 text-xs text-gray-700">
      <span>{t("params.model_execute_label")}</span>
      <select
        aria-label={t("params.model_execute_label")}
        value={modelExecute}
        onChange={(e) => setField("modelExecute", e.target.value)}
        className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
      >
        <option value="">
          {t("params.model_default_option")} ({models.defaults.execute})
        </option>
        {models.allowed.map((m) => (
          <option key={`exec-${m}`} value={m}>
            {m}
          </option>
        ))}
      </select>
    </label>
  </div>
)}
```

With:
```tsx
{models && models.allowed.length > 0 && (
  <div className="space-y-2">
    <div className="flex gap-2">
      <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
        <span>{t("params.model_plan_label")}</span>
        <select
          aria-label={t("params.model_plan_label")}
          value={modelPlan}
          onChange={(e) => {
            const newModel = e.target.value;
            setField("modelPlan", newModel);
            if (models.effort) {
              const levels = newModel ? (models.effort[newModel] ?? []) : [];
              setField("effortPlan", (prev) =>
                levels.length === 0 || levels.includes(prev) ? prev : "medium",
              );
            }
          }}
          className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
        >
          <option value="">
            {t("params.model_default_option")} ({models.defaults.plan})
          </option>
          {models.allowed.map((m) => (
            <option key={`plan-${m}`} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      {planEffortLevels.length > 0 && (
        <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
          <span>{t("form.effort_plan")}</span>
          <select
            aria-label={t("form.effort_plan")}
            value={effortPlan}
            onChange={(e) => setField("effortPlan", e.target.value)}
            className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
          >
            {planEffortLevels.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
    <div className="flex gap-2">
      <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
        <span>{t("params.model_execute_label")}</span>
        <select
          aria-label={t("params.model_execute_label")}
          value={modelExecute}
          onChange={(e) => {
            const newModel = e.target.value;
            setField("modelExecute", newModel);
            if (models.effort) {
              const levels = newModel ? (models.effort[newModel] ?? []) : [];
              setField("effortExecute", (prev) =>
                levels.length === 0 || levels.includes(prev) ? prev : "medium",
              );
            }
          }}
          className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
        >
          <option value="">
            {t("params.model_default_option")} ({models.defaults.execute})
          </option>
          {models.allowed.map((m) => (
            <option key={`exec-${m}`} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      {executeEffortLevels.length > 0 && (
        <label className="flex flex-1 flex-col gap-1 text-xs text-gray-700">
          <span>{t("form.effort_execute")}</span>
          <select
            aria-label={t("form.effort_execute")}
            value={effortExecute}
            onChange={(e) => setField("effortExecute", e.target.value)}
            className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm"
          >
            {executeEffortLevels.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  </div>
)}
```

- [ ] **Step 3: Run the effort-selection tests**
```bash
cd /workspace/exam-generation/web && npx vitest run src/components/ParamForm.effort-selection.test.tsx 2>&1 | tail -30
```

---

### Task 5: Add confirmation rows for effort

**Files:**
- Modify: `web/src/components/ParamForm.tsx`

- [ ] **Step 1: Add effort rows to the confirmation rows array**

In the `rows` array inside the `if (pendingParams)` block, after the model rows:
```typescript
{ label: t("form.confirm_model_plan"), value: p.model_plan, subjects: allSubjects, kind: "defaulted", defaultValue: t("form.confirm_system_default") },
{ label: t("form.confirm_model_execute"), value: p.model_execute, subjects: allSubjects, kind: "defaulted", defaultValue: t("form.confirm_system_default") },
```

Add after them (conditionally spread when models.effort exists):
```typescript
...(models?.effort ? ([
  { label: t("form.confirm_effort_plan"), value: p.effort_plan, subjects: allSubjects, kind: "defaulted" as const, defaultValue: t("form.confirm_system_default") },
  { label: t("form.confirm_effort_execute"), value: p.effort_execute, subjects: allSubjects, kind: "defaulted" as const, defaultValue: t("form.confirm_system_default") },
] satisfies ConfirmationRow[]) : []),
```

- [ ] **Step 2: Run all effort-selection tests**
```bash
cd /workspace/exam-generation/web && npx vitest run src/components/ParamForm.effort-selection.test.tsx 2>&1 | tail -30
```

- [ ] **Step 3: Run the full test suite**
```bash
cd /workspace/exam-generation/web && npx vitest run 2>&1 | tail -10
```
Expected: 60 files, 435 + N new tests, all passed.

- [ ] **Step 4: Verify TypeScript**
```bash
cd /workspace/exam-generation/web && npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.
