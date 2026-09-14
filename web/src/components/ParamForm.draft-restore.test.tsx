import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => ({ payload, drawn: [] })),
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
    { value: "n-IV-1", instruction: "理解數與量", 科目: "n", admitted_by: { 科目: ["數與量", "跨領域"] } },
  ],
  學習內容: [
    { value: "N-7-1", instruction: "負數與數線", 科目: "N", admitted_by: { 科目: ["數與量", "跨領域"] } },
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
  coreQuestionCallback: true,
  imageGenerationMode: "gpt_image",
  difficulty: "hard",
  reportingScale: "",
  subjectFilter: "數與量",
  passage: "保存的文本",
  textWordLimit: 120,
  textInstruction: "請以在地案例切入",
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
  modelVerify: "",
  modelCorrect: "",
  effortPlan: "high",
  effortExecute: "max",
  effortVerify: "",
  effortCorrect: "",
  allowDuplicateFigureKinds: false,
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
      coreQuestionCallback: true,
      imageGenerationMode: "gpt_image",
      difficulty: "",
      reportingScale: "",
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
      modelVerify: "",
      modelCorrect: "",
      effortPlan: "medium",
      effortExecute: "medium",
      effortVerify: "",
      effortCorrect: "",
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

describe("ParamForm draft restoration across learning stages", () => {
  const STAGE_BASE = {
    grades: [7, 8, 9, 10, 11, 12],
    情境: [{ value: "個人", instruction: "" }],
    情境子類別: [{ value: "健康", parent: "個人", admitted_by: { 情境: ["個人"] }, instruction: "" }],
    題型種類: [{ value: "題組題", instruction: "" }],
    題型: [{ value: "Simple multiple-choice", instruction: "" }],
    科學能力: [{ value: "證據推理", instruction: "" }],
    題目內容類型: [{ value: "純文字", instruction: "" }],
    科目: [{ value: "自然科學", instruction: "" }],
  };
  const STAGE_IV_POOL = {
    ...STAGE_BASE,
    學習階段: "第四學習階段",
    學習表現: [{ value: "tr-IV-1", instruction: "IV lp", 科目: "自然科學" }],
    學習內容: [{ value: "INc-IV-1", instruction: "IV lc", 科目: "自然科學" }],
  };
  const STAGE_V_POOL = {
    ...STAGE_BASE,
    學習階段: "第五學習階段",
    學習表現: [
      { value: "tr-Vc-1", instruction: "V lp", 科目: "自然科學" },
      { value: "tr-Vc-2", instruction: "V lp 2", 科目: "自然科學" },
    ],
    學習內容: [
      { value: "INc-Vc-1", instruction: "V lc", 科目: "自然科學" },
      { value: "INc-Vc-2", instruction: "V lc 2", 科目: "自然科學" },
    ],
  };
  const STAGE_V_DRAFT_FIELDS: FormFields = {
    grade: 11,
    style: "",
    contentType: "純文字",
    customContentType: "",
    context: ["個人"],
    setType: "題組題",
    qType: ["Simple multiple-choice"],
    count: 1,
    coverageMode: "balanced",
    skipVerify: false,
    disableReferenceFewshot: false,
    coreQuestionCallback: true,
    imageGenerationMode: "gpt_image",
    difficulty: "",
    reportingScale: "",
    subjectFilter: "",
    passage: "500 字",
    textWordLimit: null,
    textInstruction: "",
    options: ["50 字", "50 字", "50 字", "50 字"],
    topic: "",
    coreQuestion: null,
    subContext: "健康",
    scienceCompetency: ["證據推理"],
    learningPerformance: ["tr-Vc-1"],
    learningContent: ["INc-Vc-1"],
    subQuestionCount: 2,
    subquestionConfigs: [
      {
        question_type: "Simple multiple-choice",
        learning_performance: ["tr-Vc-2"],
        learning_content: ["INc-Vc-2"],
      },
      {
        question_type: "Simple multiple-choice",
        learning_performance: ["tr-Vc-1"],
        learning_content: ["INc-Vc-1"],
      },
    ],
    modelPlan: "",
    modelExecute: "",
    modelVerify: "",
    modelCorrect: "",
    effortPlan: "medium",
    effortExecute: "medium",
    effortVerify: "",
    effortCorrect: "",
    contentDomain: "",
    targetSurface: "紙本",
    allowDuplicateFigureKinds: false,
  };
  const later = <T,>(value: T, ms: number): Promise<T> =>
    new Promise((resolve) => setTimeout(() => resolve(value), ms));

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    useLangStore.setState({ lang: "zh-TW" });
    signIn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function expectRestoredCodes(
    getSchema: (subject: string, grade?: number) => Promise<typeof STAGE_IV_POOL>,
  ) {
    getSchemasMock.mockImplementation(getSchema);
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ savedAt: SAVED_AT, fields: STAGE_V_DRAFT_FIELDS }),
    );
    const { container } = render(
      <ParamForm subject="natural_sciences" onSubmit={() => {}} disabled={false} />,
    );

    await screen.findByText("找到未完成的出題表單。");
    fireEvent.click(screen.getByRole("button", { name: "還原草稿" }));
    await waitFor(() => expect(screen.getByLabelText("年級")).toHaveValue("11"));
    await waitFor(() => expect(getSchemasMock).toHaveBeenCalledWith("natural_sciences", 11));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 100)); });

    const subquestionSection = screen
      .getByRole("heading", { name: "各小題配置", level: 4 })
      .parentElement!;
    // The chip selector also matches 各小題配置; assert 全域池 selections separately.
    const selectedGlobalCodes = Array.from(container.querySelectorAll("span.bg-blue-50 > span.font-medium"))
      .filter((element) => !subquestionSection.contains(element))
      .map((element) => element.textContent);
    expect(selectedGlobalCodes).toEqual(expect.arrayContaining(["tr-Vc-1", "INc-Vc-1"]));

    const expectedRows = [
      ["tr-Vc-2", "INc-Vc-2"],
      ["tr-Vc-1", "INc-Vc-1"],
    ];
    for (const [index, [performance, content]] of expectedRows.entries()) {
      const row = within(subquestionSection)
        .getByText(`第${index + 1}小題`, { exact: true })
        .closest("div.rounded")!;
      expect(within(row).getByText(performance, { exact: true })).toBeInTheDocument();
      expect(within(row).getByText(content, { exact: true })).toBeInTheDocument();
    }

    fireEvent.change(screen.getAllByPlaceholderText("搜尋學習表現...")[0], {
      target: { value: "-" },
    });
    expect(screen.getByRole("button", { name: /^tr-Vc-2：/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^tr-IV-1：/ })).not.toBeInTheDocument();
  }

  it("restores grade 11 全域池 and 各小題配置 codes when the grade-less pool answers first", async () => {
    await expectRestoredCodes(async (_subject, grade) =>
      grade == null ? STAGE_IV_POOL : later(grade === 11 ? STAGE_V_POOL : STAGE_IV_POOL, 30),
    );
  });

  it("restores grade 11 全域池 and 各小題配置 codes when the grade-less pool is delayed", async () => {
    await expectRestoredCodes(async (_subject, grade) =>
      grade == null ? later(STAGE_IV_POOL, 30) : grade === 11 ? STAGE_V_POOL : STAGE_IV_POOL,
    );
  });

  it("keeps restored grade 11 codes when the previous pool still has pending reconciliation", async () => {
    let resolveGrade7!: (pool: typeof STAGE_IV_POOL) => void;
    const grade7Pool = new Promise<typeof STAGE_IV_POOL>((resolve) => {
      resolveGrade7 = resolve;
    });
    getSchemasMock.mockImplementation(async (_subject, grade) => {
      if (grade === 11) return STAGE_V_POOL;
      if (grade != null) return grade7Pool;
      // Show the draft prompt before the grade-specific pickers arrive.
      return { ...STAGE_IV_POOL, 學習表現: [], 學習內容: [] };
    });
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ savedAt: SAVED_AT, fields: STAGE_V_DRAFT_FIELDS }),
    );
    const { container } = render(
      <ParamForm subject="natural_sciences" onSubmit={() => {}} disabled={false} />,
    );
    await screen.findByText("找到未完成的出題表單。");
    const restoreButton = screen.getByRole("button", { name: "還原草稿" });

    // Click in the commit's mutation microtask, before the old pool's passive
    // effects run. An act-wrapped click would flush away this ordering.
    const observer = new MutationObserver(() => {
      if (!screen.queryByPlaceholderText("搜尋學習表現...")) return;
      observer.disconnect();
      restoreButton.click();
    });
    observer.observe(container, { childList: true, subtree: true });
    try {
      resolveGrade7(STAGE_IV_POOL);
      await waitFor(() => expect(screen.getByLabelText("年級")).toHaveValue("11"));
      await waitFor(() => expect(getSchemasMock).toHaveBeenCalledWith("natural_sciences", 11));
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 100)); });

      const subquestionSection = screen
        .getByRole("heading", { name: "各小題配置", level: 4 })
        .parentElement!;
      const selectedGlobalCodes = Array.from(container.querySelectorAll("span.bg-blue-50 > span.font-medium"))
        .filter((element) => !subquestionSection.contains(element))
        .map((element) => element.textContent);
      expect(selectedGlobalCodes).toEqual(expect.arrayContaining(["tr-Vc-1", "INc-Vc-1"]));

      const firstRow = within(subquestionSection)
        .getByText("第1小題", { exact: true })
        .closest("div.rounded")!;
      expect(within(firstRow).getByText("tr-Vc-2", { exact: true })).toBeInTheDocument();
      expect(within(firstRow).getByText("INc-Vc-2", { exact: true })).toBeInTheDocument();
    } finally {
      observer.disconnect();
    }
  });
});
