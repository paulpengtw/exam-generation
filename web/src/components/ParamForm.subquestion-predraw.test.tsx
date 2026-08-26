import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (k: string) => {
    const M: Record<string, string> = {
      "form.confirm_subquestion_heading": "各小題配置",
      "form.confirm_subquestion_row_title": "第 {n} 小題",
      "form.confirm_subq_lp_selected": "學習表現（已選 {n} 項）",
      "form.confirm_subq_lp_random_pool": "學習表現（隨機抽取 {n} 項）",
      "form.confirm_subq_lc_selected": "學習內容（已選 {n} 項）",
      "form.confirm_subq_lc_random_pool": "學習內容（隨機抽取 {n} 項）",
      "form.confirm_subq_lp_empty": "學習表現：生成時將沿用全域抽樣池",
      "form.confirm_subq_lc_empty": "學習內容：生成時將沿用全域抽樣池",
    };
    return M[k] ?? k;
  },
}));

import ParamForm from "./ParamForm";

const NS_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple-multiple-choice", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  question_style: [{ value: "standard", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  學習表現: [
    { value: "tr-IV-1", instruction: "", 科目: "自然科學" },
    { value: "tr-IV-2", instruction: "", 科目: "自然科學" },
    { value: "tr-IV-3", instruction: "", 科目: "自然科學" },
  ],
  學習內容: [
    { value: "INc-IV-1", instruction: "", 科目: "自然科學" },
    { value: "INc-IV-2", instruction: "", 科目: "自然科學" },
    { value: "INc-IV-3", instruction: "", 科目: "自然科學" },
    { value: "INc-IV-4", instruction: "", 科目: "自然科學" },
  ],
};

const NS_BATCH_CONTEXT_SCHEMA = {
  ...NS_SCHEMA,
  情境: [
    { value: "Personal", instruction: "" },
    { value: "Global", instruction: "" },
  ],
  情境子類別: [
    {
      value: "Personal child",
      parent: "Personal",
      admitted_by: { "情境": ["Personal"] },
      instruction: "",
    },
    {
      value: "Global child",
      parent: "Global",
      admitted_by: { "情境": ["Global"] },
      instruction: "",
    },
  ],
};

const SS_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "開放式建構反應題", instruction: "" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [
    { value: "歷史", instruction: "" },
    { value: "地理", instruction: "" },
    { value: "公民與社會", instruction: "" },
    { value: "跨科", instruction: "" },
  ],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: [
    { value: "社1a-Ⅳ-1", instruction: "", 科目: "社" },
    { value: "社1a-Ⅳ-2", instruction: "", 科目: "社" },
    { value: "社1a-Ⅳ-3", instruction: "", 科目: "社" },
  ],
  學習內容: [
    { value: "歷Ka-Ⅳ-1", instruction: "", 科目: "歷史" },
    { value: "歷Ka-Ⅳ-2", instruction: "", 科目: "歷史" },
    { value: "歷Ka-Ⅳ-3", instruction: "", 科目: "歷史" },
    { value: "歷Ka-Ⅳ-4", instruction: "", 科目: "歷史" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(NS_SCHEMA);
  getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
});

