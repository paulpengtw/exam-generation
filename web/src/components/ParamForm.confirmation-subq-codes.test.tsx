/**
 * #639 — Confirmation card 各小題配置 shows the live-picked codes (not history baseline).
 *
 * Each test drives the real per-小題 pickers, submits through 發送前確認, and asserts
 * BOTH that the confirmation card displays the expected code AND that the generated
 * query string agrees.  The card assertion is the primary TDD gate.
 *
 * The resolver mock mirrors the real server (ADR 0019/0022): it copies the top-level
 * subquestion_configs into each per_question_params row when the row doesn't already
 * carry its own.  This is the realistic shape for non-prefilled requests.
 *
 * Test matrix:
 *   1. SS LP pick, non-prefilled                → GREEN (resolver populates row configs)
 *   2. SS LC pick, non-prefilled                → GREEN
 *   3. SS prefilled, untouched sibling retains history code → GREEN
 *   4. SS prefilled, history code replaced by live pick    → GREEN
 *   5. NS LP pick, non-prefilled                → GREEN
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: resolveGenerateMock,
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm, { type FormParams } from "./ParamForm";
import { buildQueryString } from "../hooks/useGenerate";
import { toGenerateParams } from "../utils/toGenerateParams";

// ──────────────────────────────────────────────
// Shared code constants (disjoint namespaces)
// ──────────────────────────────────────────────

/** Global pool codes — auto-draw could select these; tests must not assert on them. */
const SS_GLOBAL_LP = "社全域-表現";
const SS_GLOBAL_LC = "社全域-內容";

/** User-picked codes — disjoint from the global pool; non-overlapping substrings. */
const SS_USER_LP = "社甲-表現";        // picked in 第1小題 LP (tests 1, 3, 4)
const SS_USER_LC = "社使用者-內容";    // picked in 第1小題 LC (test 2)
/** History baseline that an untouched sibling should retain. */
const SS_SIBLING_HISTORY_LP = "社兄弟-未觸碰表現"; // appears in history slot 1 (test 3)
/** Old history code that the live pick replaces. */
const SS_OLD_HISTORY_LP = "社舊-表現"; // appears in history slot 0, replaced by pick (test 4)

const NS_USER_LP = "自然使用者-表現";  // picked in 第1小題 LP (test 5)

// ──────────────────────────────────────────────
// Schema fixtures
// ──────────────────────────────────────────────

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [8],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  學習表現: [
    { value: SS_GLOBAL_LP,              instruction: "全域表現",     科目: "社", admitted_by: { 科目: ["歷史"] } },
    { value: SS_USER_LP,                instruction: "甲表現",       科目: "社", admitted_by: { 科目: ["歷史"] } },
    { value: SS_SIBLING_HISTORY_LP,     instruction: "兄弟表現",     科目: "社", admitted_by: { 科目: ["歷史"] } },
    { value: SS_OLD_HISTORY_LP,         instruction: "舊表現",       科目: "社", admitted_by: { 科目: ["歷史"] } },
  ],
  學習內容: [
    { value: SS_GLOBAL_LC,   instruction: "全域內容",       科目: "社", admitted_by: { 科目: ["歷史"] } },
    { value: SS_USER_LC,     instruction: "使用者挑選的內容", 科目: "社", admitted_by: { 科目: ["歷史"] } },
  ],
};

const NATURAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [8],
  情境: [{ value: "個人", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple multiple-choice", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  科學能力: [{ value: "探究能力", instruction: "" }],
  學習表現: [
    { value: "自然全域-表現", instruction: "全域表現", 科目: "自然科學" },
    { value: NS_USER_LP,      instruction: "使用者表現", 科目: "自然科學" },
  ],
  學習內容: [
    { value: "自然全域-內容", instruction: "全域內容", 科目: "自然科學" },
  ],
};

// ──────────────────────────────────────────────
// Realistic resolver mock (mirrors ADR 0019/0022)
// ──────────────────────────────────────────────

/**
 * Simulates what the real resolver does: materialises per_question_params rows
 * by merging the batch-level payload with each source row, and copies the
 * top-level subquestion_configs into any row that doesn't carry its own.
 * Extracted from ParamForm.confirmation-display.test.tsx to avoid duplication.
 */
function legacyConfirmationResolve(payload: Record<string, unknown>) {
  const rawRows = payload.per_question_params;
  const sourceRows = typeof rawRows === "string"
    ? JSON.parse(rawRows) as Record<string, unknown>[]
    : Array.isArray(rawRows)
      ? rawRows as Record<string, unknown>[]
      : [];
  const base = Object.fromEntries(
    Object.entries(payload).filter(([key]) => ![
      "subject", "count", "per_question_params", "drawn", "redraws",
    ].includes(key)),
  );
  const subject = payload.subject;
  const generatedSeed = typeof payload.seed !== "number";
  const seed = generatedSeed ? 900 : payload.seed as number;
  const resolvedRows = sourceRows.map((sourceRow, index) => {
    const row = { ...base, ...sourceRow };
    delete row.subject;
    delete row.count;
    delete row.per_question_params;
    delete row.drawn;
    delete row.redraws;
    if (sourceRow.seed === undefined || sourceRow.seed === null) row.seed = seed + index;
    if (row.context === undefined || (Array.isArray(row.context) && row.context.length === 0)) {
      row.context = [subject === "natural_sciences" ? "Personal" : "個人"];
    }
    if (row.subquestion_configs === undefined && payload.subquestion_configs !== undefined) {
      row.subquestion_configs = payload.subquestion_configs;
    }
    return row;
  });
  const drawn = sourceRows.flatMap((sourceRow, index) => {
    const paths: string[] = [];
    if (generatedSeed && (sourceRow.seed === undefined || sourceRow.seed === null)) {
      paths.push(`per_question_params[${index}].seed`);
    }
    if (sourceRow.context === undefined || (Array.isArray(sourceRow.context) && sourceRow.context.length === 0)) {
      paths.push(`per_question_params[${index}].情境`);
    }
    const rawConfigs = resolvedRows[index].subquestion_configs;
    const configs = typeof rawConfigs === "string"
      ? JSON.parse(rawConfigs) as Record<string, unknown>[]
      : Array.isArray(rawConfigs) ? rawConfigs as Record<string, unknown>[] : [];
    configs.forEach((config, subquestionIndex) => {
      if ((subject === "social_studies" || subject === "natural_sciences") && !config.question_type) {
        paths.push(`per_question_params[${index}].subquestion_configs[${subquestionIndex}].question_type`);
      }
      if (subject === "natural_sciences" && !config.reporting_scale) {
        paths.push(`per_question_params[${index}].subquestion_configs[${subquestionIndex}].reporting_scale`);
      }
    });
    return paths;
  });
  return {
    payload: {
      ...payload,
      ...(generatedSeed ? { seed } : {}),
      per_question_params: JSON.stringify(resolvedRows),
    },
    drawn: [...(generatedSeed ? ["seed"] : []), ...drawn],
  };
}

// ──────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────

/** Scope to the nth 小題 row in the FORM (1-indexed, by heading "第N小題"). */
function subquestionRow(index: number): ReturnType<typeof within> {
  return within(screen.getByText(`第${index}小題`).closest("div.rounded")!);
}

/** Build the final query string from the last onSubmit call. */
function requestQuery(subject: string, onSubmit: ReturnType<typeof vi.fn>): URLSearchParams {
  const formParams = onSubmit.mock.calls.at(-1)?.[0] as FormParams;
  return new URLSearchParams(buildQueryString(toGenerateParams(subject, formParams)));
}

/**
 * Submit the form and wait until the confirmation dialog has rendered.
 * Returns the "confirm send" button so callers can click it when ready.
 */
async function openConfirmation(): Promise<HTMLElement> {
  fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
  await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
  // findByText waits for the resolver promise to settle and React to re-render.
  return screen.findByText("form.btn_confirm_send");
}

// ──────────────────────────────────────────────
// Suite
// ──────────────────────────────────────────────

describe("ParamForm 確認頁 各小題配置 card shows live-picked codes — #639", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    // Realistic resolver mock: mirrors ADR 0019/0022 — copies top-level
    // subquestion_configs into each per_question_params row that lacks its own.
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) =>
      legacyConfirmationResolve(payload));
  });

  // ── Test 1: SS LP pick, non-prefilled ─────────────────────────────────────
  it("1 — SS non-prefilled LP pick: confirmation card shows the picked code (not empty)", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          // No global LP / LC so that auto-draw cannot accidentally produce the picked code.
          sub_question_count: 2,
          // No per_question_params → non-prefilled path.
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    // Pick LP in the first 小題 row.
    await screen.findByText("第1小題");
    const row1 = subquestionRow(1);
    const lpInput = row1.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: SS_USER_LP } });
    fireEvent.mouseDown(row1.getByRole("button", { name: new RegExp(SS_USER_LP) }));

    // Submit and wait for the confirmation dialog.
    const confirmBtn = await openConfirmation();

    // ── Card assertion (RED before fix / GREEN after fix) ──────────────────
    // The subquestion config section must be rendered with the picked LP code
    // visible as a selected chip inside the confirmation LP picker.
    expect(screen.getByText(SS_USER_LP)).toBeInTheDocument();

    // Click confirm.
    fireEvent.click(confirmBtn);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    // ── Query string agrees with card ──────────────────────────────────────
    const query = requestQuery("social_studies", onSubmit);
    const subqConfigs = JSON.parse(query.get("subquestion_configs")!) as Array<{ learning_performance?: string[] }>;
    expect(subqConfigs[0].learning_performance).toEqual([SS_USER_LP]);
  });

  // ── Test 2: SS LC pick, non-prefilled ─────────────────────────────────────
  it("2 — SS non-prefilled LC pick: confirmation card shows the picked code (not empty)", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          // No global LP / LC.
          sub_question_count: 2,
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    // Pick LC in the first 小題 row.
    await screen.findByText("第1小題");
    const row1 = subquestionRow(1);
    const lcInput = row1.getByPlaceholderText("搜尋學習內容...");
    fireEvent.change(lcInput, { target: { value: SS_USER_LC } });
    fireEvent.mouseDown(row1.getByRole("button", { name: new RegExp(SS_USER_LC) }));

    const confirmBtn = await openConfirmation();

    // ── Card assertion ─────────────────────────────────────────────────────
    expect(screen.getByText(SS_USER_LC)).toBeInTheDocument();

    fireEvent.click(confirmBtn);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    // ── Query string ───────────────────────────────────────────────────────
    const query = requestQuery("social_studies", onSubmit);
    const subqConfigs = JSON.parse(query.get("subquestion_configs")!) as Array<{ learning_content?: string[] }>;
    expect(subqConfigs[0].learning_content).toEqual([SS_USER_LC]);
  });

  // ── Test 3: SS prefilled, untouched sibling retains history code ──────────
  it("3 — SS prefilled, 第2小題 history code survives while 第1小題 shows live pick", async () => {
    const onSubmit = vi.fn();
    // History has subquestion_configs: slot 0 is empty, slot 1 has the sibling code.
    const historySubqConfigs = JSON.stringify([
      {},
      { learning_performance: [SS_SIBLING_HISTORY_LP] },
    ]);
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          learning_performance: [SS_GLOBAL_LP],
          learning_content: [SS_GLOBAL_LC],
          sub_question_count: 2,
          per_question_params: JSON.stringify([{
            seed: 6391,
            sub_question_count: 2,
            learning_performance: [SS_GLOBAL_LP],
            learning_content: [SS_GLOBAL_LC],
            subquestion_configs: historySubqConfigs,
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    // Pick LP in 第1小題 only; leave 第2小題 untouched.
    await screen.findByText("第1小題");
    const row1 = subquestionRow(1);
    const lpInput = row1.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: SS_USER_LP } });
    fireEvent.mouseDown(row1.getByRole("button", { name: new RegExp(SS_USER_LP) }));

    const confirmBtn = await openConfirmation();

    // ── Card assertions ────────────────────────────────────────────────────
    // 第1小題: shows the live-picked code.
    expect(screen.getByText(SS_USER_LP)).toBeInTheDocument();
    // 第2小題: shows the untouched sibling's history code.
    expect(screen.getByText(SS_SIBLING_HISTORY_LP)).toBeInTheDocument();

    fireEvent.click(confirmBtn);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    // ── Query string ───────────────────────────────────────────────────────
    const query = requestQuery("social_studies", onSubmit);
    const perQuestion = JSON.parse(query.get("per_question_params")!) as Array<{ subquestion_configs: string }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs) as Array<{ learning_performance?: string[] }>;
    expect(rows[0].learning_performance).toEqual([SS_USER_LP]);
    expect(rows[1].learning_performance).toEqual([SS_SIBLING_HISTORY_LP]);
  });

  // ── Test 4: SS prefilled, history code replaced by live pick ──────────────
  it("4 — SS prefilled, live pick replaces old history LP code in card and query", async () => {
    const onSubmit = vi.fn();
    // History has the old code in slot 0.
    const historySubqConfigs = JSON.stringify([
      { learning_performance: [SS_OLD_HISTORY_LP] },
    ]);
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          learning_performance: [SS_GLOBAL_LP],
          learning_content: [SS_GLOBAL_LC],
          sub_question_count: 2,
          per_question_params: JSON.stringify([{
            seed: 6392,
            sub_question_count: 2,
            learning_performance: [SS_GLOBAL_LP],
            learning_content: [SS_GLOBAL_LC],
            subquestion_configs: historySubqConfigs,
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    // Pick LP in 第1小題 (replaces the old history code).
    await screen.findByText("第1小題");
    const row1 = subquestionRow(1);
    const lpInput = row1.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: SS_USER_LP } });
    fireEvent.mouseDown(row1.getByRole("button", { name: new RegExp(SS_USER_LP) }));

    const confirmBtn = await openConfirmation();

    // ── Card assertions ────────────────────────────────────────────────────
    // New code is visible.
    expect(screen.getByText(SS_USER_LP)).toBeInTheDocument();
    // Old history code is NOT visible (it was replaced).
    expect(screen.queryByText(SS_OLD_HISTORY_LP)).not.toBeInTheDocument();

    fireEvent.click(confirmBtn);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    // ── Query string ───────────────────────────────────────────────────────
    const query = requestQuery("social_studies", onSubmit);
    const perQuestion = JSON.parse(query.get("per_question_params")!) as Array<{ subquestion_configs: string }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs) as Array<{ learning_performance?: string[] }>;
    expect(rows[0].learning_performance).toEqual([SS_USER_LP]);
    expect(rows[0].learning_performance).not.toContain(SS_OLD_HISTORY_LP);
  });

  // ── Test 5: NS LP pick, non-prefilled ─────────────────────────────────────
  it("5 — NS non-prefilled LP pick: confirmation card shows the picked code (not empty)", async () => {
    getSchemasMock.mockResolvedValue(NATURAL_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        initialParams={{
          grade: 8,
          context: ["個人"],
          sub_context: "健康",
          set_type: "題組題",
          q_type: ["Simple multiple-choice"],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          science_competency: ["探究能力"],
          learning_performance: ["自然全域-表現"],
          learning_content: ["自然全域-內容"],
          sub_question_count: 2,
          // No per_question_params → non-prefilled path.
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    // Pick LP in 第1小題.
    await screen.findByText("第1小題");
    const row1 = subquestionRow(1);
    const lpInput = row1.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: NS_USER_LP } });
    fireEvent.mouseDown(row1.getByRole("button", { name: new RegExp(NS_USER_LP) }));

    const confirmBtn = await openConfirmation();

    // ── Card assertion ─────────────────────────────────────────────────────
    expect(screen.getByText(NS_USER_LP)).toBeInTheDocument();

    fireEvent.click(confirmBtn);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    // ── Query string ───────────────────────────────────────────────────────
    const query = requestQuery("natural_sciences", onSubmit);
    const subqConfigs = JSON.parse(query.get("subquestion_configs")!) as Array<{ learning_performance?: string[] }>;
    expect(subqConfigs[0].learning_performance).toEqual([NS_USER_LP]);
  });
});
