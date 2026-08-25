import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
}));
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

const DOMAIN = "Civic Principles";
const PROCESS = "Reasoning and Applying–Relate or Integrate";
const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  認知歷程: [{ value: PROCESS, instruction: "" }],
  內容領域: [{ value: DOMAIN, instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "公民與社會", instruction: "" }],
  學習表現: [],
  學習內容: [],
  內容領域_mapping: {},
  digital_only_question_types: [],
};

describe("#506 confirmation ICCS axes", () => {
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

  it("shows 認知歷程 per 小題 and 內容領域 on the question confirmation card", async () => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          content_domain: DOMAIN,
          sub_question_count: 3,
          subquestion_configs: [{ cognitive_process: PROCESS }, {}, {}],
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    const question = within(await screen.findByRole("region", { name: "第1題" }));

    expect(question.getByText(`認知歷程: ${PROCESS}`)).toBeInTheDocument();
    expect(question.getByText(`內容領域: ${DOMAIN}`)).toBeInTheDocument();
  });
});
