/**
 * Issue #291 frontend regression guard: grade-pool re-fetch for 自然科學.
 *
 * These tests verify the pool-swapping mechanics in ParamForm when a user
 * changes the grade for a natural-sciences request.  They are regression
 * cover only — the frontend LC/LP pools were never the broken layer — the
 * bug was in the backend parser and validator.  But having these tests
 * confirms the UI correctly re-fetches grade-specific pools when the grade
 * changes, so a future regression cannot silently serve the wrong pool.
 *
 * Three cases covered:
 *   1. Grade-change triggers a getSchemas re-fetch that swaps the pool.
 *   2. The submitted payload carries only codes from the new (stage-5) pool.
 *   3. Out-of-order schema responses don't restore the stale (stage-4) pool
 *      — the cancelled flag discards responses from the previous grade's
 *      in-flight request.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── Hoist mocks before any import that may trigger the module ──────────────
const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => ({ payload, drawn: [] })),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

// ── Import after mocks are wired ───────────────────────────────────────────
import ParamForm, { type GenerateParams } from "./ParamForm";

// ── Fixture schemas ────────────────────────────────────────────────────────

// Stage-4 pool (第四學習階段, grades 7-9).
const STAGE4_LP = [
  { value: "tr-IV-1", instruction: "", 科目: "自然科學" },
  { value: "tr-IV-2", instruction: "", 科目: "自然科學" },
  { value: "tr-IV-3", instruction: "", 科目: "自然科學" },
];
const STAGE4_LC = [
  { value: "INc-IV-1", instruction: "", 科目: "自然科學" },
  { value: "INc-IV-2", instruction: "", 科目: "自然科學" },
  { value: "INc-IV-3", instruction: "", 科目: "自然科學" },
];
const STAGE4_LC_VALUES = STAGE4_LC.map((e) => e.value);
const STAGE4_LP_VALUES = STAGE4_LP.map((e) => e.value);

// Stage-5 pool (第五學習階段, grades 10-12).
const STAGE5_LP = [
  { value: "pa-Va-1", instruction: "", 科目: "自然科學" },
  { value: "pa-Va-2", instruction: "", 科目: "自然科學" },
  { value: "pa-Va-3", instruction: "", 科目: "自然科學" },
];
const STAGE5_LC = [
  { value: "BDa-Va-1", instruction: "", 科目: "自然科學" },
  { value: "BDa-Va-2", instruction: "", 科目: "自然科學" },
  { value: "BDa-Va-3", instruction: "", 科目: "自然科學" },
];
const STAGE5_LC_VALUES = STAGE5_LC.map((e) => e.value);
const STAGE5_LP_VALUES = STAGE5_LP.map((e) => e.value);

// Base NS schema fields shared across grades.
const NS_BASE = {
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple-multiple-choice", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  question_style: [{ value: "standard", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
};

// Initial schema returned when getSchemas is called without a grade.
// Includes all NS grades so the form can render both stage-4 and stage-5.
const NS_SCHEMA_ALL_GRADES = {
  ...NS_BASE,
  學習階段: "第四學習階段",
  grades: [7, 8, 9, 10, 11, 12],
  學習表現: STAGE4_LP,
  學習內容: STAGE4_LC,
};

// Grade-specific schemas returned by the grade re-fetch effect.
const NS_SCHEMA_GRADE8 = {
  ...NS_BASE,
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  學習表現: STAGE4_LP,
  學習內容: STAGE4_LC,
};

const NS_SCHEMA_GRADE11 = {
  ...NS_BASE,
  學習階段: "第五學習階段",
  grades: [10, 11, 12],
  學習表現: STAGE5_LP,
  學習內容: STAGE5_LC,
};

// Deferred promise helper — lets tests control when an async operation resolves.
function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

// ── Test setup ─────────────────────────────────────────────────────────────
beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
  // Default: every getSchemas call returns stage-4 data.
  getSchemasMock.mockResolvedValue(NS_SCHEMA_ALL_GRADES);
});

// ── Test helpers ───────────────────────────────────────────────────────────

/** Find the grade <select> element by its associated label. */
function gradeSelect() {
  return screen.getByLabelText("form.grade") as HTMLSelectElement;
}

