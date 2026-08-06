import { fireEvent, render, screen } from "@testing-library/react";
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

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }, { value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

const SOCIAL_SCHEMA = {
  ...MATH_SCHEMA,
  題型種類: [{ value: "題組題", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
};

const SCIENCE_SCHEMA = {
  ...SOCIAL_SCHEMA,
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
};

async function submit(subject: string, initialParams: Record<string, unknown> = {}) {
  const onSubmit = vi.fn();
  render(
    <ParamForm
      subject={subject}
      onSubmit={onSubmit}
      disabled={false}
      initialParams={initialParams}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "產生" }));
  fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));
  return onSubmit;
}

describe("數學 文本字數限制 and 小題數", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  it("shows 文本字數限制 for 數學 and submits its value", async () => {
    const onSubmit = await submit("math", { text_word_limit: 321 });

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ text_word_limit: 321 }),
    );
  });

  it("shows 小題數 for 數學 and submits its value", async () => {
    const onSubmit = await submit("math", {
      set_type: "題組題",
      sub_question_count: 4,
    });

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ sub_question_count: 4 }),
    );
  });

  it("renders both resolved rows on 數學 發送前確認", async () => {
    render(
      <ParamForm
        subject="math"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          set_type: "題組題",
          text_word_limit: 321,
          sub_question_count: 4,
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    expect(await screen.findByText("文本字數限制", { selector: "dt" })).toBeInTheDocument();
    expect(screen.getByText("小題數", { selector: "dt" })).toBeInTheDocument();
  });

  it("removes the math limit input and omits the value when 文本 is user-authored", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          passage: "使用者提供的文本",
          text_word_limit: 321,
        }}
      />,
    );

    await screen.findByRole("button", { name: "產生" });
    expect(screen.queryByLabelText("文本字數限制")).not.toBeInTheDocument();
    expect(screen.getByText("數學的文本由使用者提供，生成的文本字數限制不適用。"))
      .toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));

    expect(screen.queryByText("文本字數限制", { selector: "dt" })).not.toBeInTheDocument();
    expect(onSubmit).toHaveBeenCalledWith(
      expect.not.objectContaining({ text_word_limit: expect.anything() }),
    );
  });
});

describe("curriculum subject 文本字數限制 compatibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  it.each([
    ["social_studies", SOCIAL_SCHEMA],
    ["natural_sciences", SCIENCE_SCHEMA],
  ])("keeps the limit input for %s", async (subject, schema) => {
    getSchemasMock.mockResolvedValue(schema);

    render(<ParamForm subject={subject} onSubmit={vi.fn()} disabled={false} />);

    expect(await screen.findByLabelText("文本字數限制")).toBeInTheDocument();
  });
});
