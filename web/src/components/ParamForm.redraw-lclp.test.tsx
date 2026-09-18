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
  useLangStore: (selector: (state: { lang: string }) => unknown) => selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

const LC_A = "RESOLVER-LC-A";
const LC_B = "RESOLVER-LC-B";
const LC_C = "RESOLVER-LC-C";
const LP_A = "RESOLVER-LP-A";
const REDRAW_PATH = "per_question_params[0].subquestion_configs[0].learning_content";

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
    { value: LP_A, instruction: "resolver LP", 科目: "社", admitted_by: { 科目: ["歷史"] } },
  ],
  學習內容: [
    { value: LC_A, instruction: "resolver LC A", 科目: "歷史", admitted_by: { 科目: ["歷史"] } },
    { value: LC_B, instruction: "resolver LC B", 科目: "歷史", admitted_by: { 科目: ["歷史"] } },
    { value: LC_C, instruction: "resolver LC C", 科目: "歷史", admitted_by: { 科目: ["歷史"] } },
  ],
};

function responseFor(
  payload: Record<string, unknown>,
  learningContent: string,
): { payload: Record<string, unknown>; drawn: string[] } {
  const rows = JSON.parse(payload.per_question_params as string) as Record<string, unknown>[];
  const firstRow = rows[0] ?? {};
  const configs = JSON.parse(firstRow.subquestion_configs as string) as Record<string, unknown>[];
  const completedConfigs = configs.map((config, index) => index === 0
    ? { ...config, learning_content: [learningContent], learning_performance: [LP_A] }
    : config);
  const completedRows = rows.map((row, index) => index === 0
    ? {
        ...row,
        seed: 604,
        learning_content: ["RESOLVER-GLOBAL-LC"],
        learning_performance: ["RESOLVER-GLOBAL-LP"],
        subquestion_configs: JSON.stringify(completedConfigs),
      }
    : row);
  return {
    payload: {
      ...payload,
      seed: 604,
      sub_question_count: 3,
      learning_content: ["RESOLVER-GLOBAL-LC"],
      learning_performance: ["RESOLVER-GLOBAL-LP"],
      per_question_params: JSON.stringify(completedRows),
    },
    drawn: [REDRAW_PATH, "per_question_params[0].subquestion_configs[0].learning_performance"],
  };
}

function getFirstSubquestionCard() {
  const question = within(screen.getByRole("region", { name: "第1題" }));
  const heading = question.getByRole("heading", { name: "各小題配置", level: 4 });
  return within(within(heading.closest("section") as HTMLElement).getAllByRole("listitem")[0]);
}

function getLearningContentPicker(card: ReturnType<typeof within>) {
  return card.getByLabelText("學習內容").parentElement as HTMLElement;
}

function removeChip(picker: HTMLElement, value: string) {
  const chip = within(picker).getByText(value).closest("span.inline-flex") as HTMLElement;
  fireEvent.click(within(chip).getByRole("button", { name: "×" }));
}

describe("ParamForm resolver redraws", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SS_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  it("clears only one field, increments its redraw counter, preserves seed/sibling, and changes twice", async () => {
    const onSubmit = vi.fn();
    resolveGenerateMock
      .mockResolvedValueOnce(responseFor({ per_question_params: JSON.stringify([{ subquestion_configs: JSON.stringify([{}]) }]) }, LC_A))
      .mockResolvedValueOnce(responseFor({ per_question_params: JSON.stringify([{ subquestion_configs: JSON.stringify([{}]) }]) }, LC_B))
      .mockResolvedValueOnce(responseFor({ per_question_params: JSON.stringify([{ subquestion_configs: JSON.stringify([{}]) }]) }, LC_C));

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          core_question: "固定核心問題",
          sub_question_count: 3,
          subquestion_configs: [{}],
          learning_content: ["RESOLVER-GLOBAL-LC"],
          learning_performance: ["RESOLVER-GLOBAL-LP"],
        }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByText(LC_A);

    const card = getFirstSubquestionCard();
    const picker = getLearningContentPicker(card);
    expect(card.getByText(LC_A)).toBeInTheDocument();
    expect(card.getByText(LP_A)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "第1題" })).getByText("604")).toBeInTheDocument();

    removeChip(picker, LC_A);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(2));
    expect(resolveGenerateMock.mock.calls[1][1]).toEqual({ [REDRAW_PATH]: 1 });
    await waitFor(() => {
      expect(getFirstSubquestionCard().getByText(LC_B)).toBeInTheDocument();
      expect(getFirstSubquestionCard().getByText(LP_A)).toBeInTheDocument();
      expect(within(screen.getByRole("region", { name: "第1題" })).getByText("604")).toBeInTheDocument();
    });
    expect(JSON.parse(resolveGenerateMock.mock.calls[1][0].per_question_params)[0].subquestion_configs)
      .not.toContain(LC_A);

    removeChip(getLearningContentPicker(getFirstSubquestionCard()), LC_B);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(3));
    expect(resolveGenerateMock.mock.calls[2][1]).toEqual({ [REDRAW_PATH]: 2 });
    await waitFor(() => {
      expect(getFirstSubquestionCard().getByText(LC_C)).toBeInTheDocument();
      expect(getFirstSubquestionCard().getByText(LP_A)).toBeInTheDocument();
      expect(within(screen.getByRole("region", { name: "第1題" })).getByText("604")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const submittedRows = JSON.parse(onSubmit.mock.calls[0][0].per_question_params) as Array<{
      seed: number;
      subquestion_configs: string;
    }>;
    expect(submittedRows[0].seed).toBe(604);
    expect(JSON.parse(submittedRows[0].subquestion_configs)[0]).toEqual(expect.objectContaining({
      learning_content: [LC_C],
      learning_performance: [LP_A],
    }));
  });
});