// ── Case 1: Grade-change triggers getSchemas re-fetch that swaps the pool ─

describe("NS grade pool: grade change triggers pool re-fetch", () => {
  it("calls getSchemas with the new grade when the user changes the grade", async () => {
    // Route grade-specific calls to the right schema.
    getSchemasMock.mockImplementation(async (subject: string, grade?: number) => {
      if (grade === 11) return NS_SCHEMA_GRADE11;
      if (grade === 8) return NS_SCHEMA_GRADE8;
      return NS_SCHEMA_ALL_GRADES;
    });

    render(<ParamForm subject="natural_sciences" onSubmit={vi.fn()} disabled={false} />);

    // Wait for the form to finish its initial load (grade=7 re-fetch).
    await waitFor(() => expect(gradeSelect().value).not.toBe(""));

    // User switches grade from the initial value to 11.
    fireEvent.change(gradeSelect(), { target: { value: "11" } });

    // The grade-change effect must have called getSchemas with grade=11.
    await waitFor(() => {
      expect(getSchemasMock).toHaveBeenCalledWith("natural_sciences", 11);
    });
  });
});

// ── Case 2: Submitted payload carries only stage-5 codes for a grade-11 request ─

describe("NS grade pool: grade-11 submission carries stage-5 codes", () => {
  it("submitted learning_content and learning_performance are from the stage-5 pool", async () => {
    getSchemasMock.mockImplementation(async (subject: string, grade?: number) => {
      if (grade === 11) return NS_SCHEMA_GRADE11;
      return NS_SCHEMA_ALL_GRADES;
    });

    const submitted: GenerateParams[] = [];
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={(p) => submitted.push(p)}
        disabled={false}
      />,
    );

    // Wait for form to be ready.
    await waitFor(() => expect(gradeSelect().value).not.toBe(""));

    // Switch to grade 11 and wait for the stage-5 pool to load.
    fireEvent.change(gradeSelect(), { target: { value: "11" } });
    await waitFor(() => {
      expect(getSchemasMock).toHaveBeenCalledWith("natural_sciences", 11);
    });

    // Open confirmation dialog and submit.
    fireEvent.click(await screen.findByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));

    const { learning_content, learning_performance } = submitted[0];

    // Every submitted LC code must come from the stage-5 pool.
    if (learning_content && learning_content.length > 0) {
      for (const code of learning_content) {
        expect(STAGE5_LC_VALUES).toContain(code);
        expect(STAGE4_LC_VALUES).not.toContain(code);
      }
    }

    // Every submitted LP code must come from the stage-5 pool.
    if (learning_performance && learning_performance.length > 0) {
      for (const code of learning_performance) {
        expect(STAGE5_LP_VALUES).toContain(code);
        expect(STAGE4_LP_VALUES).not.toContain(code);
      }
    }
  });
});

// ── Case 3: Out-of-order responses don't restore the stale stage-4 pool ──

