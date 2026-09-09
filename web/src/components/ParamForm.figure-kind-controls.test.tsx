/**
 * Tests for issue #450 — ParamForm UI for 圖像種類 controls.
 *
 * Slices covered:
 *   (b)  子題設定 row renders the 圖像種類 control listing canonical values
 *   (c)  picking a canonical value sends figure_kind in that 小題's config
 *   (d)  free text is accepted and sent verbatim
 *   (e)  toggle off → no allow_duplicate_figure_kinds in query; on → true
 *   (f)  confirmation rows show figure_kind when set, toggle when on
 *   (g)  draft persistence and history prefill round-trip
 *   (h)  math shows neither control
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
  useT: () => (key: string) => {
    if (key === "form.figure_kind_input") return "圖像種類";
    if (key === "form.figure_kind_placeholder") return "例如：直方圖";
    if (key === "form.allow_duplicate_figure_kinds_label") return "允許圖像種類重複";
    if (key === "form.confirm_allow_duplicate_figure_kinds") return "允許圖像種類重複";
    if (key === "form.confirm_subq_figure_kind") return "圖像種類:";
    if (key === "form.confirm_subq_figure_kind_input") return "圖像種類";
    if (key === "form.confirm_title") return "發送前確認設定";
    if (key === "form.btn_generate") return "form.btn_generate";
    if (key === "form.btn_confirm_send") return "form.btn_confirm_send";
    if (key === "form.confirm_yes") return "是";
    if (key === "form.confirm_no") return "否";
    return key;
  },
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm, { type FormParams } from "./ParamForm";
import { buildQueryString } from "../hooks/useGenerate";
import { toGenerateParams } from "../utils/toGenerateParams";
import { saveDraft, loadDraft } from "../lib/formDraft";

const FIGURE_KINDS = ["直方圖", "長條圖", "圓餅圖", "表格", "地圖"];

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "社會選擇題", instruction: "" },
    { value: "社會開放題", instruction: "" },
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
  figure_kinds: FIGURE_KINDS,
};

const NATURAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "Simple multiple-choice", instruction: "" },
    { value: "Constructed response", instruction: "" },
  ],
  數學思考: [],
  question_style: [],
  題目內容類型: [
    { value: "純文字", instruction: "" },
    { value: "含圖片", instruction: "" },
  ],
  科目: [],
  學習表現: [],
  學習內容: [],
  figure_kinds: FIGURE_KINDS,
};

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
  // no figure_kinds for math
};

function subquestionRow(index: number): ReturnType<typeof within> {
  return within(screen.getByText(`第${index}小題`).closest("div")!);
}

function requestQuery(subject: string, onSubmit: ReturnType<typeof vi.fn>): URLSearchParams {
  const formParams = onSubmit.mock.calls.at(-1)?.[0] as FormParams;
  return new URLSearchParams(
    buildQueryString(toGenerateParams(subject, formParams)),
  );
}

// ──────────────────────────────────────────────
// Realistic resolver mock (mirrors ADR 0019/0022)
// ──────────────────────────────────────────────
/**
 * Simulates what the real resolver does: materialises per_question_params rows
 * by merging the batch-level payload with each source row, and copies the
 * top-level subquestion_configs into any row that doesn't carry its own.
 * Matches the helper in ParamForm.confirmation-display.test.tsx and
 * ParamForm.confirmation-subq-codes.test.tsx (extracted inline to avoid a
 * shared-test-util import).
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

describe("ParamForm 圖像種類 controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    resolveGenerateMock.mockImplementation(
      async (payload: Record<string, unknown>) => legacyConfirmationResolve(payload),
    );
  });

  // ---------------------------------------------------------------------------
  // Slice (b): 子題設定 row renders the 圖像種類 control listing canonical values
  // ---------------------------------------------------------------------------

  it("(b) social_studies 子題設定 row renders the 圖像種類 control with canonical datalist", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ sub_question_count: 2, subquestion_configs: [{}, {}] }}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    // Label must be rendered
    expect(firstRow.getByText("圖像種類", { selector: "label" })).toBeInTheDocument();
    // The text input for figure_kind
    const input = firstRow.getByPlaceholderText("例如：直方圖");
    expect(input).toBeInTheDocument();
    expect(input.tagName).toBe("INPUT");
  });

  it("(b) natural_sciences 子題設定 row renders the 圖像種類 control", async () => {
    getSchemasMock.mockResolvedValue(NATURAL_SCHEMA);
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ sub_question_count: 2, subquestion_configs: [{}, {}] }}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    expect(firstRow.getByText("圖像種類", { selector: "label" })).toBeInTheDocument();
    expect(firstRow.getByPlaceholderText("例如：直方圖")).toBeInTheDocument();
  });

  it("(b) datalist option contains canonical kind entries", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ sub_question_count: 1, subquestion_configs: [{}] }}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const input = firstRow.getByPlaceholderText("例如：直方圖");
    // The datalist is referenced by the input's list attribute
    const listId = input.getAttribute("list");
    expect(listId).toBeTruthy();
    const datalist = document.getElementById(listId!);
    expect(datalist).toBeInTheDocument();
    const options = datalist!.querySelectorAll("option");
    const optionValues = Array.from(options).map((o) => o.getAttribute("value") ?? o.textContent ?? "");
    for (const kind of FIGURE_KINDS) {
      expect(optionValues).toContain(kind);
    }
  });

  // ---------------------------------------------------------------------------
  // Slice (c): picking a canonical value sends figure_kind in config row
  // ---------------------------------------------------------------------------

  it("(c) selecting a canonical 圖像種類 sends it in subquestion_configs", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ sub_question_count: 2, subquestion_configs: [{}, {}] }}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const input = firstRow.getByPlaceholderText("例如：直方圖");
    fireEvent.change(input, { target: { value: "直方圖" } });

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const query = requestQuery("social_studies", onSubmit);
    const configs = JSON.parse(query.get("subquestion_configs")!) as Array<{
      figure_kind?: string;
    }>;
    expect(configs[0].figure_kind).toBe("直方圖");
    expect(configs[1].figure_kind).toBeUndefined();
  });

  // ---------------------------------------------------------------------------
  // Slice (d): free text is accepted and sent verbatim
  // ---------------------------------------------------------------------------

  it("(d) free-text 圖像種類 value is sent verbatim", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ sub_question_count: 1, subquestion_configs: [{}] }}
      />,
    );

    await screen.findByText("第1小題");
    const input = subquestionRow(1).getByPlaceholderText("例如：直方圖");
    fireEvent.change(input, { target: { value: "電路圖" } });

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const query = requestQuery("social_studies", onSubmit);
    const configs = JSON.parse(query.get("subquestion_configs")!) as Array<{
      figure_kind?: string;
    }>;
    expect(configs[0].figure_kind).toBe("電路圖");
  });

  // ---------------------------------------------------------------------------
  // Slice (e): toggle off → no allow_duplicate_figure_kinds; on → true
  // ---------------------------------------------------------------------------

  it("(e) allow_duplicate_figure_kinds toggle is absent when social_studies form loads with toggle off", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ sub_question_count: 1, subquestion_configs: [{}] }}
      />,
    );

    await screen.findByText("第1小題");
    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const query = requestQuery("social_studies", onSubmit);
    expect(query.has("allow_duplicate_figure_kinds")).toBe(false);
  });

  it("(e) allow_duplicate_figure_kinds=true when toggle is checked (social_studies)", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ sub_question_count: 1, subquestion_configs: [{}] }}
      />,
    );

    await screen.findByText("第1小題");
    // Find and check the toggle checkbox
    const checkbox = screen.getByRole("checkbox", { name: "允許圖像種類重複" });
    fireEvent.click(checkbox);

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const query = requestQuery("social_studies", onSubmit);
    expect(query.get("allow_duplicate_figure_kinds")).toBe("true");
  });

  it("(e) allow_duplicate_figure_kinds toggle works for natural_sciences", async () => {
    getSchemasMock.mockResolvedValue(NATURAL_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ sub_question_count: 1, subquestion_configs: [{}] }}
      />,
    );

    await screen.findByText("第1小題");
    const checkbox = screen.getByRole("checkbox", { name: "允許圖像種類重複" });
    fireEvent.click(checkbox);

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const query = requestQuery("natural_sciences", onSubmit);
    expect(query.get("allow_duplicate_figure_kinds")).toBe("true");
  });

  // ---------------------------------------------------------------------------
  // Slice (f): confirmation rows
  // ---------------------------------------------------------------------------

  it("(f) 發送前確認 shows figure_kind when set on a 小題", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          sub_question_count: 1,
          subquestion_configs: [{ figure_kind: "圓餅圖" }],
        }}
      />,
    );

    await screen.findByText("第1小題");
    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    await screen.findByRole("heading", { name: "發送前確認設定" });

    // The confirmation should display the figure_kind value
    expect(screen.getByText("圓餅圖")).toBeInTheDocument();
  });

  it("(f) 發送前確認 shows 允許圖像種類重複 row when toggle is on", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ sub_question_count: 1, subquestion_configs: [{}] }}
      />,
    );

    await screen.findByText("第1小題");
    const checkbox = screen.getByRole("checkbox", { name: "允許圖像種類重複" });
    fireEvent.click(checkbox);

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    await screen.findByRole("heading", { name: "發送前確認設定" });

    // The confirmation should contain the toggle label
    expect(screen.getByText("允許圖像種類重複", { selector: "dt" })).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Slice (g): draft persistence round-trip
  // ---------------------------------------------------------------------------

  it("(g) figure_kind in subquestion_configs is persisted and restored through draft", () => {
    const userId = "test-user-figure-kind";
    // Build a draft fields object that includes figure_kind in subquestionConfigs
    const fields = {
      grade: 8 as number | "",
      style: "",
      contentType: "含圖片",
      customContentType: "",
      context: [] as string[],
      setType: "題組題",
      qType: [] as string[],
      count: 1,
      coverageMode: "balanced" as const,
      skipVerify: false,
      disableReferenceFewshot: false,
      coreQuestionCallback: true,
      imageGenerationMode: "html" as const,
      difficulty: "" as const,
      reportingScale: "",
      subjectFilter: "",
      passage: "",
      textWordLimit: null,
      textInstruction: "",
      options: [] as string[],
      topic: "",
      coreQuestion: null,
      subContext: "",
      scienceCompetency: [] as string[],
      learningPerformance: [] as string[],
      learningContent: [] as string[],
      subQuestionCount: 2 as number | "",
      subquestionConfigs: [
        { figure_kind: "直方圖" },
        { figure_kind: "表格" },
      ],
      modelPlan: "",
      modelExecute: "",
      modelVerify: "",
      modelCorrect: "",
      effortPlan: "",
      effortExecute: "",
      effortVerify: "",
      effortCorrect: "",
      allowDuplicateFigureKinds: true,
    };

    saveDraft(userId, fields);
    const restored = loadDraft(userId);

    expect(restored).not.toBeNull();
    expect(restored!.fields.subquestionConfigs[0]).toMatchObject({ figure_kind: "直方圖" });
    expect(restored!.fields.subquestionConfigs[1]).toMatchObject({ figure_kind: "表格" });
    expect(restored!.fields.allowDuplicateFigureKinds).toBe(true);
  });

  it("(g) old draft without allowDuplicateFigureKinds or figure_kind loads without error (defaults false)", () => {
    const userId = "test-user-old-draft";
    // Simulate an old draft stored before issue #450 (no figure_kind, no allowDuplicateFigureKinds)
    const oldDraft = {
      savedAt: new Date().toISOString(),
      fields: {
        grade: 8,
        style: "",
        contentType: "含圖片",
        customContentType: "",
        context: [],
        setType: "題組題",
        qType: [],
        count: 1,
        coverageMode: "balanced",
        skipVerify: false,
        disableReferenceFewshot: false,
        coreQuestionCallback: true,
        imageGenerationMode: "html",
        difficulty: "",
        reportingScale: "",
        subjectFilter: "",
        passage: "",
        textWordLimit: null,
        textInstruction: "",
        options: [],
        topic: "",
        coreQuestion: null,
        subContext: "",
        scienceCompetency: [],
        learningPerformance: [],
        learningContent: [],
        subQuestionCount: 2,
        subquestionConfigs: [
          // Old draft: no figure_kind field at all
          { question_type: "社會選擇題" },
          {},
        ],
        modelPlan: "",
        modelExecute: "",
        modelVerify: "",
        modelCorrect: "",
        effortPlan: "",
        effortExecute: "",
        effortVerify: "",
        effortCorrect: "",
        // No allowDuplicateFigureKinds field
      },
    };
    window.localStorage.setItem(`exam_form_draft_${userId}`, JSON.stringify(oldDraft));

    const restored = loadDraft(userId);
    expect(restored).not.toBeNull();
    // Should normalize to false
    expect(restored!.fields.allowDuplicateFigureKinds).toBe(false);
    // Subquestion configs should still load
    expect(restored!.fields.subquestionConfigs[0]).toMatchObject({ question_type: "社會選擇題" });
  });

  // ---------------------------------------------------------------------------
  // Slice (g): history prefill round-trip
  // ---------------------------------------------------------------------------

  it("(g) history prefill with figure_kind populates the 圖像種類 input", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          sub_question_count: 1,
          subquestion_configs: JSON.stringify([{ figure_kind: "地圖" }]),
        }}
      />,
    );

    await screen.findByText("第1小題");
    const input = subquestionRow(1).getByPlaceholderText("例如：直方圖");
    expect((input as HTMLInputElement).value).toBe("地圖");
  });

  // ---------------------------------------------------------------------------
  // Slice (h): math shows neither control
  // ---------------------------------------------------------------------------

  it("(h) math subject shows no 圖像種類 control and no 允許圖像種類重複 toggle", async () => {
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    render(
      <ParamForm
        subject="math"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{}}
      />,
    );

    await screen.findByText("form.btn_generate");
    // Math has no sub_question_count by default but let's verify no figure controls
    expect(screen.queryByText("圖像種類", { selector: "label" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "允許圖像種類重複" })).not.toBeInTheDocument();
  });
});
