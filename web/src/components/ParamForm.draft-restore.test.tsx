import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import type { FormFields } from "./ParamForm";

const getSchemasMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: vi.fn(async () => ({
    allowed: ["planner-model", "execute-model"],
    defaults: { plan: "planner-model", execute: "execute-model" },
  })),
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));

import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import ParamForm from "./ParamForm";

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [
    { value: "個人", instruction: "" },
    { value: "社會", instruction: "" },
  ],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "填充題", instruction: "" },
  ],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [
    { value: "課本", instruction: "" },
    { value: "素養", instruction: "" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [
    { value: "n-IV-1", instruction: "理解數與量", 科目: "n" },
  ],
  學習內容: [
    { value: "N-7-1", instruction: "負數與數線", 科目: "N" },
  ],
};

const DRAFT_KEY = "exam_form_draft_teacher-1";
const SAVED_AT = new Date(Date.now() - 60_000).toISOString();
const SAVED_FIELDS: FormFields = {
  grade: 8,
  style: "素養",
  contentType: "customized",
  customContentType: "圖表判讀",
  context: ["社會"],
  setType: "單一題",
  qType: ["填充題"],
  count: 2,
  coverageMode: "random",
  skipVerify: true,
  disableReferenceFewshot: true,
  imageGenerationMode: "gpt_image",
  difficulty: "hard",
  subjectFilter: "數與量",
  passage: "保存的文本",
  textWordLimit: 120,
  options: ["甲", "乙", "丙", "丁"],
  topic: "保存的主題",
  coreQuestion: "保存的核心問題",
  subContext: "保存的情境子類別",
  scienceCompetency: ["保存的科學能力"],
  learningPerformance: ["n-IV-1"],
  learningContent: ["N-7-1"],
  subQuestionCount: 3,
  subquestionConfigs: [
    { question_type: "填充題", instruction: "第一小題" },
    { content_type: "純文字", question_word_limit: 60 },
    { image_generation_mode: "gpt_image", option_word_limit: 20 },
  ],
  modelPlan: "planner-model",
  modelExecute: "execute-model",
  effortPlan: "high",
  effortExecute: "max",
};

function signIn(): void {
  useAuthStore.getState().login("token", {
    id: "teacher-1",
    email: "teacher@example.com",
    created_at: "2026-01-01T00:00:00.000Z",
  });
}

function storeDraft(): void {
  localStorage.setItem(
    DRAFT_KEY,
    JSON.stringify({ savedAt: SAVED_AT, fields: SAVED_FIELDS }),
  );
}

describe("ParamForm draft restoration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    useLangStore.setState({ lang: "zh-TW" });
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    signIn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows the saved time and restores every saved field on 還原草稿", async () => {
    storeDraft();
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    expect(
      await screen.findByText("找到未完成的出題表單。"),
    ).toBeInTheDocument();
    expect(
      screen
        .getByRole("status")
        .textContent?.replace(/\s/g, " "),
    ).toContain(
      new Date(SAVED_AT).toLocaleString("zh-TW").replace(/\s/g, " "),
    );
    const topicInput = screen.getByPlaceholderText(
      "例如：氣候變遷與都市規劃",
    ) as HTMLInputElement;
    expect(topicInput.value).toBe("");

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "還原草稿" }));

    expect(topicInput.value).toBe("保存的主題");
    expect(screen.queryByText("找到未完成的出題表單。")).not.toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });

    const stored = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null") as {
      fields: FormFields;
    };
    expect(stored.fields).toEqual(SAVED_FIELDS);
  });

  it("clears the draft and leaves the form blank on 重新開始", async () => {
    storeDraft();
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    await screen.findByText("找到未完成的出題表單。");
    const topicInput = screen.getByPlaceholderText(
      "例如：氣候變遷與都市規劃",
    ) as HTMLInputElement;
    expect(topicInput.value).toBe("");

    fireEvent.click(screen.getByRole("button", { name: "重新開始" }));

    expect(screen.queryByText("找到未完成的出題表單。")).not.toBeInTheDocument();
    expect(topicInput.value).toBe("");
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
  });

  it("shows no restore prompt when there is no draft", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    await screen.findByRole("button", { name: "產生" });

    expect(screen.queryByText("找到未完成的出題表單。")).not.toBeInTheDocument();
  });

  it("lets route prefill win without offering or clearing the saved draft", async () => {
    storeDraft();
    render(
      <ParamForm
        subject="math"
        initialParams={{ topic: "紀錄帶入的主題" }}
        onSubmit={() => {}}
        disabled={false}
      />,
    );

    await waitFor(() =>
      expect(screen.getByDisplayValue("紀錄帶入的主題")).toBeInTheDocument(),
    );

    expect(screen.queryByText("找到未完成的出題表單。")).not.toBeInTheDocument();
    expect(localStorage.getItem(DRAFT_KEY)).not.toBeNull();
  });

  it("does not resave restored fields that deep-equal the defaults", async () => {
    const defaultFields: FormFields = {
      grade: 7,
      style: "課本",
      contentType: "純文字",
      customContentType: "",
      context: [],
      setType: "單一題",
      qType: [],
      count: 1,
      coverageMode: "balanced",
      skipVerify: false,
      disableReferenceFewshot: false,
      imageGenerationMode: "gpt_image",
      difficulty: "",
      subjectFilter: "",
      passage: "500 字",
      textWordLimit: null,
      options: ["50 字", "50 字", "50 字", "50 字"],
      topic: "",
      coreQuestion: null,
      subContext: "",
      scienceCompetency: [],
      learningPerformance: [],
      learningContent: [],
      subQuestionCount: "",
      subquestionConfigs: [],
      modelPlan: "",
      modelExecute: "",
      effortPlan: "medium",
      effortExecute: "medium",
    };
    const reorderedFields = Object.fromEntries(
      Object.entries(defaultFields).reverse(),
    ) as unknown as FormFields;
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ savedAt: SAVED_AT, fields: reorderedFields }),
    );
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    await screen.findByText("找到未完成的出題表單。");

    const setItemSpy = vi.spyOn(localStorage, "setItem");
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "還原草稿" }));
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });

    expect(
      setItemSpy.mock.calls.filter(([key]) => key === DRAFT_KEY),
    ).toHaveLength(0);
    expect(localStorage.getItem(DRAFT_KEY)).not.toBeNull();
  });
});