describe("per-子題 pre-draw (natural_sciences)", () => {
  it("draws each 題組's 情境子類別 from that 題組's resolved 情境", async () => {
    getSchemasMock.mockResolvedValue(NS_BATCH_CONTEXT_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={onSubmit}
        initialParams={{ count: 2, core_question: "固定核心問題" }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_generate/i }));
    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_confirm_send/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const perQuestion = JSON.parse(onSubmit.mock.calls[0][0].per_question_params) as Array<{
      context: string[];
      sub_context: string;
    }>;
    const admittedByContext: Record<string, string> = {
      Personal: "Personal child",
      Global: "Global child",
    };

    expect(new Set(perQuestion.map((params) => params.context[0]))).toEqual(
      new Set(["Personal", "Global"]),
    );
    for (const params of perQuestion) {
      expect(params.sub_context).toBe(admittedByContext[params.context[0]]);
    }
  });

  it("keeps an explicitly pinned 情境 for every 題組 and only draws its admitted child", async () => {
    getSchemasMock.mockResolvedValue(NS_BATCH_CONTEXT_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={onSubmit}
        initialParams={{
          count: 2,
          context: ["Global"],
          core_question: "固定核心問題",
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_generate/i }));
    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_confirm_send/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const payload = onSubmit.mock.calls[0][0] as {
      predrawn_fields: string;
      per_question_params: string;
    };
    const perQuestion = JSON.parse(payload.per_question_params) as Array<{
      context: string[];
      sub_context: string;
    }>;
    const predrawnFields = JSON.parse(payload.predrawn_fields) as string[];

    expect(perQuestion).toHaveLength(2);
    expect(perQuestion.every((params) => params.context[0] === "Global")).toBe(true);
    expect(perQuestion.every((params) => params.sub_context === "Global child")).toBe(true);
    expect(predrawnFields).not.toContain("per_question_params[0].context");
    expect(predrawnFields).not.toContain("per_question_params[1].context");
  });

  it("keeps an explicitly pinned 情境子類別 under its admitting 情境", async () => {
    getSchemasMock.mockResolvedValue(NS_BATCH_CONTEXT_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={onSubmit}
        initialParams={{
          count: 2,
          sub_context: "Personal child",
          core_question: "固定核心問題",
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_generate/i }));
    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_confirm_send/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const payload = onSubmit.mock.calls[0][0] as {
      predrawn_fields: string;
      per_question_params: string;
    };
    const perQuestion = JSON.parse(payload.per_question_params) as Array<{
      context: string[];
      sub_context: string;
    }>;
    const predrawnFields = JSON.parse(payload.predrawn_fields) as string[];

    expect(perQuestion).toHaveLength(2);
    expect(perQuestion.every((params) => params.context[0] === "Personal")).toBe(true);
    expect(perQuestion.every((params) => params.sub_context === "Personal child")).toBe(true);
    expect(predrawnFields).not.toContain("per_question_params[0].context");
    expect(predrawnFields).not.toContain("per_question_params[1].context");
  });

  it("restores history 題組 rows with a pinned 情境子類別 under its admitting 情境", async () => {
    getSchemasMock.mockResolvedValue(NS_BATCH_CONTEXT_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={onSubmit}
        initialParams={{
          count: 2,
          core_question: "固定核心問題",
          per_question_params: JSON.stringify([
            { sub_context: "Personal child", seed: 101 },
            { sub_context: "Personal child", seed: 102 },
          ]),
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_generate/i }));
    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_confirm_send/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const perQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ context: string[]; sub_context: string }>;

    expect(perQuestion).toHaveLength(2);
    expect(perQuestion.every((params) => params.context[0] === "Personal")).toBe(true);
    expect(perQuestion.every((params) => params.sub_context === "Personal child")).toBe(true);
  });

  it("fills empty per-小題 learning_content/performance with a random subset before submit", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="natural_sciences" onSubmit={onSubmit} />);
    await screen.findByPlaceholderText("自動 3-7");
    fireEvent.change(screen.getByPlaceholderText("自動 3-7"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /form\.btn_generate/i }));

    const confirmBtn = await screen.findByRole("button", { name: /form\.btn_confirm_send/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const payload = onSubmit.mock.calls[0][0];
    expect(typeof payload.subquestion_configs).toBe("string");
    const rows = JSON.parse(payload.subquestion_configs as string);
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      expect(Array.isArray(row.learning_content)).toBe(true);
      expect(row.learning_content.length).toBeGreaterThanOrEqual(1);
      expect(row.learning_content.length).toBeLessThanOrEqual(3);
      expect(Array.isArray(row.learning_performance)).toBe(true);
      expect(row.learning_performance.length).toBeGreaterThanOrEqual(1);
      expect(row.learning_performance.length).toBeLessThanOrEqual(2);
      for (const code of row.learning_content) {
        expect(["INc-IV-1", "INc-IV-2", "INc-IV-3", "INc-IV-4"]).toContain(code);
        expect(payload.learning_content).toContain(code);
      }
      for (const code of row.learning_performance) {
        expect(["tr-IV-1", "tr-IV-2", "tr-IV-3"]).toContain(code);
        expect(payload.learning_performance).toContain(code);
      }
      expect(row).not.toHaveProperty("_lcWasAutoDrawn");
      expect(row).not.toHaveProperty("_lpWasAutoDrawn");
    }
  });

  it("records each per-小題 LC/LP pre-draw as an addressed field slot", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="natural_sciences" onSubmit={onSubmit} />);
    await screen.findByPlaceholderText("自動 3-7");
    fireEvent.change(screen.getByPlaceholderText("自動 3-7"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /form\.btn_generate/i }));
    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_confirm_send/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const payload = onSubmit.mock.calls[0][0] as { predrawn_fields: string };
    const predrawnFields = JSON.parse(payload.predrawn_fields) as string[];

    expect(predrawnFields).toEqual(expect.arrayContaining([
      "per_question_params[0].subquestion_configs[0].learning_content",
      "per_question_params[0].subquestion_configs[0].learning_performance",
      "per_question_params[0].subquestion_configs[1].learning_content",
      "per_question_params[0].subquestion_configs[1].learning_performance",
    ]));
  });

  it("renders each 子題's pre-drawn LC/LP codes in the confirmation screen", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="natural_sciences" onSubmit={onSubmit} />);
    await screen.findByPlaceholderText("自動 3-7");
    fireEvent.change(screen.getByPlaceholderText("自動 3-7"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /form\.btn_generate/i }));

    await screen.findByText("各小題配置");

    const section = screen
      .getByText("各小題配置")
      .closest("section")!;
    const html = section.innerHTML;
    const lcVisible = ["INc-IV-1", "INc-IV-2", "INc-IV-3", "INc-IV-4"].some((c) =>
      html.includes(c),
    );
    const lpVisible = ["tr-IV-1", "tr-IV-2", "tr-IV-3"].some((c) => html.includes(c));
    expect(lcVisible).toBe(true);
    expect(lpVisible).toBe(true);
  });

  it("copies typed 各小題配置 but redraws automatic LC/LP per question", async () => {
    const random = vi.spyOn(Math, "random");
    let turn = 0;
    random.mockImplementation(() => (turn++ % 2 === 0 ? 0 : 0.99));
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={onSubmit}
        initialParams={{
          count: 2,
          sub_question_count: 3,
          subquestion_configs: [
            { question_type: "Simple-multiple-choice", instruction: "固定指示", question_word_limit: 88 },
            {},
            {},
          ],
        }}
      />,
    );
    await screen.findByPlaceholderText("自動 3-7");
    fireEvent.click(screen.getByRole("button", { name: /form\.btn_generate/i }));
    fireEvent.click(await screen.findByRole("button", { name: /form\.btn_confirm_send/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const perQuestion = JSON.parse(onSubmit.mock.calls[0][0].per_question_params);
    const first = JSON.parse(perQuestion[0].subquestion_configs);
    const second = JSON.parse(perQuestion[1].subquestion_configs);
    expect(first[0]).toEqual(expect.objectContaining({
      question_type: "Simple-multiple-choice",
      instruction: "固定指示",
      question_word_limit: 88,
    }));
    expect(second[0]).toEqual(expect.objectContaining({
      question_type: "Simple-multiple-choice",
      instruction: "固定指示",
      question_word_limit: 88,
    }));
    expect(first.map((row: { learning_content: string[] }) => row.learning_content))
      .not.toEqual(second.map((row: { learning_content: string[] }) => row.learning_content));
    expect(first.map((row: { learning_performance: string[] }) => row.learning_performance))
      .not.toEqual(second.map((row: { learning_performance: string[] }) => row.learning_performance));
    random.mockRestore();
  });
});

