import { act, fireEvent, render, screen, within } from "@testing-library/react";
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
    allowed: [],
    defaults: { plan: "", execute: "" },
  })),
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => ({ payload, drawn: [] })),
}));

import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import ParamForm from "./ParamForm";

const NOW = new Date("2026-07-30T12:00:00.000Z");
const DRAFT_KEY = "exam_form_draft_teacher-choice";

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

const DRAFT_FIELDS: FormFields = {
  grade: 8,
  style: "素養",
  contentType: "純文字",
  customContentType: "",
  context: ["社會"],
  setType: "單一題",
  qType: ["填充題"],
  count: 2,
  coverageMode: "random",
  skipVerify: true,
  disableReferenceFewshot: true,
  coreQuestionCallback: true,
  imageGenerationMode: "gpt_image",
  difficulty: "medium",
  reportingScale: "",
  subjectFilter: "數與量",
  passage: "草稿保存的文本",
  textWordLimit: 120,
  textInstruction: "",
  options: ["草稿甲", "草稿乙", "草稿丙", "草稿丁"],
  topic: "草稿保存的主題",
  coreQuestion: "草稿保存的核心問題",
  subContext: "草稿情境",
  scienceCompetency: ["草稿能力"],
  learningPerformance: ["n-IV-1"],
  learningContent: ["N-7-1"],
  subQuestionCount: 3,
  subquestionConfigs: [{ question_type: "填充題", instruction: "草稿小題" }],
  modelPlan: "",
  modelExecute: "",
  modelVerify: "",
  modelCorrect: "",
  effortPlan: "medium",
  effortExecute: "medium",
  effortVerify: "",
  effortCorrect: "",
};

const DRAFT_FIELDS_WITH_SUBQUESTION_CONFIGS: FormFields = {
  ...DRAFT_FIELDS,
  subquestionConfigs: [
    { question_type: "選擇題", learning_performance: ["n-IV-1"] },
    {},
  ],
};

const DRAFT_FIELDS_WITH_UNKNOWN_CURRICULUM_CODES: FormFields = {
  ...DRAFT_FIELDS,
  learningPerformance: ["n-IV-1", "ZZ-IV-9"],
  learningContent: ["N-7-1", "ZZ-IV-9"],
};

const HISTORY_PARAMS = {
  grade: 9,
  style: "課本",
  content_type: "純文字",
  context: ["個人"],
  set_type: "單一題",
  q_type: ["選擇題"],
  count: 5,
  skip_verify: true,
  disable_reference_fewshot: true,
  image_generation_mode: "gpt_image",
  difficulty: "hard",
  subject_filter: "數與量",
  passage: "歷史紀錄帶入的文本",
  text_word_limit: 180,
  options: ["歷史甲", "歷史乙", "歷史丙", "歷史丁"],
  topic: "歷史紀錄帶入的主題",
  core_question: "歷史紀錄帶入的核心問題",
  sub_context: "歷史情境",
  science_competency: ["歷史能力"],
  learning_performance: ["n-IV-1"],
  learning_content: ["N-7-1"],
  sub_question_count: 3,
  subquestion_configs: [
    { question_type: "選擇題", instruction: "歷史小題" },
  ],
};

const HISTORY_FIELDS: FormFields = {
  grade: 9,
  style: "課本",
  contentType: "純文字",
  customContentType: "",
  context: ["個人"],
  setType: "單一題",
  qType: ["選擇題"],
  count: 5,
  coverageMode: "balanced",
  skipVerify: true,
  disableReferenceFewshot: true,
  coreQuestionCallback: true,
  imageGenerationMode: "gpt_image",
  difficulty: "hard",
  reportingScale: "",
  subjectFilter: "數與量",
  passage: "歷史紀錄帶入的文本",
  textWordLimit: 180,
  textInstruction: "",
  options: ["歷史甲", "歷史乙", "歷史丙", "歷史丁"],
  topic: "歷史紀錄帶入的主題",
  coreQuestion: "歷史紀錄帶入的核心問題",
  subContext: "歷史情境",
  scienceCompetency: ["歷史能力"],
  learningPerformance: ["n-IV-1"],
  learningContent: ["N-7-1"],
  subQuestionCount: 3,
  subquestionConfigs: [
    { question_type: "選擇題", instruction: "歷史小題" },
    {},
    {},
  ],
  modelPlan: "",
  modelExecute: "",
  modelVerify: "",
  modelCorrect: "",
  effortPlan: "medium",
  effortExecute: "medium",
  effortVerify: "",
  effortCorrect: "",
};

function signIn(): void {
  useAuthStore.getState().login("token", {
    id: "teacher-choice",
    email: "teacher@example.com",
    created_at: "2026-01-01T00:00:00.000Z",
  });
}

