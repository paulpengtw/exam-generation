import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => ({
    "form.btn_generate": "產生",
    "form.btn_confirm_send": "確定發送",
    "form.confirm_question_block": "第{n}題",
    "form.confirm_backend_sampled": "由後端隨機抽取（每題不同）",
    "form.confirm_content_domain": "內容領域",
    "form.confirm_badge_random": "隨機",
    "form.confirm_subquestion_heading": "各小題配置",
    "form.confirm_subquestion_row_title": "第 {n} 小題",
  }[key] ?? key),
}));

import ParamForm from "./ParamForm";

const TARGET_DOMAIN = "Civic Principles";
const OTHER_DOMAIN = "Civic Participation";
const TARGET_CODE = "公Synthetic-Ⅳ-1";
const OTHER_CODE = "公Synthetic-Ⅳ-2";

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  認知歷程: [],
  內容領域: [
    { value: TARGET_DOMAIN, instruction: "" },
    { value: OTHER_DOMAIN, instruction: "" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "公民與社會", instruction: "" }, { value: "跨科", instruction: "" }],
  學習表現: [
    {
      value: "社1a-Ⅳ-1",
      instruction: "",
      科目: "社",
      admitted_by: { 科目: ["公民與社會", "跨科"] },
    },
  ],
  學習內容: [
    {
      value: TARGET_CODE,
      instruction: "",
      科目: "公",
      admitted_by: {
        科目: ["公民與社會", "跨科"],
        內容領域: [TARGET_DOMAIN],
      },
    },
    {
      value: OTHER_CODE,
      instruction: "",
      科目: "公",
      admitted_by: {
        科目: ["公民與社會", "跨科"],
        內容領域: [OTHER_DOMAIN],
      },
    },
  ],
  digital_only_question_types: [],
};

describe("ParamForm social-studies content-domain 預抽", () => {
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

  it.each(["公民與社會", "跨科"])(
    "shows and submits a resolved domain per 題組 for %s, with each LC from its intersection",
    async (subjectFilter) => {
    const onSubmit = vi.fn();
    const random = vi.spyOn(Math, "random").mockReturnValue(0.9999);

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          subject_filter: subjectFilter,
          count: 2,
          sub_question_count: 3,
          subquestion_configs: [{}, {}, {}],
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    const firstQuestion = await screen.findByRole("region", { name: "第1題" });
    const secondQuestion = screen.getByRole("region", { name: "第2題" });

    expect(within(firstQuestion).getByText(`內容領域: ${TARGET_DOMAIN}`)).toBeInTheDocument();
    expect(within(secondQuestion).getByText(`內容領域: ${OTHER_DOMAIN}`)).toBeInTheDocument();
    expect(screen.queryAllByText("由後端隨機抽取（每題不同）")).toHaveLength(0);
    expect(within(firstQuestion).getAllByText("隨機").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const payload = onSubmit.mock.calls[0][0] as { per_question_params: string };
    const perQuestion = JSON.parse(payload.per_question_params) as Array<{
      content_domain: string;
      learning_content: string[];
    }>;
    expect(perQuestion.map((row) => row.content_domain)).toEqual([
      TARGET_DOMAIN,
      OTHER_DOMAIN,
    ]);
    expect(perQuestion[0].learning_content).toEqual([TARGET_CODE]);
    expect(perQuestion[1].learning_content).toEqual([OTHER_CODE]);

    random.mockRestore();
    },
  );

  it("forwards a pinned domain to both the shared request and each 題組", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          subject_filter: "公民與社會",
          content_domain: TARGET_DOMAIN,
          count: 2,
          sub_question_count: 3,
          subquestion_configs: [{}, {}, {}],
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    const firstQuestion = await screen.findByRole("region", { name: "第1題" });
    expect(within(firstQuestion).getByText(`內容領域: ${TARGET_DOMAIN}`)).toBeInTheDocument();
    expect(screen.queryAllByText("由後端隨機抽取（每題不同）")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const payload = onSubmit.mock.calls[0][0] as {
      content_domain: string;
      per_question_params: string;
    };
    const perQuestion = JSON.parse(payload.per_question_params) as Array<{
      content_domain: string;
    }>;
    expect(payload.content_domain).toBe(TARGET_DOMAIN);
    expect(perQuestion.map((row) => row.content_domain)).toEqual([
      TARGET_DOMAIN,
      TARGET_DOMAIN,
    ]);
  });
});
