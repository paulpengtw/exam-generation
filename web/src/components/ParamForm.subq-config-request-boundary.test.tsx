/**
 * #640 — Characterisation tests for the 各小題配置 submit path, asserted at the
 * request boundary (the built query string).
 *
 * These tests cover the matrix cells NOT already covered by the six tests in
 * ParamForm.prefill-live-subq-edits.test.tsx (the #656 suite).  Each test drives
 * the real per-小題 pickers, submits through 發送前確認, and asserts on the query
 * string produced by the real buildQueryString.  Picked codes are drawn from a
 * namespace disjoint from the 全域池 so auto-draw can never produce them by chance.
 *
 * Coverage audit — cells already covered by the #656 suite (not duplicated here):
 *   1. SS, prefilled, history no per-小題 codes, LP pick on 第1小題, 1 題組
 *   2. SS, prefilled, history with per-小題 codes, LP pick (clear+pick), 第1小題,
 *      untouched sibling, 1 題組
 *   3. SS, prefilled, history no per-小題 codes, LC pick on 第1小題, 1 題組
 *   4. SS, prefilled, history with per-小題 codes, 題型/出題指示/圖片/字數 edit, 1 題組
 *   5. NS, prefilled, history no per-小題 codes, LP pick on 第1小題, 1 題組
 *   6. SS, non-prefilled, WITH 全域 LP, LP pick on 第1小題, 1 題組
 *
 * New cells added in this file:
 *   A. SS, non-prefilled, WITHOUT 全域 LP, LP pick on 第1小題
 *   B. SS, prefilled, history no per-小題 codes: LP pick on 第2小題 (later subquestion)
 *   C. SS, prefilled, multiple 題組 (count = 2), LP pick on first 小題 of first 題組
 *   D. SS, prefilled, 題組 count mismatch (per_question_params length ≠ form count)
 *   E. NS, non-prefilled (no history), LP pick on 第1小題
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
// Schema fixtures
// ──────────────────────────────────────────────

/**
 * Codes in the 全域池 that auto-draw could select. Tests must never assert on
 * these values, so the suite reliably turns red if the #638 fix is reverted.
 */
const SS_GLOBAL_LP = "社全域-表現";
const SS_GLOBAL_LC = "社全域-內容";

/**
 * Disjoint user-picked codes for 社會領域 — auto-draw cannot produce these.
 * These names are chosen to be non-overlapping substrings of each other so that
 * a SearchPicker search for one code never shows both in the dropdown simultaneously.
 */
const SS_USER_LP = "社甲-表現";     // picked on 第1小題 (tests A, C, D)
const SS_USER_LP_ROW2 = "社乙-表現"; // picked on 第2小題 (test B)

/** Disjoint user-picked code for 自然科學. */
const NS_USER_LP = "自然使用者-表現";

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [8],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "社使用者-題型", instruction: "使用者挑選的題型" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  學習表現: [
    { value: SS_GLOBAL_LP, instruction: "全域表現", 科目: "社", admitted_by: { 科目: ["歷史"] } },
    { value: SS_USER_LP, instruction: "甲表現", 科目: "社", admitted_by: { 科目: ["歷史"] } },
    { value: SS_USER_LP_ROW2, instruction: "乙表現", 科目: "社", admitted_by: { 科目: ["歷史"] } },
    { value: "社兄弟-未觸碰表現", instruction: "兄弟表現", 科目: "社", admitted_by: { 科目: ["歷史"] } },
  ],
  學習內容: [
    { value: SS_GLOBAL_LC, instruction: "全域內容", 科目: "社", admitted_by: { 科目: ["歷史"] } },
    { value: "社使用者-內容", instruction: "使用者挑選的內容", 科目: "社", admitted_by: { 科目: ["歷史"] } },
  ],
};

const NATURAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [8],
  情境: [{ value: "個人", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "Simple multiple-choice", instruction: "" },
    { value: "Complex multiple-choice", instruction: "" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  科學能力: [{ value: "探究能力", instruction: "" }],
  學習表現: [
    { value: "自然全域-表現", instruction: "全域表現", 科目: "自然科學" },
    { value: NS_USER_LP, instruction: "使用者挑選的表現", 科目: "自然科學" },
  ],
  學習內容: [
    { value: "自然全域-內容", instruction: "全域內容", 科目: "自然科學" },
  ],
};

// ──────────────────────────────────────────────
// Helpers (same pattern as the #656 suite)
// ──────────────────────────────────────────────

/** Returns a `within` scope for the nth 小題 row on the form (1-indexed). */
function subquestionRow(index: number): ReturnType<typeof within> {
  return within(screen.getByText(`第${index}小題`).closest("div.rounded")!);
}

function requestQuery(subject: string, onSubmit: ReturnType<typeof vi.fn>): URLSearchParams {
  const formParams = onSubmit.mock.calls.at(-1)?.[0] as FormParams;
  return new URLSearchParams(buildQueryString(toGenerateParams(subject, formParams)));
}

async function submitAndConfirm(onSubmit: ReturnType<typeof vi.fn>) {
  fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
  await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
  fireEvent.click(await screen.findByText("form.btn_confirm_send"));
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
}

// ──────────────────────────────────────────────
// Suite
// ──────────────────────────────────────────────

describe("ParamForm 各小題配置 submit-path characterisation (request boundary) — #640", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({
      payload,
      drawn: [],
    }));
  });

  // ── Cell A: SS, non-prefilled, WITHOUT 全域 LP ─────────────────────────────
  it("Cell A — SS non-prefilled, no 全域 LP: picked 第1小題 LP lands in top-level subquestion_configs", async () => {
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
          // No learning_performance / learning_content — 全域池 is deliberately empty
          sub_question_count: 2,
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const lpInput = firstRow.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: SS_USER_LP } });
    fireEvent.mouseDown(firstRow.getByRole("button", { name: new RegExp(SS_USER_LP) }));

    await submitAndConfirm(onSubmit);

    const query = requestQuery("social_studies", onSubmit);
    // Non-prefilled: subq codes land in top-level subquestion_configs; per_question_params = [{}]
    const subqConfigs = JSON.parse(query.get("subquestion_configs")!) as Array<{ learning_performance?: string[] }>;
    expect(subqConfigs[0].learning_performance).toEqual([SS_USER_LP]);
    expect(JSON.parse(query.get("per_question_params")!)).toEqual([{}]);
  });

  // ── Cell B: SS, prefilled, LP pick on 第2小題 (later subquestion) ──────────
  it("Cell B — SS prefilled, history no per-小題 codes: LP pick on 第2小題 lands in slot 1, slot 0 is empty", async () => {
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
          learning_performance: [SS_GLOBAL_LP],
          learning_content: [SS_GLOBAL_LC],
          sub_question_count: 2,
          per_question_params: JSON.stringify([{
            seed: 6401,
            sub_question_count: 2,
            learning_performance: [SS_GLOBAL_LP],
            learning_content: [SS_GLOBAL_LC],
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第2小題");
    // Pick LP on the SECOND 小題 row (not the first)
    const secondRow = subquestionRow(2);
    const lpInput = secondRow.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: SS_USER_LP_ROW2 } });
    fireEvent.mouseDown(secondRow.getByRole("button", { name: new RegExp(SS_USER_LP_ROW2) }));

    await submitAndConfirm(onSubmit);

    const query = requestQuery("social_studies", onSubmit);
    const perQuestion = JSON.parse(query.get("per_question_params")!) as Array<{ subquestion_configs: string }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs) as Array<{ learning_performance?: string[] }>;
    // 第1小題 (slot 0) untouched: no LP
    expect(rows[0].learning_performance).toBeUndefined();
    // 第2小題 (slot 1) has the picked code
    expect(rows[1].learning_performance).toEqual([SS_USER_LP_ROW2]);
  });

  // ── Cell C: SS, prefilled, multiple 題組 (count = 2) ──────────────────────
  it("Cell C — SS prefilled, multiple 題組 (count=2): LP pick on 第1小題 of first 題組 lands in per_question_params[0]", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 2,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          learning_performance: [SS_GLOBAL_LP],
          learning_content: [SS_GLOBAL_LC],
          sub_question_count: 2,
          per_question_params: JSON.stringify([
            {
              seed: 6402,
              sub_question_count: 2,
              learning_performance: [SS_GLOBAL_LP],
              learning_content: [SS_GLOBAL_LC],
            },
            {
              seed: 6403,
              sub_question_count: 2,
              learning_performance: [SS_GLOBAL_LP],
              learning_content: [SS_GLOBAL_LC],
            },
          ]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const lpInput = firstRow.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: SS_USER_LP } });
    fireEvent.mouseDown(firstRow.getByRole("button", { name: new RegExp(SS_USER_LP) }));

    await submitAndConfirm(onSubmit);

    const query = requestQuery("social_studies", onSubmit);
    const perQuestion = JSON.parse(query.get("per_question_params")!) as Array<{ subquestion_configs: string }>;
    // Should have 2 entries for 2 題組
    expect(perQuestion).toHaveLength(2);
    // First 題組, 第1小題: has the picked code
    const rows0 = JSON.parse(perQuestion[0].subquestion_configs) as Array<{ learning_performance?: string[] }>;
    expect(rows0[0].learning_performance).toEqual([SS_USER_LP]);
    // Second 題組 also has subquestion_configs (shares the same live state)
    expect(typeof perQuestion[1].subquestion_configs).toBe("string");
  });

  // ── Cell D: SS, prefilled, 題組 count mismatch ────────────────────────────
  it("Cell D — SS prefilled, count mismatch (per_question_params entries < count): falls back to non-prefilled path", async () => {
    const onSubmit = vi.fn();
    // Form requests count=2 but per_question_params only has 1 entry → count mismatch
    // → hasHistoryPerQuestionParams = false → non-prefilled path
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 2,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          learning_performance: [SS_GLOBAL_LP],
          learning_content: [SS_GLOBAL_LC],
          sub_question_count: 2,
          // Only 1 entry but count=2 → mismatch
          per_question_params: JSON.stringify([{
            seed: 6404,
            sub_question_count: 2,
            learning_performance: [SS_GLOBAL_LP],
            learning_content: [SS_GLOBAL_LC],
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const lpInput = firstRow.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: SS_USER_LP } });
    fireEvent.mouseDown(firstRow.getByRole("button", { name: new RegExp(SS_USER_LP) }));

    await submitAndConfirm(onSubmit);

    const query = requestQuery("social_studies", onSubmit);
    // Count mismatch → non-prefilled path: per-小題 codes land in top-level subquestion_configs
    const subqConfigs = JSON.parse(query.get("subquestion_configs")!) as Array<{ learning_performance?: string[] }>;
    expect(subqConfigs[0].learning_performance).toEqual([SS_USER_LP]);
    // per_question_params has 2 empty entries (for count=2)
    const perQuestion = JSON.parse(query.get("per_question_params")!) as Array<Record<string, unknown>>;
    expect(perQuestion).toHaveLength(2);
    expect(perQuestion[0]).toEqual({});
    expect(perQuestion[1]).toEqual({});
  });

  // ── Cell E: NS, non-prefilled, LP pick ────────────────────────────────────
  it("Cell E — NS non-prefilled: picked 第1小題 LP appears in top-level subquestion_configs", async () => {
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
          // No per_question_params → non-prefilled path
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const lpInput = firstRow.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: NS_USER_LP } });
    fireEvent.mouseDown(firstRow.getByRole("button", { name: new RegExp(NS_USER_LP) }));

    await submitAndConfirm(onSubmit);

    const query = requestQuery("natural_sciences", onSubmit);
    // Non-prefilled: per-小題 LP lands in top-level subquestion_configs
    const subqConfigs = JSON.parse(query.get("subquestion_configs")!) as Array<{ learning_performance?: string[] }>;
    expect(subqConfigs[0].learning_performance).toEqual([NS_USER_LP]);
    expect(JSON.parse(query.get("per_question_params")!)).toEqual([{}]);
  });
});