function storeDraft(): void {
  localStorage.setItem(
    DRAFT_KEY,
    JSON.stringify({
      savedAt: new Date(NOW.getTime() - 60_000).toISOString(),
      fields: DRAFT_FIELDS,
    }),
  );
}

function storeDraftWithReportingScale(): void {
  localStorage.setItem(
    DRAFT_KEY,
    JSON.stringify({
      savedAt: new Date(NOW.getTime() - 60_000).toISOString(),
      fields: { ...DRAFT_FIELDS, reportingScale: "2" },
    }),
  );
}

function storeDraftWithSubquestionConfigs(): void {
  localStorage.setItem(
    DRAFT_KEY,
    JSON.stringify({
      savedAt: new Date(NOW.getTime() - 60_000).toISOString(),
      fields: DRAFT_FIELDS_WITH_SUBQUESTION_CONFIGS,
    }),
  );
}

function storeDraftWithUnknownCurriculumCodes(): void {
  localStorage.setItem(
    DRAFT_KEY,
    JSON.stringify({
      savedAt: new Date(NOW.getTime() - 60_000).toISOString(),
      fields: DRAFT_FIELDS_WITH_UNKNOWN_CURRICULUM_CODES,
    }),
  );
}

function renderWithHistory() {
  return render(
    <ParamForm
      subject="math"
      initialParams={HISTORY_PARAMS}
      onSubmit={() => {}}
      disabled={false}
    />,
  );
}

function topicInput(): HTMLInputElement {
  return screen.getByPlaceholderText(
    "例如：氣候變遷與都市規劃",
  ) as HTMLInputElement;
}

function countInput(): HTMLInputElement {
  return screen.getByLabelText("題數") as HTMLInputElement;
}

function storedDraftFields(): FormFields {
  return (
    JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null") as {
      fields: FormFields;
    }
  ).fields;
}

