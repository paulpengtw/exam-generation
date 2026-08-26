import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
  resolveGenerate: resolveGenerateMock,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => ({
    "form.btn_generate": "產生",
    "form.btn_confirm_send": "確定發送",
    "form.confirm_title": "發送前確認設定",
    "form.confirm_question_block": "第{n}題",
    "form.confirm_content_domain": "內容領域",
    "form.confirm_reporting_scale": "Reporting Scale",
    "form.confirm_reporting_scale_per_subquestion": "各小題分別抽取",
    "form.confirm_core_competency": "核心素養",
    "form.confirm_math_thinking": "數學思考",
    "form.reporting_scale": "Reporting Scale",
    "form.confirm_random": "（隨機）",
    "form.confirm_subq_reporting_scale": "Reporting Scale:",
    "form.confirm_badge_random": "隨機",
    "form.confirm_badge_user": "使用者選擇",
    "form.confirm_edit": "編輯",
    "form.confirm_redraw": "重抽",
    "form.confirm_subquestion_heading": "各小題配置",
    "form.confirm_subquestion_row_title": "第 {n} 小題",
    "form.confirm_subq_cognitive_process": "認知歷程:",
    "form.confirm_subq_q_type_input": "題型",
    "form.confirm_subq_instruction_input": "出題指示",
    "form.confirm_subq_content_type_input": "題目內容類型",
    "form.confirm_subq_image_mode_input": "圖片生成模式",
    "form.confirm_subq_q_word_limit_input": "小題字數限制",
    "form.confirm_subq_o_word_limit_input": "選項字數限制",
    "form.confirm_subq_text_word_limit_input": "文本字數限制",
    "form.confirm_subq_lc_label": "學習內容",
    "form.confirm_subq_lp_label": "學習表現",
    "form.confirm_subq_lc_picker_placeholder": "選擇學習內容",
    "form.confirm_subq_lp_picker_placeholder": "選擇學習表現",
    "form.confirm_badge_inherit": "沿用文本設定",
    "form.confirm_badge_unlimited": "不限",
    "form.confirm_unlimited": "不限",
    "form.confirm_inherit_text": "沿用文本設定",
    "form.confirm_not_filled": "未填寫",
    "form.confirm_subq_q_type": "題型:",
    "form.confirm_subq_instruction": "出題指示:",
    "form.confirm_subq_content_type": "題目內容類型:",
    "form.confirm_subq_image_mode": "圖片生成模式:",
    "form.confirm_subq_q_word_limit": "小題字數限制:",
    "form.confirm_subq_o_word_limit": "選項字數限制:",
    "form.confirm_subq_text_word_limit": "文本字數限制:",
    "form.confirm_learning_content": "學習內容",
    "form.confirm_learning_performance": "學習表現",
    "form.confirm_lc_selected": "學習內容",
    "form.confirm_lp_selected": "學習表現",
    "form.confirm_lc_random_pool": "學習內容（隨機抽取）",
    "form.confirm_lp_random_pool": "學習表現（隨機抽取）",
  }[key] ?? key),
}));

import ParamForm from "./ParamForm";

const PROCESS_VALUES = [
  "Knowing–Defining and Describing",
  "Knowing–Illustrating with examples",
  "Reasoning and Applying–Interpret information",
];
const DOMAIN = "Civic Principles";
const REPORTING_SCALE_VALUES = ["1b", "4"];
const CORE_COMPETENCY_VALUES = ["社-J-A2", "社-J-B1"];
const MATH_CORE_COMPETENCY_VALUES = ["數-J-A1", "數-J-B2"];
const MATH_THINKING_VALUE = "運用";

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  認知歷程: PROCESS_VALUES.map((value) => ({ value, instruction: "" })),
  內容領域: [{ value: DOMAIN, instruction: "" }],
  數學思考: [],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "公民與社會", instruction: "" }],
  學習表現: [],
  學習內容: [],
  digital_only_question_types: [],
};

const NATURAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  數學思考: [],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [],
  學習表現: [],
  學習內容: [],
};

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: MATH_THINKING_VALUE, instruction: "" }],
  question_style: [{ value: "standard", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

describe("ParamForm generic drawn-value confirmation rows", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "", verify: "", correct: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  it("shows every resolver-drawn social domain and cognitive value with a badge", async () => {
    const onSubmit = vi.fn();
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({
      payload: {
        ...payload,
        per_question_params: JSON.stringify([{
          content_domain: DOMAIN,
          subject_filter: ["公民與社會"],
          sub_question_count: 3,
          subquestion_configs: PROCESS_VALUES.map((cognitive_process) => ({
            question_type: "選擇題",
            cognitive_process,
          })),
        }]),
      },
      drawn: [
        "per_question_params[0].內容領域",
        ...PROCESS_VALUES.map((_, index) =>
          `per_question_params[0].subquestion_configs[${index}].認知歷程`,
        ),
      ],
    }));

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          subject_filter: "公民與社會",
          count: 1,
          sub_question_count: 3,
          subquestion_configs: [{}, {}, {}],
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalled());
    const question = within(await screen.findByRole("region", { name: "第1題" }));
    expect(screen.queryByText("（隨機）")).not.toBeInTheDocument();

    expect(question.getByText("內容領域: Civic Principles")).toBeInTheDocument();
    for (const cognitiveProcess of [
      "Knowing–Defining and Describing",
      "Knowing–Illustrating with examples",
      "Reasoning and Applying–Interpret information",
    ]) {
      const value = question.getByText(`認知歷程: ${cognitiveProcess}`);
      expect(value).toBeInTheDocument();
      const row = value.closest("[data-drawn-value-path]");
      expect(row).not.toBeNull();
      expect(within(row as HTMLElement).getByText("隨機")).toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it("limits a confirmation 小題學習內容 picker to three codes", async () => {
    const learningContent = ["LC-1", "LC-2", "LC-3", "LC-4"].map((value) => ({
      value,
      instruction: "",
      admitted_by: { 科目: ["公民與社會"] },
    }));
    getSchemasMock.mockResolvedValue({ ...SOCIAL_SCHEMA, 學習內容: learningContent });
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "social_studies",
        grade: 8,
        count: 1,
        per_question_params: JSON.stringify([{
          subject_filter: ["公民與社會"],
          content_domain: DOMAIN,
          sub_question_count: 3,
          subquestion_configs: [{ learning_content: ["LC-1"] }, {}, {}],
        }]),
      },
      drawn: ["per_question_params[0].subquestion_configs[0].learning_content"],
    });

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ subject_filter: "公民與社會", count: 1, sub_question_count: 3 }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    const card = within(await screen.findByRole("region", { name: "第1題" })).getAllByRole("listitem")[0];
    const picker = within(card).getByLabelText("學習內容");
    for (const value of ["LC-2", "LC-3"]) {
      fireEvent.change(picker, { target: { value } });
      fireEvent.mouseDown(within(card).getByRole("button", { name: new RegExp(value) }));
    }
    fireEvent.change(picker, { target: { value: "LC-4" } });

    expect(within(card).getAllByText(/LC-[1-4]/)).toHaveLength(3);
    expect(within(card).getByText("LC-1")).toBeInTheDocument();
    expect(within(card).getByText("LC-2")).toBeInTheDocument();
    expect(within(card).getByText("LC-3")).toBeInTheDocument();
    expect(within(card).queryByText("LC-4")).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "LC-4" })).not.toBeInTheDocument();
  });

  it("edits a canonical Chinese cognitive-process key without retaining the old alias", async () => {
    const onSubmit = vi.fn();
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "social_studies",
        grade: 8,
        count: 1,
        per_question_params: JSON.stringify([{
          subject_filter: ["公民與社會"],
          content_domain: DOMAIN,
          sub_question_count: 3,
          subquestion_configs: [{ "認知歷程": PROCESS_VALUES[0] }, {}, {}],
        }]),
      },
      drawn: ["per_question_params[0].subquestion_configs[0].認知歷程"],
    });

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ subject_filter: "公民與社會", count: 1, sub_question_count: 3 }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    const card = within(await screen.findByRole("region", { name: "第1題" })).getAllByRole("listitem")[0];
    const cognitiveRow = within(card).getByText(`認知歷程: ${PROCESS_VALUES[0]}`).closest("[data-drawn-value-path]") as HTMLElement;
    fireEvent.click(within(cognitiveRow).getByRole("button", { name: "編輯" }));
    fireEvent.change(within(cognitiveRow).getByLabelText("認知歷程:"), {
      target: { value: PROCESS_VALUES[1] },
    });

    expect(within(cognitiveRow).getByText("使用者選擇")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const submittedRows = JSON.parse(onSubmit.mock.calls[0][0].per_question_params) as Array<{
      subquestion_configs: string;
    }>;
    expect(JSON.parse(submittedRows[0].subquestion_configs)[0]).toEqual({
      cognitive_process: PROCESS_VALUES[1],
    });
  });

  it("keeps the random badge for top-level canonical draw paths", async () => {
    resolveGenerateMock.mockResolvedValue({
      payload: {
        content_domain: "Constitutional Rights",
        core_competency: ["社-J-C1"],
        per_question_params: JSON.stringify([{
          sub_question_count: 3,
          subquestion_configs: [{}, {}, {}],
        }]),
      },
      drawn: ["內容領域", "核心素養"],
    });

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={() => {}}
        disabled={false}
        initialParams={{
          subject_filter: "公民與社會",
          count: 1,
          sub_question_count: 3,
          subquestion_configs: [{}, {}, {}],
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalled());
    const question = within(await screen.findByRole("region", { name: "第1題" }));
    const domain = question.getByText("內容領域: Constitutional Rights");
    const domainRow = domain.closest("[data-drawn-value-path]");
    expect(domainRow).not.toBeNull();
    expect(within(domainRow as HTMLElement).getByText("隨機")).toBeInTheDocument();
    const competency = question.getByText("核心素養", { selector: "dt" }).parentElement!;
    expect(competency).toHaveTextContent("社-J-C1");
    expect(within(competency).getByText("隨機")).toBeInTheDocument();
  });

  it("shows each resolved natural-science Reporting Scale slot without a random value", async () => {
    getSchemasMock.mockResolvedValue(NATURAL_SCHEMA);
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({
      payload: {
        ...payload,
        per_question_params: JSON.stringify([{
          sub_question_count: REPORTING_SCALE_VALUES.length,
          subquestion_configs: REPORTING_SCALE_VALUES.map((reporting_scale) => ({ reporting_scale })),
        }]),
      },
      drawn: REPORTING_SCALE_VALUES.map((_, index) =>
        `per_question_params[0].subquestion_configs[${index}].reporting_scale`,
      ),
    }));

    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={() => {}}
        disabled={false}
        initialParams={{
          grade: 7,
          context: ["個人"],
          sub_context: "健康",
          set_type: "題組題",
          q_type: ["選擇題"],
          content_type: "純文字",
          sub_question_count: REPORTING_SCALE_VALUES.length,
          subquestion_configs: [{}, {}],
        }}
      />,
    );

    await screen.findAllByLabelText("Reporting Scale");
    fireEvent.submit((await screen.findByRole("button", { name: "產生" })).closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalled());
    const question = within(await screen.findByRole("region", { name: "第1題" }));
    const groupRow = screen.getByText("Reporting Scale", { selector: "dt" }).parentElement;
    expect(screen.queryByText("（隨機）")).not.toBeInTheDocument();
    expect(groupRow).toHaveAttribute("data-drawn-value-path", "reporting_scale");
    expect(groupRow).toHaveTextContent("各小題分別抽取");

    const slotFields = question.getAllByLabelText("Reporting Scale");
    expect(slotFields).toHaveLength(2);
    for (const [index, reportingScale] of ["1b", "4"].entries()) {
      expect(slotFields[index]).toHaveValue(reportingScale);
      const row = slotFields[index].closest("[data-drawn-value-path]");
      expect(row).not.toBeNull();
      expect(row).toHaveAttribute(
        "data-drawn-value-path",
        `per_question_params[0].subquestion_configs[${index}].reporting_scale`,
      );
      expect(within(row as HTMLElement).getByText("隨機")).toBeInTheDocument();
    }
  });

  it("shows resolver-drawn competency and math-thinking values on the math confirmation", async () => {
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({
      payload: {
        ...payload,
        per_question_params: JSON.stringify([{
          core_competency: MATH_CORE_COMPETENCY_VALUES,
          math_thinking: [MATH_THINKING_VALUE],
        }]),
      },
      drawn: [
        "per_question_params[0].核心素養",
        "per_question_params[0].數學思考",
      ],
    }));

    render(
      <ParamForm
        subject="math"
        onSubmit={() => {}}
        disabled={false}
        initialParams={{
          grade: 7,
          context: ["個人"],
          set_type: "單一題",
          q_type: ["選擇題"],
          content_type: "純文字",
        }}
      />,
    );

    fireEvent.submit((await screen.findByRole("button", { name: "產生" })).closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalled());

    const competencyRow = screen.getByText("核心素養", { selector: "dt" }).parentElement!;
    expect(screen.queryByText("（隨機）")).not.toBeInTheDocument();
    expect(competencyRow).toHaveTextContent("數-J-A1、數-J-B2");
    expect(within(competencyRow).getByText("隨機")).toBeInTheDocument();
    const thinkingRow = screen.getByText("數學思考", { selector: "dt" }).parentElement!;
    expect(thinkingRow).toHaveTextContent("運用");
    expect(within(thinkingRow).getByText("隨機")).toBeInTheDocument();
  });

  it("shows a resolver-drawn social competency value on the social confirmation", async () => {
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({
      payload: {
        ...payload,
        per_question_params: JSON.stringify([{
          core_competency: CORE_COMPETENCY_VALUES,
        }]),
      },
      drawn: ["per_question_params[0].核心素養"],
    }));

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={() => {}}
        disabled={false}
        initialParams={{
          grade: 7,
          subject_filter: "公民與社會",
          set_type: "題組題",
          content_type: "純文字",
        }}
      />,
    );

    fireEvent.submit((await screen.findByRole("button", { name: "產生" })).closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalled());

    const competencyRow = screen.getByText("核心素養", { selector: "dt" }).parentElement!;
    expect(screen.queryByText("（隨機）")).not.toBeInTheDocument();
    expect(competencyRow).toHaveTextContent("社-J-A2、社-J-B1");
    expect(within(competencyRow).getByText("隨機")).toBeInTheDocument();
  });

  it("edits a drawn competency in place, re-resolves, and pins the new value", async () => {
    getSchemasMock.mockResolvedValue({
      ...MATH_SCHEMA,
      核心素養: [
        { value: "數-J-A1", instruction: "" },
        { value: "數-J-B2", instruction: "" },
      ],
    });
    resolveGenerateMock
      .mockResolvedValueOnce({
        payload: {
          subject: "math",
          grade: 7,
          count: 1,
          per_question_params: JSON.stringify([{ core_competency: ["數-J-A1"] }]),
        },
        drawn: ["per_question_params[0].核心素養"],
        cleared: [],
      })
      .mockResolvedValueOnce({
        payload: {
          subject: "math",
          grade: 7,
          count: 1,
          per_question_params: JSON.stringify([{ core_competency: ["數-J-B2"] }]),
        },
        drawn: [],
        cleared: [],
      });

    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ count: 1 }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByRole("region", { name: "第1題" });

    const row = within(screen.getByRole("region", { name: "第1題" }))
      .getByText("核心素養", { selector: "dt" })
      .parentElement!;
    fireEvent.click(within(row).getByRole("button", { name: "編輯" }));
    const editor = within(row).getByRole("listbox", { name: "核心素養" });
    fireEvent.change(editor, { target: { value: ["數-J-B2"] } });

    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(2));
    const resubmitted = resolveGenerateMock.mock.calls[1][0] as Record<string, unknown>;
    expect(JSON.parse(resubmitted.per_question_params as string)[0].core_competency)
      .toEqual(["數-J-B2"]);
    await waitFor(() => expect(within(row).getByText("數-J-B2")).toBeInTheDocument());
    expect(within(row).getByText("使用者選擇")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    expect(onSubmit.mock.calls[0][0].per_question_params).toContain("數-J-B2");
  });
});
