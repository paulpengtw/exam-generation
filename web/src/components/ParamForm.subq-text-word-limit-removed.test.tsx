/**
 * Tests verifying that the per-子題 文本字數限制 (text_word_limit) has been removed
 * from the 子題設定 form while preserving question_word_limit and option_word_limit.
 *
 * Slices:
 *  (a) Rendered UI — no text_word_limit control in 子題設定, question/option controls present
 *  (b) Submitted query string — subquestion_configs rows carry no text_word_limit
 *  (c) Stored draft with per-row text_word_limit — loads without error, not re-emitted on wire
 *  (d) Confirmation card — no per-子題 text-limit row; top-level 文本字數限制 row present
 *
 * Conservative behaviour for slice (c) per ADR 0023:
 * A draft / history value carrying per-row text_word_limit is accepted by the form
 * (no decode-time shim, no migration).  On re-submit serialisableSubquestionConfig
 * strips the field so it never reaches the server.  The server will 422 such a draft
 * only after #644 removes the field from the schema — an accepted cost.
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

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [8],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "開放式建構反應題", instruction: "" },
  ],
  數學思考: [],
  question_style: [],
  題目內容類型: [
    { value: "純文字", instruction: "" },
    { value: "含圖片", instruction: "" },
  ],
  科目: [{ value: "歷史", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

function subquestionRow(n: number) {
  return within(screen.getByText(`第${n}小題`).closest("div")!);
}

function requestQuery(subject: string, onSubmit: ReturnType<typeof vi.fn>): URLSearchParams {
  const formParams = onSubmit.mock.calls.at(-1)?.[0] as FormParams;
  return new URLSearchParams(
    buildQueryString(toGenerateParams(subject, formParams)),
  );
}

function setupMocks() {
  vi.clearAllMocks();
  window.localStorage.clear();
  getAvailableModelsMock.mockResolvedValue({
    allowed: [],
    defaults: { plan: "", execute: "" },
  });
  getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
  resolveGenerateMock.mockImplementation(
    async (payload: Record<string, unknown>) => ({ payload, drawn: [] }),
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Slice (a): rendered UI — 子題設定 shows no text_word_limit control
// ──────────────────────────────────────────────────────────────────────────────
describe("Slice (a) — 子題設定 UI", () => {
  beforeEach(setupMocks);

  it("renders no 文本字數限制 spinbutton in 子題設定 for a 社會領域 row", async () => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          grade: 8,
          set_type: "題組題",
          sub_question_count: 1,
          subquestion_configs: [{ question_type: "選擇題" }],
        }}
      />,
    );

    await screen.findByText("第1小題");
    const row = subquestionRow(1);

    // Only question_word_limit and option_word_limit spinbuttons should render
    expect(row.getAllByRole("spinbutton")).toHaveLength(2);
  });

  it("still renders question_word_limit and option_word_limit spinbuttons with correct initial values", async () => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          grade: 8,
          set_type: "題組題",
          sub_question_count: 1,
          subquestion_configs: [{ question_word_limit: 42, option_word_limit: 99 }],
        }}
      />,
    );

    await screen.findByText("第1小題");
    const row = subquestionRow(1);
    const spinbuttons = row.getAllByRole("spinbutton") as HTMLInputElement[];
    expect(spinbuttons).toHaveLength(2);
    expect(spinbuttons[0].value).toBe("42");
    expect(spinbuttons[1].value).toBe("99");
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Slice (b): submitted request — per-subquestion rows carry no text_word_limit
// ──────────────────────────────────────────────────────────────────────────────
describe("Slice (b) — submitted query string", () => {
  beforeEach(setupMocks);

  it("query string's per-subquestion rows carry no text_word_limit while question/option limits are present", async () => {
    const onSubmit = vi.fn();
    const historyRows = [{
      question_type: "選擇題",
      instruction: "舊出題指示",
      content_type: "純文字",
      image_generation_mode: "html",
      question_word_limit: 31,
      option_word_limit: 41,
    }];

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
          learning_performance: ["社全域-表現"],
          learning_content: ["社全域-內容"],
          sub_question_count: 1,
          subquestion_configs: JSON.stringify(historyRows),
          per_question_params: JSON.stringify([{
            seed: 6384,
            sub_question_count: 1,
            subquestion_configs: JSON.stringify(historyRows),
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const selects = firstRow.getAllByRole("combobox");
    fireEvent.change(selects[0], { target: { value: "選擇題" } });

    const wordLimits = firstRow.getAllByRole("spinbutton");
    expect(wordLimits).toHaveLength(2);
    fireEvent.change(wordLimits[0], { target: { value: "55" } });
    fireEvent.change(wordLimits[1], { target: { value: "66" } });

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const qs = requestQuery("social_studies", onSubmit);
    const perQuestion = JSON.parse(qs.get("per_question_params")!) as Array<{
      subquestion_configs: string;
    }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs) as Array<Record<string, unknown>>;

    // text_word_limit must NOT appear on the wire
    expect(rows[0]).not.toHaveProperty("text_word_limit");

    // question_word_limit and option_word_limit ARE preserved
    expect(rows[0]).toHaveProperty("question_word_limit", 55);
    expect(rows[0]).toHaveProperty("option_word_limit", 66);
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Slice (c): stored draft with per-row text_word_limit
// ──────────────────────────────────────────────────────────────────────────────
describe("Slice (c) — stored draft with per-row text_word_limit", () => {
  beforeEach(setupMocks);

  /**
   * Conservative behaviour per ADR 0023:
   * A draft or history value carrying per-row text_word_limit is accepted at
   * restore time (no decode-time migration, no error).  When the user re-submits,
   * serialisableSubquestionConfig strips text_word_limit so it never goes on the wire.
   */
  it("loads a draft with per-row text_word_limit without error and strips it on re-submit", async () => {
    const onSubmit = vi.fn();
    const historyRows = [{
      question_type: "選擇題",
      instruction: "舊出題指示",
      content_type: "純文字",
      image_generation_mode: "html",
      question_word_limit: 40,
      option_word_limit: 50,
      text_word_limit: 999, // stale per-row value from old draft — must NOT appear on wire
    }];

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
          learning_performance: [],
          learning_content: [],
          sub_question_count: 1,
          subquestion_configs: JSON.stringify(historyRows),
          per_question_params: JSON.stringify([{
            seed: 1234,
            sub_question_count: 1,
            subquestion_configs: JSON.stringify(historyRows),
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    // Form loads without error (no decode-time failure)
    await screen.findByText("第1小題");

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const qs = requestQuery("social_studies", onSubmit);
    const perQuestion = JSON.parse(qs.get("per_question_params")!) as Array<{
      subquestion_configs: string;
    }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs) as Array<Record<string, unknown>>;

    // text_word_limit must NOT appear on the wire
    expect(rows[0]).not.toHaveProperty("text_word_limit");

    // Other per-row fields are preserved
    expect(rows[0]).toHaveProperty("question_word_limit", 40);
    expect(rows[0]).toHaveProperty("option_word_limit", 50);
  });
});