describe("ParamForm draft versus history choice", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    useLangStore.setState({ lang: "zh-TW" });
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    signIn();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows a three-way dialog with the existing identifying draft summary", async () => {
    storeDraft();
    renderWithHistory();

    const dialog = await screen.findByRole("dialog", {
      name: "同時找到未完成的草稿與從歷史紀錄帶入的設定，請選擇要使用的內容。",
    });
    const summary = within(dialog).getByRole("region", { name: "草稿摘要" });

    expect(summary).toHaveTextContent("草稿保存的主題");
    expect(summary).toHaveTextContent("草稿保存的核心問題");
    expect(
      within(dialog).getByRole("button", { name: "還原草稿" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "使用從歷史紀錄帶入的設定",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "重新開始" }),
    ).toBeInTheDocument();
  });

  it("shows the reporting scale in the history choice dialog full settings", async () => {
    storeDraftWithReportingScale();
    renderWithHistory();

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByText("完整設定", { selector: "summary" }),
    );

    const row = within(dialog).getByText("Reporting Scale", { selector: "dt" })
      .parentElement;
    expect(within(row!).getByText("2", { exact: true })).toBeInTheDocument();
  });

  it("renders saved per-subquestion settings as labelled cards in the history dialog", async () => {
    storeDraftWithSubquestionConfigs();
    renderWithHistory();

    const dialog = await screen.findByRole("dialog");
    within(dialog).getByRole("region", { name: "草稿摘要" });
    fireEvent.click(
      within(dialog).getByText("完整設定", { selector: "summary" }),
    );

    for (const label of [
      "第 1 小題",
      "第 2 小題",
      "題型:",
      "出題指示:",
      "題目內容類型:",
      "圖片生成模式:",
      "題目字數限制:",
      "選項字數限制:",
      "文本字數限制:",
    ]) {
      expect(dialog).toHaveTextContent(label);
    }

    expect(dialog).not.toHaveTextContent('"question_type"');
    expect(dialog).not.toHaveTextContent(
      JSON.stringify(DRAFT_FIELDS_WITH_SUBQUESTION_CONFIGS.subquestionConfigs),
    );

    const secondCard = within(dialog)
      .getByRole("heading", { name: "第 2 小題" })
      .closest("li");
    expect(secondCard).not.toBeNull();
    expect(secondCard).toHaveTextContent("（隨機）");
    expect(secondCard).toHaveTextContent("（沿用文本設定）");
    expect(secondCard).toHaveTextContent("不限");
    expect(secondCard).toHaveTextContent("學習內容: （沿用全域設定）");
    expect(secondCard).toHaveTextContent("學習表現: （沿用全域設定）");
  });

  it("renders curriculum instructions and preserves unknown draft codes in the history dialog", async () => {
    storeDraftWithUnknownCurriculumCodes();
    renderWithHistory();

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(
      within(dialog).getByText("完整設定", { selector: "summary" }),
    );

    const performanceRow = within(dialog).getByText("學習表現", { selector: "dt" })
      .parentElement!;
    expect(performanceRow).toHaveTextContent("理解數與量");
    const unknownPerformanceItem = within(performanceRow)
      .getByText("ZZ-IV-9", { exact: true })
      .closest("li");
    expect(unknownPerformanceItem).not.toBeNull();
    expect(unknownPerformanceItem).toHaveTextContent("ZZ-IV-9");
    expect(unknownPerformanceItem).not.toHaveTextContent("—");

    const contentRow = within(dialog).getByText("學習內容", { selector: "dt" })
      .parentElement!;
    expect(contentRow).toHaveTextContent("負數與數線");
    const unknownContentItem = within(contentRow)
      .getByText("ZZ-IV-9", { exact: true })
      .closest("li");
    expect(unknownContentItem).not.toBeNull();
    expect(unknownContentItem).toHaveTextContent("ZZ-IV-9");
    expect(unknownContentItem).not.toHaveTextContent("—");
  });

  it("restores the stored draft when the draft option is chosen", async () => {
    storeDraft();
    renderWithHistory();

    const dialog = await screen.findByRole("dialog");
    await act(async () => {
      fireEvent.click(
        within(dialog).getByRole("button", { name: "還原草稿" }),
      );
    });

    expect(topicInput()).toHaveValue("草稿保存的主題");
    expect(screen.getByLabelText("年級")).toHaveValue("8");
    expect(countInput()).toHaveValue(2);
    expect(screen.getByRole("checkbox", { name: "填充題" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "社會" })).toBeChecked();
    expect(storedDraftFields()).toEqual(DRAFT_FIELDS);
  });

  it("keeps the carried history fields when the history option is chosen", async () => {
    storeDraft();
    renderWithHistory();

    const dialog = await screen.findByRole("dialog");
    fireEvent.change(topicInput(), { target: { value: "選擇前暫時編輯" } });
    fireEvent.change(countInput(), { target: { value: "6" } });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "使用從歷史紀錄帶入的設定",
      }),
    );

    expect(topicInput()).toHaveValue("歷史紀錄帶入的主題");
    expect(screen.getByLabelText("年級")).toHaveValue("9");
    expect(countInput()).toHaveValue(5);
    expect(screen.getByRole("checkbox", { name: "選擇題" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "個人" })).toBeChecked();

    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(storedDraftFields()).toEqual(DRAFT_FIELDS);
  });

  it("starts from defaults without deleting the draft or reopening the dialog", async () => {
    storeDraft();
    const view = renderWithHistory();

    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "重新開始",
      }),
    );

    expect(topicInput()).toHaveValue("");
    expect(screen.getByLabelText("年級")).toHaveValue("7");
    expect(countInput()).toHaveValue(1);
    expect(screen.getByRole("checkbox", { name: "選擇題" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "填充題" })).not.toBeChecked();

    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(storedDraftFields()).toEqual(DRAFT_FIELDS);

    view.rerender(
      <ParamForm
        subject="math"
        initialParams={HISTORY_PARAMS}
        onSubmit={() => {}}
        disabled={false}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("silently uses history fields when there is no stored draft", async () => {
    renderWithHistory();

    expect(
      await screen.findByDisplayValue("歷史紀錄帶入的主題"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("年級")).toHaveValue("9");
    expect(countInput()).toHaveValue(5);
  });

  it("keeps history-carried fields out of the draft until a user edit", async () => {
    const firstMount = renderWithHistory();
    await screen.findByDisplayValue("歷史紀錄帶入的主題");

    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();

    fireEvent.change(countInput(), {
      target: { value: "6" },
    });
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(storedDraftFields()).toEqual({
      ...HISTORY_FIELDS,
      count: 6,
    });

    firstMount.unmount();
    render(
      <ParamForm subject="math" onSubmit={() => {}} disabled={false} />,
    );

    const prompt = await screen.findByRole("status");
    const summary = within(prompt).getByRole("region", { name: "草稿摘要" });
    expect(summary).toHaveTextContent("歷史紀錄帶入的主題");
    expect(summary).toHaveTextContent("歷史紀錄帶入的核心問題");
    expect(summary).toHaveTextContent("歷史紀錄帶入的文本");
    expect(summary).toHaveTextContent("選擇題");
    expect(summary).toHaveTextContent("個人");

    await act(async () => {
      fireEvent.click(
        within(prompt).getByRole("button", { name: "還原草稿" }),
      );
    });
    expect(topicInput()).toHaveValue("歷史紀錄帶入的主題");
    expect(screen.getByLabelText("年級")).toHaveValue("9");
    expect(countInput()).toHaveValue(6);
  });
});
