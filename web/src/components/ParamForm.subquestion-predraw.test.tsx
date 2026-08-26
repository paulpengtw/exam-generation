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

const HISTORY_LC = "HISTORY-MISSING-LC";
const HISTORY_LP = "HISTORY-MISSING-LP";
const MISSING_LC_PATH = "per_question_params[0].subquestion_configs[0].learning_content";
const MISSING_LP_PATH = "per_question_params[0].subquestion_configs[0].learning_performance";

const NS_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "Health", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple multiple-choice", instruction: "" }],
  科學能力: [{ value: "Ability one", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  學習表現: [{ value: HISTORY_LP, instruction: "resolver LP", 科目: "自然科學" }],
  學習內容: [{ value: HISTORY_LC, instruction: "resolver LC", 科目: "自然科學" }],
};

describe("ParamForm resolver-backed per-subquestion values", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(NS_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  it("silently resolves a field missing from an older history record and marks it random", async () => {
    const onSubmit = vi.fn();
    const history = {
      subject: "natural_sciences",
      grade: 8,
      count: 1,
      seed: 901,
      context: ["Personal"],
      sub_context: "Health",
      set_type: "題組題",
      q_type: ["Simple multiple-choice"],
      content_type: "純文字",
      per_question_params: JSON.stringify([{
        seed: 901,
        subquestion_configs: JSON.stringify([{}]),
      }]),
    };
    const resolvedPayload = {
      ...history,
      per_question_params: JSON.stringify([{
        seed: 901,
        subquestion_configs: JSON.stringify([{
          learning_content: [HISTORY_LC],
          learning_performance: [HISTORY_LP],
        }]),
      }]),
    };
    resolveGenerateMock.mockResolvedValueOnce({
      payload: resolvedPayload,
      drawn: [MISSING_LC_PATH, MISSING_LP_PATH],
    });

    render(<ParamForm subject="natural_sciences" onSubmit={onSubmit} initialParams={history} />);
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    const question = await screen.findByRole("region", { name: "第1題" });
    expect(within(question).getByText(HISTORY_LC)).toBeInTheDocument();
    expect(within(question).getByText(HISTORY_LP)).toBeInTheDocument();
    expect(within(question).getAllByText("隨機抽取").length).toBeGreaterThanOrEqual(2);

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(JSON.parse(onSubmit.mock.calls[0][0].per_question_params)[0].subquestion_configs)
      .toContain(HISTORY_LC);
    expect(onSubmit.mock.calls[0][0].drawn).toEqual([MISSING_LC_PATH, MISSING_LP_PATH]);
    expect(history.per_question_params).not.toContain(HISTORY_LC);
  });

  it("renders the resolver's completed subquestion payload instead of drawing in the browser", async () => {
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "natural_sciences",
        grade: 8,
        count: 1,
        seed: 902,
        per_question_params: JSON.stringify([{
          seed: 902,
          subquestion_configs: JSON.stringify([{
            learning_content: [HISTORY_LC],
            learning_performance: [HISTORY_LP],
          }]),
        }]),
      },
      drawn: [MISSING_LC_PATH, MISSING_LP_PATH],
    });

    render(<ParamForm subject="natural_sciences" onSubmit={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByText(HISTORY_LC);
    expect(resolveGenerateMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("form.confirm_not_filled")).not.toBeInTheDocument();
  });
});