// ──────────────────────────────────────────────────────────────────────────────
// Slice (d): confirmation screen — no per-子題 text-limit row
// ──────────────────────────────────────────────────────────────────────────────
describe("Slice (d) — confirmation screen", () => {
  beforeEach(setupMocks);

  it("shows no per-子題 text-limit input on the confirmation card", async () => {
    const historyRows = [{
      question_type: "選擇題",
      question_word_limit: 40,
      option_word_limit: 50,
    }];

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
          learning_performance: [],
          learning_content: [],
          text_word_limit: 200,
          sub_question_count: 1,
          subquestion_configs: JSON.stringify(historyRows),
          per_question_params: JSON.stringify([{
            seed: 5678,
            sub_question_count: 1,
            subquestion_configs: JSON.stringify(historyRows),
          }]),
        }}
        onSubmit={vi.fn()}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await screen.findByText("form.confirm_title");

    // Top-level 文本字數限制 confirmation row must still show
    expect(screen.getByText("form.confirm_text_word_limit")).toBeInTheDocument();

    // No per-子題 文本字數限制 input on the confirmation card
    expect(screen.queryByLabelText("form.confirm_subq_text_word_limit_input")).toBeNull();
  });

  it("per-子題 question_word_limit and option_word_limit confirmation inputs still render", async () => {
    const historyRows = [{
      question_type: "選擇題",
      question_word_limit: 40,
      option_word_limit: 50,
    }];

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
          learning_performance: [],
          learning_content: [],
          sub_question_count: 1,
          subquestion_configs: JSON.stringify(historyRows),
          per_question_params: JSON.stringify([{
            seed: 9012,
            sub_question_count: 1,
            subquestion_configs: JSON.stringify(historyRows),
          }]),
        }}
        onSubmit={vi.fn()}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await screen.findByText("form.confirm_title");

    // Per-小題 question/option word limit inputs still appear on confirmation
    expect(screen.getByLabelText("form.confirm_subq_q_word_limit_input")).toBeInTheDocument();
    expect(screen.getByLabelText("form.confirm_subq_o_word_limit_input")).toBeInTheDocument();
  });
});