describe("社會領域各小題預抽", () => {
  it("預抽s 學習內容 and 學習表現 from the 全域池 under 均衡", async () => {
    getSchemasMock.mockResolvedValue(SS_SCHEMA);
    const onSubmit = vi.fn();
    render(<ParamForm subject="social_studies" onSubmit={onSubmit} />);
    await screen.findByPlaceholderText("自動 3-7");
    fireEvent.change(screen.getByPlaceholderText("自動 3-7"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /form\.btn_generate/i }));

    const confirmBtn = await screen.findByRole("button", { name: /form\.btn_confirm_send/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const payload = onSubmit.mock.calls[0][0];
    expect(typeof payload.subquestion_configs).toBe("string");
    const rows = JSON.parse(payload.subquestion_configs as string);
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      expect(Array.isArray(row.learning_content)).toBe(true);
      expect(row.learning_content.length).toBeGreaterThanOrEqual(1);
      expect(row.learning_content.length).toBeLessThanOrEqual(3);
      expect(Array.isArray(row.learning_performance)).toBe(true);
      expect(row.learning_performance.length).toBeGreaterThanOrEqual(1);
      expect(row.learning_performance.length).toBeLessThanOrEqual(2);
      for (const code of row.learning_content) {
        expect(["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2", "歷Ka-Ⅳ-3", "歷Ka-Ⅳ-4"]).toContain(code);
        expect(payload.learning_content).toContain(code);
      }
      for (const code of row.learning_performance) {
        expect(["社1a-Ⅳ-1", "社1a-Ⅳ-2", "社1a-Ⅳ-3"]).toContain(code);
        expect(payload.learning_performance).toContain(code);
      }
      expect(row).not.toHaveProperty("_lcWasAutoDrawn");
      expect(row).not.toHaveProperty("_lpWasAutoDrawn");
    }
  });
});
