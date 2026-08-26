import { fireEvent, render, screen, within } from "@testing-library/react";
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
  useLangStore: (selector: (state: { lang: string }) => unknown) => selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

const LC_A = "RESOLVED-LC-A";
const LC_B = "RESOLVED-LC-B";
const LC_C = "RESOLVED-LC-C";
const LP_A = "RESOLVED-LP-A";
const LP_B = "RESOLVED-LP-B";

const SS_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: [
    { value: LP_A, instruction: "resolved LP A", 科目: "社", admitted_by: { 科目: ["歷史"] } },
    { value: LP_B, instruction: "resolved LP B", 科目: "社", admitted_by: { 科目: ["歷史"] } },
  ],
  學習內容: [
    { value: LC_A, instruction: "resolved LC A", 科目: "歷史", admitted_by: { 科目: ["歷史"] } },
    { value: LC_B, instruction: "resolved LC B", 科目: "歷史", admitted_by: { 科目: ["歷史"] } },
    { value: LC_C, instruction: "resolved LC C", 科目: "歷史", admitted_by: { 科目: ["歷史"] } },
  ],
};

const rows = [0, 1].map((questionIndex) => ({
  seed: 600 + questionIndex,
  subquestion_configs: JSON.stringify([
    { question_type: "選擇題", learning_content: [LC_A], learning_performance: [LP_A] },
    { question_type: "選擇題", learning_content: [LC_B], learning_performance: [LP_B] },
    { question_type: "選擇題", learning_content: [LC_A], learning_performance: [LP_A] },
  ]),
}));
const DRAWN = rows.flatMap((_row, questionIndex) => [
  `per_question_params[${questionIndex}].subquestion_configs[0].learning_content`,
  `per_question_params[${questionIndex}].subquestion_configs[0].learning_performance`,
  `per_question_params[${questionIndex}].subquestion_configs[1].learning_content`,
  `per_question_params[${questionIndex}].subquestion_configs[1].learning_performance`,
  `per_question_params[${questionIndex}].subquestion_configs[2].learning_content`,
  `per_question_params[${questionIndex}].subquestion_configs[2].learning_performance`,
]);

function resolvedResponse() {
  return {
    payload: {
      subject: "social_studies",
      grade: 8,
      count: 2,
      sub_question_count: 3,
      learning_content: [LC_A, LC_B],
      learning_performance: [LP_A, LP_B],
      per_question_params: JSON.stringify(rows),
    },
    drawn: DRAWN,
  };
}

function getSubquestionCard(questionIndex: number, subquestionIndex: number) {
  const question = within(screen.getByRole("region", { name: `第${questionIndex + 1}題` }));
  const heading = question.getByRole("heading", { name: "各小題配置", level: 4 });
  const section = within(heading.closest("section") as HTMLElement);
  return within(section.getAllByRole("listitem")[subquestionIndex]);
}

describe("ParamForm confirmation curriculum pickers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SS_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
    resolveGenerateMock.mockResolvedValue(resolvedResponse());
  });

  it("renders resolver-provided LC/LP pickers for every existing question and sub-question", async () => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ count: 2, sub_question_count: 3, subquestion_configs: [{}, {}, {}] }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findAllByText(LC_A);

    for (const questionIndex of [0, 1]) {
      for (const subquestionIndex of [0, 1, 2]) {
        const card = getSubquestionCard(questionIndex, subquestionIndex);
        expect(card.getByLabelText("學習內容")).toBeInTheDocument();
        expect(card.getByLabelText("學習表現")).toBeInTheDocument();
      }
    }
  });

  it("derives random badges from drawn paths and keeps sibling/other rows isolated after an explicit edit", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ count: 2, sub_question_count: 3, subquestion_configs: [{}, {}, {}] }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findAllByText(LC_A);

    const firstCard = getSubquestionCard(0, 0);
    const lcInput = firstCard.getByLabelText("學習內容");
    const lcSection = lcInput.parentElement!.parentElement!;
    const lpInput = firstCard.getByLabelText("學習表現");
    const lpSection = lpInput.parentElement!.parentElement!;
    expect(within(lcSection).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(within(lpSection).getByText("隨機抽取")).toHaveClass("text-amber-700");

    fireEvent.change(lcInput, { target: { value: "RESOLVED-LC-C" } });
    fireEvent.mouseDown((await firstCard.findByText(LC_C)).closest("button")!);

    expect(within(lcSection).queryByText("隨機抽取")).not.toBeInTheDocument();
    expect(within(lcSection).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(within(lpSection).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(getSubquestionCard(0, 1).getAllByText("隨機抽取").length).toBeGreaterThan(0);
    expect(getSubquestionCard(1, 0).getAllByText("隨機抽取").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const submittedRows = JSON.parse(onSubmit.mock.calls[0][0].per_question_params) as Array<{
      subquestion_configs: string;
    }>;
    const firstConfigs = JSON.parse(submittedRows[0].subquestion_configs) as Array<Record<string, unknown>>;
    const secondConfigs = JSON.parse(submittedRows[1].subquestion_configs) as Array<Record<string, unknown>>;
    expect(firstConfigs[0]).toEqual(expect.objectContaining({
      learning_content: [LC_A, LC_C],
      learning_performance: [LP_A],
    }));
    expect(firstConfigs[1].learning_content).toEqual([LC_B]);
    expect(secondConfigs[0].learning_content).toEqual([LC_A]);
    expect(onSubmit.mock.calls[0][0].drawn).not.toContain(
      "per_question_params[0].subquestion_configs[0].learning_content",
    );
    expect(onSubmit.mock.calls[0][0].drawn).toContain(
      "per_question_params[0].subquestion_configs[0].learning_performance",
    );
  });
});
