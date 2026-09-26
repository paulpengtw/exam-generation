import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const SOCIAL_SCHEMA = {
  grades: [7, 8, 9],
  情境: [{ value: "個人" }, { value: "公共" }],
  情境子類別: [],
  題型種類: [{ value: "題組題" }],
  題型: [
    { value: "選擇題" },
    { value: "開放式建構反應題" },
  ],
  題目內容類型: [{ value: "純文字" }],
  科目: [{ value: "歷史" }, { value: "地理" }],
  學習表現: [
    { value: "歷1a-IV-1", instruction: "理解歷史時序", 科目: "歷", admitted_by: { 科目: ["歷史", "跨科"] } },
  ],
  學習內容: [
    { value: "歷Ka-Ⅳ-1", instruction: "古代文明", 科目: "歷", admitted_by: { 科目: ["歷史", "跨科"] } },
    { value: "歷Ka-Ⅳ-2", instruction: "近代變遷", 科目: "歷", admitted_by: { 科目: ["歷史", "跨科"] } },
  ],
  question_style: [],
};

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [
    { value: "n-IV-1", instruction: "理解數與量", 科目: "n", admitted_by: { 科目: ["數與量", "跨領域"] } },
  ],
  學習內容: [
    { value: "N-7-1", instruction: "負數與數線", 科目: "N", admitted_by: { 科目: ["數與量", "跨領域"] } },
    { value: "N-7-2", instruction: "指數律", 科目: "N", admitted_by: { 科目: ["數與量", "跨領域"] } },
  ],
};

vi.mock("../api/client", () => ({
  getSchemas: vi.fn(async (subject: string) =>
    subject === "math" ? MATH_SCHEMA : SOCIAL_SCHEMA),
  getAvailableModels: vi.fn(async () => ({
    allowed: [],
    defaults: { plan: "", execute: "" },
  })),
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => ({ payload, drawn: [] })),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => ({
    "form.confirm_subq_instruction_placeholder": "例如：請聚焦在資料判讀與因果推論",
    "form.toggle_checkbox_mode": "切換勾選模式",
    "form.toggle_search_mode": "切換搜尋模式",
    "form.add_option": "+ 新增選項",
  }[key] ?? key),
}));

import ParamForm from "./ParamForm";

async function renderSocial(onUnsubmittedInput = vi.fn(), initialParams = {}) {
  render(
    <ParamForm
      subject="social_studies"
      onSubmit={() => {}}
      disabled={false}
      initialParams={initialParams}
      onUnsubmittedInput={onUnsubmittedInput}
    />,
  );
  await waitFor(() =>
    expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
  );
  return onUnsubmittedInput;
}

async function renderMath(onUnsubmittedInput = vi.fn()) {
  render(
    <ParamForm
      subject="math"
      onSubmit={() => {}}
      disabled={false}
      onUnsubmittedInput={onUnsubmittedInput}
    />,
  );
  await screen.findByText("form.btn_generate");
  return onUnsubmittedInput;
}

function getLearningContentSection(): HTMLElement {
  const label = screen.getByText("form.learning_content", { selector: "label" });
  return label.parentElement!.parentElement!;
}

