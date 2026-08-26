import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());

const MATH_LEARNING_CONTENT = [
  { value: "N-7-1", instruction: "負數與數線", 科目: "N", admitted_by: { 科目: ["數與量", "跨領域"] } },
  { value: "n-IV-2", instruction: "數與量關係", 科目: "n", admitted_by: { 科目: ["數與量", "跨領域"] } },
  { value: "A-7-3", instruction: "代數式", 科目: "A", admitted_by: { 科目: ["代數", "跨領域"] } },
  { value: "S-8-1", instruction: "幾何與空間", 科目: "S", admitted_by: { 科目: ["幾何", "跨領域"] } },
  { value: "D-9-1", instruction: "資料分析", 科目: "D", admitted_by: { 科目: ["統計與機率", "跨領域"] } },
];

function mathSchema(learningContent = MATH_LEARNING_CONTENT) {
  return {
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
      { value: "統計與機率", instruction: "" },
      { value: "跨領域", instruction: "" },
    ],
    學習表現: [
      { value: "n-IV-1", instruction: "理解數與量", 科目: "n", admitted_by: { 科目: ["數與量", "跨領域"] } },
      { value: "a-IV-1", instruction: "理解代數", 科目: "a", admitted_by: { 科目: ["代數", "跨領域"] } },
    ],
    學習內容: learningContent,
  };
}

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: vi.fn(async () => ({
    allowed: [],
    defaults: { plan: "", execute: "" },
  })),
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: resolveGenerateMock,
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

import ParamForm, { type GenerateParams } from "./ParamForm";

function getLearningContentSection(): HTMLElement {
  const label = screen.getByText("form.learning_content", { selector: "label" });
  return label.parentElement!.parentElement!;
}

function getSubjectFilterSelect(): HTMLSelectElement {
  const label = screen.getByText("form.subject_filter", { selector: "label" });
  const select = label.parentElement!.querySelector("select");
  expect(select).not.toBeNull();
  return select as HTMLSelectElement;
}

describe("ParamForm math learning-content selector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockImplementation(async () => mathSchema());
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({ payload, drawn: [] }));
  });

  it("shows the 學習內容 selector on the 數學 form when the pool is non-empty", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    expect(await screen.findByText("form.learning_content", { selector: "label" }))
      .toBeInTheDocument();
    // Default is search mode — verify the SearchPicker appears in the section
    expect(within(getLearningContentSection()).getByPlaceholderText("搜尋學習內容...")).toBeInTheDocument();
  });

  it("hides the 學習內容 selector when the pool is empty", async () => {
    getSchemasMock.mockImplementation(async () => mathSchema([]));
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    await screen.findByText("form.btn_generate");
    expect(screen.queryByText("form.learning_content", { selector: "label" }))
      .not.toBeInTheDocument();
  });

  it("narrows the visible 學習內容 pool by subject_filter strand prefix", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    // Switch to checkbox mode (default is search mode)
    await screen.findByText("form.learning_content", { selector: "label" });
    fireEvent.click(within(getLearningContentSection()).getByRole("button", { name: "切換勾選模式" }));
    await screen.findByText("N-7-1");

    fireEvent.change(getSubjectFilterSelect(), { target: { value: "幾何" } });
    await waitFor(() => {
      const section = within(getLearningContentSection());
      expect(section.getByText("S-8-1")).toBeInTheDocument();
      expect(section.queryByText("N-7-1")).not.toBeInTheDocument();
      expect(section.queryByText("D-9-1")).not.toBeInTheDocument();
    });

    fireEvent.change(getSubjectFilterSelect(), { target: { value: "數與量" } });
    await waitFor(() => {
      const section = within(getLearningContentSection());
      expect(section.getByText("N-7-1")).toBeInTheDocument();
      expect(section.getByText("n-IV-2")).toBeInTheDocument();
      expect(section.queryByText("S-8-1")).not.toBeInTheDocument();
      expect(section.queryByText("D-9-1")).not.toBeInTheDocument();
    });
  });

  it("sends an explicit 數學 學習內容 selection verbatim and suppresses the 預抽", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="math" onSubmit={(params) => submitted.push(params)} disabled={false} />,
    );

    // Switch to checkbox mode (default is search mode)
    await screen.findByText("form.learning_content", { selector: "label" });
    fireEvent.click(within(getLearningContentSection()).getByRole("button", { name: "切換勾選模式" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^A-7-3/ }));
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].learning_content).toEqual(["A-7-3"]);
  });

  it("labels an explicit 數學 學習內容 selection as user-selected", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    // Switch to checkbox mode (default is search mode)
    await screen.findByText("form.learning_content", { selector: "label" });
    fireEvent.click(within(getLearningContentSection()).getByRole("button", { name: "切換勾選模式" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^S-8-1/ }));
    fireEvent.click(screen.getByText("form.btn_generate"));
    await screen.findByText("form.confirm_title");

    const label = screen.getByText("form.confirm_learning_content", { selector: "dt" });
    const learningContentRow = within(label.parentElement!);
    expect(learningContentRow.getByText("form.confirm_lc_selected")).toBeInTheDocument();
    expect(learningContentRow.queryByText("form.confirm_lc_random_pool")).not.toBeInTheDocument();
  });

  it("restores the 預抽 when an explicit selection is cleared", async () => {
    const submitted: GenerateParams[] = [];
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "math",
        grade: 7,
        count: 1,
        learning_content: ["N-7-1"],
        per_question_params: JSON.stringify([{ learning_content: ["N-7-1"] }]),
      },
      drawn: ["learning_content", "per_question_params[0].learning_content"],
    });
    render(
      <ParamForm subject="math" onSubmit={(params) => submitted.push(params)} disabled={false} />,
    );

    // Switch to checkbox mode (default is search mode)
    await screen.findByText("form.learning_content", { selector: "label" });
    fireEvent.click(within(getLearningContentSection()).getByRole("button", { name: "切換勾選模式" }));
    const checkbox = screen.getByRole("checkbox", { name: /^A-7-3/ });
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
    fireEvent.click(checkbox);
    expect(checkbox).not.toBeChecked();
    fireEvent.click(screen.getByText("form.btn_generate"));

    const label = await screen.findByText("form.confirm_learning_content", { selector: "dt" });
    const learningContentRow = within(label.parentElement!);
    expect(learningContentRow.getByText("form.confirm_lc_random_pool")).toBeInTheDocument();
    expect(learningContentRow.queryByText("form.confirm_lc_selected")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("form.btn_confirm_send"));
    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].learning_content).toEqual(["N-7-1"]);
  });

  it("supports both checkbox and search modes on the 數學 form", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    await screen.findByText("form.learning_content", { selector: "label" });

    const section = within(getLearningContentSection());
    // Default is now search mode
    expect(section.getByPlaceholderText("搜尋學習內容...")).toBeInTheDocument();
    const toggle = section.getByRole("button", { name: "切換勾選模式" });
    expect(toggle).toBeInTheDocument();
    fireEvent.click(toggle);

    // After toggling to checkbox mode
    expect(section.getByRole("button", { name: "切換搜尋模式" })).toBeInTheDocument();
  });
});