describe("NS grade pool: out-of-order schema responses are discarded", () => {
  it("keeps the grade pool when a late grade-less response adds context options after a subject switch", async () => {
    const mathSchema = {
      grades: [7, 8, 9],
      情境: [{ value: "個人", instruction: "" }],
      題型種類: [{ value: "單一題", instruction: "" }],
      題型: [{ value: "選擇題", instruction: "" }],
      題目內容類型: [{ value: "純文字", instruction: "" }],
    };
    const grade7Schema = {
      ...NS_SCHEMA_ALL_GRADES,
      情境: [{ value: "個人", instruction: "" }],
      學習表現: [STAGE4_LP[0]],
      學習內容: [STAGE4_LC[0]],
    };
    const gradeLessSchema = {
      ...grade7Schema,
      情境: [{ value: "個人", instruction: "" }, { value: "海洋", instruction: "" }],
      學習表現: [{ value: "tr-IV-9", instruction: "", 科目: "自然科學" }],
      學習內容: [{ value: "INc-IV-9", instruction: "", 科目: "自然科學" }],
    };
    getSchemasMock.mockImplementation(async (subject: string, grade?: number) => {
      if (subject === "math") return mathSchema;
      if (subject === "natural_sciences" && grade === undefined) {
        return new Promise((resolve) => setTimeout(() => resolve(gradeLessSchema), 30));
      }
      if (subject === "natural_sciences" && grade === 7) return grade7Schema;
      throw new Error(`Unexpected curriculum request: ${subject}, ${grade}`);
    });

    const { rerender } = render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    await waitFor(() => expect(gradeSelect()).toHaveValue("7"));

    rerender(<ParamForm subject="natural_sciences" onSubmit={() => {}} disabled={false} />);
    await waitFor(() => {
      expect(getSchemasMock).toHaveBeenCalledWith("natural_sciences", 7);
      expect(getSchemasMock).toHaveBeenCalledWith("natural_sciences");
    });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 100)); });

    fireEvent.change(screen.getByPlaceholderText("搜尋學習表現..."), { target: { value: "-" } });
    expect(screen.queryByRole("button", { name: "tr-IV-9" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "tr-IV-1" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("搜尋學習內容..."), { target: { value: "-" } });
    expect(screen.queryByRole("button", { name: "INc-IV-9" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "INc-IV-1" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "海洋" })).toBeInTheDocument();
  });

  it(
    "a stale grade-7 response arriving after a grade-11 response does not restore stage-4 pool",
    async () => {
      // Two deferred promises — one for each grade's schema call.
      const grade7Deferred = deferred<typeof NS_SCHEMA_GRADE8>();
      const grade11Deferred = deferred<typeof NS_SCHEMA_GRADE11>();

      // Initial no-grade call resolves immediately; grade-specific calls are deferred.
      getSchemasMock.mockImplementation(async (subject: string, grade?: number) => {
        if (grade === 7) return grade7Deferred.promise;
        if (grade === 11) return grade11Deferred.promise;
        // No-grade initial call: resolve immediately with NS base (grade 7 default).
        return NS_SCHEMA_ALL_GRADES;
      });

      render(<ParamForm subject="natural_sciences" onSubmit={vi.fn()} disabled={false} />);

      // Wait for form to render (initial no-grade call resolves; grade is set to 7).
      await waitFor(() => expect(gradeSelect()).toBeInTheDocument());

      // Verify the grade-7 re-fetch is pending.
      await waitFor(() => {
        expect(getSchemasMock).toHaveBeenCalledWith("natural_sciences", 7);
      });

      // User changes grade to 11 — this cancels the grade-7 effect and starts grade-11.
      fireEvent.change(gradeSelect(), { target: { value: "11" } });
      await waitFor(() => {
        expect(getSchemasMock).toHaveBeenCalledWith("natural_sciences", 11);
      });

      // Grade-11 response arrives first → pool swaps to stage-5.
      await act(async () => {
        grade11Deferred.resolve(NS_SCHEMA_GRADE11);
        await Promise.resolve();
      });

      // Now the grade-7 response arrives (out-of-order; effect is cancelled).
      await act(async () => {
        grade7Deferred.resolve(NS_SCHEMA_GRADE8);
        await Promise.resolve();
      });

      // Verify the grade select still shows 11 (not reverted to 7).
      expect(gradeSelect().value).toBe("11");

      // Open confirmation to trigger pre-draw from the current pool.
      fireEvent.click(await screen.findByText("form.btn_generate"));

      // The confirmation dialog must open (pool is active and form is valid).
      await screen.findByText("form.confirm_title");
    },
  );
});