describe("ParamForm 未送出的輸入", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("does not raise 未送出的輸入 on an untouched form", async () => {
    const onUnsubmittedInput = await renderSocial();

    expect(onUnsubmittedInput).not.toHaveBeenCalled();
  });

  it("raises 未送出的輸入 when a text input changes", async () => {
    const onUnsubmittedInput = await renderSocial();

    fireEvent.change(screen.getByPlaceholderText("form.topic_placeholder"), {
      target: { value: "臺灣史" },
    });

    expect(onUnsubmittedInput).toHaveBeenCalled();
  });

  it("raises 未送出的輸入 when a select changes", async () => {
    const onUnsubmittedInput = await renderSocial();

    fireEvent.change(screen.getByLabelText("form.difficulty"), {
      target: { value: "hard" },
    });

    expect(onUnsubmittedInput).toHaveBeenCalled();
  });

  it("raises 未送出的輸入 when the count number input changes", async () => {
    const onUnsubmittedInput = await renderSocial();
    const countInput = screen.getByLabelText("form.count");

    fireEvent.change(countInput, { target: { value: "2" } });

    expect(onUnsubmittedInput).toHaveBeenCalled();
  });

  it("raises 未送出的輸入 when a checkbox is toggled", async () => {
    const onUnsubmittedInput = await renderSocial();

    fireEvent.click(screen.getByRole("checkbox", { name: "form.skip_verify" }));

    expect(onUnsubmittedInput).toHaveBeenCalled();
  });

  it("raises 未送出的輸入 when the core-question callback checkbox is toggled", async () => {
    const onUnsubmittedInput = await renderSocial();

    fireEvent.click(
      screen.getByRole("checkbox", { name: "form.core_question_callback" }),
    );

    expect(onUnsubmittedInput).toHaveBeenCalled();
  });

  it("raises 未送出的輸入 when a per-subquestion field changes", async () => {
    const onUnsubmittedInput = await renderSocial();

    fireEvent.change(screen.getByPlaceholderText("自動 3-7"), {
      target: { value: "3" },
    });
    await screen.findByText("第1小題");
    onUnsubmittedInput.mockClear();

    fireEvent.change(
      screen.getAllByPlaceholderText("例如：請聚焦在資料判讀與因果推論")[0],
      { target: { value: "比較兩項史料" } },
    );

    expect(onUnsubmittedInput).toHaveBeenCalled();
  });

  it("raises 未送出的輸入 when a 選項 is added and when one is removed", async () => {
    const onUnsubmittedInput = await renderMath();

    fireEvent.click(screen.getByRole("button", { name: "+ 新增選項" }));
    expect(onUnsubmittedInput).toHaveBeenCalled();

    onUnsubmittedInput.mockClear();
    const removeButtons = screen.getAllByRole("button", { name: "−" });
    fireEvent.click(removeButtons[removeButtons.length - 1]);
    expect(onUnsubmittedInput).toHaveBeenCalled();
  });

  it("raises 未送出的輸入 when curriculum search mode is toggled", async () => {
    const onUnsubmittedInput = await renderSocial();
    const learningContent = within(getLearningContentSection());

    // Default is now search mode; toggle to checkbox mode
    fireEvent.click(
      learningContent.getByRole("button", { name: "切換勾選模式" }),
    );

    expect(onUnsubmittedInput).toHaveBeenCalled();
  });

  it("raises 未送出的輸入 when a selected code chip is removed", async () => {
    const onUnsubmittedInput = await renderSocial();
    const learningContent = within(getLearningContentSection());
    // Default is now search mode — no toggle needed before interacting with SearchPicker
    fireEvent.change(
      learningContent.getByPlaceholderText("搜尋學習內容..."),
      { target: { value: "歷Ka-Ⅳ-1" } },
    );
    fireEvent.mouseDown(learningContent.getByRole("button", { name: /歷Ka-Ⅳ-1/ }));
    onUnsubmittedInput.mockClear();

    const chip = learningContent.getByText("歷Ka-Ⅳ-1").parentElement!;
    fireEvent.click(within(chip).getByRole("button", { name: "×" }));

    expect(onUnsubmittedInput).toHaveBeenCalled();
  });

  it("does not raise 未送出的輸入 for params prefilled by a Regenerate", async () => {
    const onUnsubmittedInput = await renderSocial(vi.fn(), {
      grade: 8,
      topic: "工業革命",
      context: ["個人"],
      set_type: "題組題",
      q_type: ["選擇題"],
      count: 2,
      skip_verify: true,
      image_generation_mode: "gpt_image",
      learning_content: ["歷Ka-Ⅳ-1"],
      sub_question_count: 3,
      subquestion_configs: [{ instruction: "比較史料" }, {}, {}],
    });

    await waitFor(() =>
      expect(screen.getByDisplayValue("工業革命")).toBeInTheDocument(),
    );
    await screen.findByText("第1小題");

    expect(onUnsubmittedInput).not.toHaveBeenCalled();
  });

  it("does not raise 未送出的輸入 for a 預抽 draw", async () => {
    const onUnsubmittedInput = await renderSocial();

    fireEvent.click(screen.getByText("form.btn_generate"));
    await screen.findByText("form.confirm_title");

    expect(onUnsubmittedInput).not.toHaveBeenCalled();
  });
});
