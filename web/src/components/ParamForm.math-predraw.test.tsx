import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const MATH_LEARNING_CONTENT = [
  { value: "N-7-1", instruction: "負數與數線", 科目: "N" },
  { value: "A-7-2", instruction: "一元一次方程式", 科目: "A" },
  { value: "S-7-3", instruction: "幾何與空間", 科目: "S" },
];
const LEARNING_CONTENT_CODES = MATH_LEARNING_CONTENT.map((entry) => entry.value);

vi.mock("../api/client", () => ({
  getSchemas: vi.fn(async () => ({
    學習階段: "第四學習階段",
    grades: [7, 8, 9],
    情境: [{ value: "個人", instruction: "" }],
    題型種類: [{ value: "單一題", instruction: "" }],
    題型: [{ value: "選擇題", instruction: "" }],
    數學思考: [{ value: "形成", instruction: "" }],
    question_style: [{ value: "課本", instruction: "" }],
    題目內容類型: [{ value: "純文字", instruction: "" }],
    科目: [
      { value: "數與量", instruction: "" },
      { value: "代數", instruction: "" },
      { value: "幾何", instruction: "" },
    ],
    學習表現: [
      { value: "n-IV-1", instruction: "理解數與量", 科目: "n" },
      { value: "a-IV-1", instruction: "理解代數", 科目: "a" },
    ],
    學習內容: MATH_LEARNING_CONTENT,
  })),
  getAvailableModels: vi.fn(async () => ({
    allowed: [],
    defaults: { plan: "", execute: "" },
  })),
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

import ParamForm, { type GenerateParams } from "./ParamForm";

function expectLearningContentFromPool(value: unknown): asserts value is string[] {
  expect(value).toBeInstanceOf(Array);
  const codes = value as string[];
  expect(codes.length).toBeGreaterThanOrEqual(1);
  expect(codes.length).toBeLessThanOrEqual(3);
  expect(codes.every((code) => LEARNING_CONTENT_CODES.includes(code))).toBe(true);
}

describe("ParamForm math learning-content predraw", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("釘選s a 預抽'd 學習內容 for a 數學 request with nothing selected", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="math" onSubmit={(params) => submitted.push(params)} disabled={false} />,
    );

    fireEvent.click(await screen.findByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expectLearningContentFromPool(submitted[0].learning_content);
    const perQuestion = JSON.parse(submitted[0].per_question_params as string);
    expect(perQuestion).toHaveLength(1);
    expectLearningContentFromPool(perQuestion[0].learning_content);
  });

  it("shows the 數學 預抽'd 學習內容 under the randomly-drawn heading", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    fireEvent.click(await screen.findByText("form.btn_generate"));
    await screen.findByText("form.confirm_title");

    const label = screen.getByText("form.confirm_learning_content", { selector: "dt" });
    const learningContentRow = within(label.parentElement!);
    expect(learningContentRow.getByText("form.confirm_lc_random_pool")).toBeInTheDocument();
    expect(learningContentRow.queryByText("form.confirm_not_filled")).not.toBeInTheDocument();
  });

  it("draws 學習內容 independently per question for a 數學 batch", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="math" onSubmit={(params) => submitted.push(params)} disabled={false} />,
    );

    await screen.findByText("form.btn_generate");
    const countInput = screen.getByLabelText("form.count");
    fireEvent.change(countInput, { target: { value: "3" } });
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    const perQuestion = JSON.parse(submitted[0].per_question_params as string);
    expect(perQuestion).toHaveLength(3);
    for (const question of perQuestion) {
      expectLearningContentFromPool(question.learning_content);
    }
  });
});
