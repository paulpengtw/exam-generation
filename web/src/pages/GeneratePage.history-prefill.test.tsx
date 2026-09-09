import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FormFields } from "../components/ParamForm";
import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const generateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => ({ payload, drawn: [] })),
}));

vi.mock("../hooks/useFeedbackDialog", () => ({
  useFeedbackDialog: () => ({ enabled: false, open: vi.fn() }),
}));

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: "idle" as const,
    progressLines: [],
    results: [],
    displayResults: [],
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: null,
    finishedAt: null,
    subQuestionTotal: null,
    generate: generateMock,
    reset: vi.fn(),
  }),
}));

vi.mock("../lib/sessionRenewal", () => ({
  renewSessionIfNeeded: vi.fn(async () => undefined),
}));

vi.mock("../components/DestructiveConfirm", () => ({ default: () => null }));
vi.mock("../components/GenerationStatusBar", () => ({ default: () => null }));
vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));

vi.mock("../utils/odt", () => ({
  buildExamOdt: vi.fn(),
  formatTimestamp: vi.fn(() => "ts"),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useBlocker: () => ({ state: "unblocked", proceed: undefined, reset: undefined }),
  };
});

import { MemoryRouter, Route, Routes } from "react-router-dom";
import GeneratePage from "./GeneratePage";

const NATURAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [
    { value: "個人", instruction: "" },
    { value: "實驗室", instruction: "" },
  ],
  情境子類別: [
    { value: "健康", parent: "個人", admitted_by: { 情境: ["個人"] }, instruction: "" },
    { value: "野外調查", parent: "實驗室", admitted_by: { 情境: ["實驗室"] }, instruction: "" },
  ],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "Simple multiple-choice", instruction: "" },
    { value: "Complex multiple-choice", instruction: "" },
    { value: "Constructed response", instruction: "" },
  ],
  科學能力: [{ value: "證據推理", instruction: "" }],
  題目內容類型: [
    { value: "純文字", instruction: "" },
    { value: "含圖片", instruction: "" },
  ],
  科目: [{ value: "自然科學", instruction: "" }],
  學習表現: [
    { value: "tr-IV-1", instruction: "觀察與推理", 科目: "自然科學" },
    { value: "tr-IV-2", instruction: "分析資料", 科目: "自然科學" },
    { value: "tr-IV-3", instruction: "建立模型", 科目: "自然科學" },
  ],
  學習內容: [
    { value: "INc-IV-1", instruction: "物質組成", 科目: "自然科學" },
    { value: "INc-IV-2", instruction: "尺度與單位", 科目: "自然科學" },
    { value: "INc-IV-3", instruction: "能量轉換", 科目: "自然科學" },
  ],
};

const HISTORY_SUBQUESTION_ROWS = [
  {
    question_type: "Simple multiple-choice",
    instruction: "第一自然小題",
    content_type: "含圖片",
    image_generation_mode: "html",
    question_word_limit: 41,
    option_word_limit: 51,
    text_word_limit: 61,
    reporting_scale: "4",
    learning_content: ["INc-IV-1"],
    learning_performance: ["tr-IV-1"],
  },
  {
    question_type: "Complex multiple-choice",
    instruction: "第二自然小題",
    content_type: "純文字",
    image_generation_mode: "gpt_image",
    question_word_limit: 42,
    option_word_limit: 52,
    text_word_limit: 62,
    reporting_scale: "5",
    learning_content: ["INc-IV-2"],
    learning_performance: ["tr-IV-2"],
  },
  {
    question_type: "Constructed response",
    instruction: "第三自然小題",
    content_type: "含圖片",
    image_generation_mode: "html",
    question_word_limit: 43,
    option_word_limit: 53,
    text_word_limit: 63,
    reporting_scale: "6",
    learning_content: ["INc-IV-3"],
    learning_performance: ["tr-IV-3"],
  },
];

const HISTORY_PER_QUESTION_PARAMS = [
  {
    seed: 733,
    style: null,
    context: ["實驗室"],
    set_type: "題組題",
    q_type: ["Complex multiple-choice"],
    skip_verify: true,
    disable_reference_fewshot: true,
    image_generation_mode: "gpt_image",
    content_type: "含圖片",
    sub_context: "野外調查",
    science_competency: ["證據推理"],
    topic: "校園水質監測",
    core_question: "如何根據證據判斷水質？",
    learning_performance: ["tr-IV-2"],
    learning_content: ["INc-IV-2"],
    sub_question_count: 3,
    reporting_scale: "3",
    text_word_limit: 260,
    subquestion_configs: JSON.stringify(HISTORY_SUBQUESTION_ROWS),
    model_plan: "history-plan",
    model_execute: "history-execute",
    model_verify: "history-verify",
    model_correct: "history-correct",
    effort_plan: "high",
    effort_execute: "low",
    effort_verify: "high",
    effort_correct: "low",
  },
];

// This is the server's GenerateParams.model_dump(mode="json") shape: optional
// unset fields are retained as null, while per-question values remain nested.
const HISTORY_PARAMS = {
  subject: "natural_sciences",
  grade: 8,
  style: null,
  context: ["實驗室"],
  set_type: "題組題",
  q_type: ["Complex multiple-choice"],
  count: 1,
  skip_verify: true,
  disable_reference_fewshot: true,
  seed: null,
  max_retries: 3,
  allow_duplicate_figure_kinds: false,
  image_generation_mode: "gpt_image",
  difficulty: null,
  coverage_mode: "balanced",
  core_question_callback: false,
  subject_filter: null,
  content_type: "含圖片",
  content_domain: null,
  target_surface: null,
  passage: null,
  options: null,
  topic: "校園水質監測",
  core_question: "如何根據證據判斷水質？",
  sub_context: "野外調查",
  science_competency: ["證據推理"],
  learning_performance: null,
  core_competency: null,
  learning_content: null,
  sub_question_count: 3,
  question_word_limit: null,
  option_word_limit: null,
  text_word_limit: 260,
  subquestion_configs: JSON.stringify(HISTORY_SUBQUESTION_ROWS),
  per_question_params: JSON.stringify(HISTORY_PER_QUESTION_PARAMS),
  drawn: [],
  model_plan: "history-plan",
  model_execute: "history-execute",
  model_verify: "history-verify",
  model_correct: "history-correct",
  effort_plan: "high",
  effort_execute: "low",
  effort_verify: "high",
  effort_correct: "low",
  reporting_scale: "3",
};

// Aborted records use the same GenerateParams.model_dump(mode="json") writer
// as completed records; the distinction is the GenerationRecord status and
// null question payload, not a different request object.
const ABORTED_HISTORY_PARAMS = { ...HISTORY_PARAMS };

// Keep the model_dump envelope intact, but make the raw per-question row
// sparse as an aborted request may be. The server validates the JSON array and
// merges each row with the base params; nested fields remain optional.
const PARTIAL_ABORTED_HISTORY_PARAMS = {
  ...HISTORY_PARAMS,
  topic: "中斷時保存的主題",
  core_question: "中斷時保存的題幹",
  q_type: ["已停用的題型"],
  subquestion_configs: JSON.stringify([
    {
      question_type: "Complex multiple-choice",
      instruction: "中斷時已保存的小題指示",
    },
  ]),
  per_question_params: JSON.stringify([{
    topic: "中斷時保存的主題",
    core_question: "中斷時保存的題幹",
    sub_question_count: 3,
    subquestion_configs: JSON.stringify([
      {
        question_type: "Complex multiple-choice",
        instruction: "中斷時已保存的小題指示",
      },
    ]),
  }]),
};

const DRAFT_FIELDS: FormFields = {
  grade: 7,
  style: "",
  contentType: "純文字",
  customContentType: "",
  context: ["個人"],
  setType: "題組題",
  qType: ["Simple multiple-choice"],
  count: 2,
  coverageMode: "random",
  skipVerify: false,
  disableReferenceFewshot: false,
  coreQuestionCallback: true,
  imageGenerationMode: "html",
  difficulty: "",
  reportingScale: "1c",
  subjectFilter: "",
  passage: "",
  textWordLimit: null,
  options: [],
  topic: "草稿主題",
  coreQuestion: null,
  subContext: "健康",
  scienceCompetency: [],
  learningPerformance: [],
  learningContent: [],
  subQuestionCount: 3,
  subquestionConfigs: [{ instruction: "草稿小題" }, {}, {}],
  modelPlan: "",
  modelExecute: "",
  modelVerify: "",
  modelCorrect: "",
  effortPlan: "medium",
  effortExecute: "medium",
  effortVerify: "",
  effortCorrect: "",
};

function selectInField(label: string): HTMLSelectElement {
  const labelElement = screen
    .getAllByText(label, { selector: "label", exact: true })
    .find((element) => element.classList.contains("text-sm"));
  if (!labelElement) throw new Error(`Top-level label not found: ${label}`);
  return labelElement.parentElement!.querySelector("select") as HTMLSelectElement;
}

function renderPageWithHistoryState(prefillParams: Record<string, unknown> = HISTORY_PARAMS) {
  return render(
    <MemoryRouter
      initialEntries={[{
        pathname: "/generate/natural_sciences",
        state: { prefillParams },
      }]}
    >
      <Routes>
        <Route
          path="/generate/natural_sciences"
          element={<GeneratePage subject="natural_sciences" />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("GeneratePage history prefill with a saved draft", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    useLangStore.setState({ lang: "zh-TW" });
    useAuthStore.getState().login("history-route-token", {
      id: "history-route-user",
      email: "history-route@example.com",
      created_at: "2026-01-01T00:00:00.000Z",
    });
    localStorage.setItem(
      "exam_form_draft_history-route-user",
      JSON.stringify({
        savedAt: new Date().toISOString(),
        fields: DRAFT_FIELDS,
      }),
    );
    getSchemasMock.mockResolvedValue(NATURAL_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: ["history-plan", "history-execute", "history-verify", "history-correct"],
      defaults: {
        plan: "default-plan",
        execute: "default-execute",
        verify: "",
        correct: "",
        effort_plan: "medium",
        effort_execute: "medium",
        effort_verify: "",
        effort_correct: "",
      },
      effort: {
        "history-plan": ["low", "high"],
        "history-execute": ["low", "high"],
        "history-verify": ["low", "high"],
        "history-correct": ["low", "high"],
      },
    });
  });

  it("restores route-state history values after choosing history over the saved draft", async () => {
    renderPageWithHistoryState();

    const dialog = await screen.findByRole("dialog", {
      name: "同時找到未完成的草稿與從歷史紀錄帶入的設定，請選擇要使用的內容。",
    });
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "使用從歷史紀錄帶入的設定",
      }),
    );

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    expect(screen.getByLabelText("年級")).toHaveValue("8");
    expect(screen.getByDisplayValue("校園水質監測")).toBeInTheDocument();
    expect(selectInField("情境")).toHaveValue("實驗室");
    expect(selectInField("情境子類別")).toHaveValue("野外調查");
    expect(selectInField("題型種類")).toHaveValue("題組題");
    expect(screen.getByRole("checkbox", { name: "Complex multiple-choice" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "證據推理" })).toBeChecked();
    expect(selectInField("題目內容類型")).toHaveValue("含圖片");
    expect(selectInField("圖片產生方式")).toHaveValue("gpt_image");
    expect(screen.getByRole("checkbox", { name: "略過驗證" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "關閉參考範例" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "末小題回扣核心問題" })).not.toBeChecked();
    expect(screen.getByLabelText("題數")).toHaveValue(1);
    expect(screen.getByLabelText("小題數")).toHaveValue(3);
    expect(document.getElementById("text-word-limit")).toHaveValue(260);
    expect(screen.getAllByLabelText("Reporting Scale")[0]).toHaveValue("3");

    expect(screen.getByLabelText("規劃模型")).toHaveValue("history-plan");
    expect(screen.getByLabelText("出題模型")).toHaveValue("history-execute");
    expect(screen.getByLabelText("驗證模型")).toHaveValue("history-verify");
    expect(screen.getByLabelText("修正模型")).toHaveValue("history-correct");
    expect(screen.getByLabelText("規劃 Effort")).toHaveValue("high");
    expect(screen.getByLabelText("出題 Effort")).toHaveValue("low");
    expect(screen.getByLabelText("驗證 Effort")).toHaveValue("high");
    expect(screen.getByLabelText("修正 Effort")).toHaveValue("low");

    const subquestionHeading = screen.getByRole("heading", {
      name: "各小題配置",
      level: 4,
    });
    const subquestionSection = subquestionHeading.parentElement!;
    const expectedRows = [
      ["第一自然小題", "Simple multiple-choice", "41", "51", "4", "INc-IV-1", "tr-IV-1"],
      ["第二自然小題", "Complex multiple-choice", "42", "52", "5", "INc-IV-2", "tr-IV-2"],
      ["第三自然小題", "Constructed response", "43", "53", "6", "INc-IV-3", "tr-IV-3"],
    ];

    for (const [index, [instruction, questionType, questionLimit, optionLimit, scale, content, performance]] of expectedRows.entries()) {
      const row = within(subquestionSection)
        .getByText(`第${index + 1}小題`, { exact: true })
        .closest("div.rounded")!;
      expect(within(row).getByDisplayValue(instruction)).toBeInTheDocument();
      expect(within(row).getByLabelText("題型")).toHaveValue(questionType);
      expect(within(row).getByLabelText("題目內容類型")).toHaveValue(
        index === 1 ? "純文字" : "含圖片",
      );
      expect(within(row).getByLabelText("圖片生成模式")).toHaveValue(
        index === 1 ? "gpt_image" : "html",
      );
      expect(within(row).getByLabelText("題目字數限制")).toHaveValue(Number(questionLimit));
      expect(within(row).getByLabelText("選項字數限制")).toHaveValue(Number(optionLimit));
      expect(within(row).queryByLabelText("文本字數限制")).not.toBeInTheDocument();
      expect(within(row).getByLabelText("Reporting Scale")).toHaveValue(scale);
      expect(within(row).getByText(content, { exact: true })).toBeInTheDocument();
      expect(within(row).getByText(performance, { exact: true })).toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));

    await waitFor(() => expect(generateMock).toHaveBeenCalledTimes(1));
    const submitted = generateMock.mock.calls[0][0] as Record<string, unknown>;
    expect(submitted.core_question).toBe("如何根據證據判斷水質？");
    expect(submitted.drawn).toEqual(expect.any(Array));

    const submittedPerQuestion = JSON.parse(
      submitted.per_question_params as string,
    ) as Array<Record<string, unknown>>;
    expect(submittedPerQuestion).toHaveLength(1);
    expect(submittedPerQuestion[0]).toEqual(expect.objectContaining({
      context: ["實驗室"],
      q_type: ["Complex multiple-choice"],
      sub_context: "野外調查",
      science_competency: ["證據推理"],
      topic: "校園水質監測",
      core_question: "如何根據證據判斷水質？",
      reporting_scale: "3",
    }));
    const expectedSubquestionRows = HISTORY_SUBQUESTION_ROWS.map((row) => Object.fromEntries(Object.entries(row).filter(([k]) => k !== "text_word_limit")));
    expect(JSON.parse(submittedPerQuestion[0].subquestion_configs as string)).toEqual(
      expectedSubquestionRows,
    );
  });

  it("reloads a complete aborted-run payload with 題幹 values and every 各小題配置 row", async () => {
    localStorage.removeItem("exam_form_draft_history-route-user");
    renderPageWithHistoryState(ABORTED_HISTORY_PARAMS);

    await waitFor(() => {
      expect(screen.getByDisplayValue("校園水質監測")).toBeInTheDocument();
    });
    expect(
      screen.queryByText("部分儲存的參數已不在目前的題目設定中，保留為預設值。"),
    ).not.toBeInTheDocument();

    const subquestionSection = screen
      .getByRole("heading", { name: "各小題配置", level: 4 })
      .parentElement!;
    const expectedRows = [
      ["第一自然小題", "Simple multiple-choice", "41", "51", "4", "INc-IV-1", "tr-IV-1"],
      ["第二自然小題", "Complex multiple-choice", "42", "52", "5", "INc-IV-2", "tr-IV-2"],
      ["第三自然小題", "Constructed response", "43", "53", "6", "INc-IV-3", "tr-IV-3"],
    ];

    for (const [index, [instruction, questionType, questionLimit, optionLimit, scale, content, performance]] of expectedRows.entries()) {
      const row = within(subquestionSection)
        .getByText(`第${index + 1}小題`, { exact: true })
        .closest("div.rounded")!;
      expect(within(row).getByDisplayValue(instruction)).toBeInTheDocument();
      expect(within(row).getByLabelText("題型")).toHaveValue(questionType);
      expect(within(row).getByLabelText("題目字數限制")).toHaveValue(Number(questionLimit));
      expect(within(row).getByLabelText("選項字數限制")).toHaveValue(Number(optionLimit));
      expect(within(row).queryByLabelText("文本字數限制")).not.toBeInTheDocument();
      expect(within(row).getByLabelText("Reporting Scale")).toHaveValue(scale);
      expect(within(row).getByText(content, { exact: true })).toBeInTheDocument();
      expect(within(row).getByText(performance, { exact: true })).toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));

    await waitFor(() => expect(generateMock).toHaveBeenCalledTimes(1));
    const submitted = generateMock.mock.calls[0][0] as Record<string, unknown>;
    expect(submitted.topic).toBe("校園水質監測");
    expect(submitted.core_question).toBe("如何根據證據判斷水質？");
    const expectedSubquestionRows2 = HISTORY_SUBQUESTION_ROWS.map((row) => Object.fromEntries(Object.entries(row).filter(([k]) => k !== "text_word_limit")));
    expect(JSON.parse(submitted.per_question_params as string)[0].subquestion_configs).toBe(
      JSON.stringify(expectedSubquestionRows2),
    );
  });

  it("shows the existing prefill notice and keeps 題幹 values for a partial aborted payload", async () => {
    localStorage.removeItem("exam_form_draft_history-route-user");
    renderPageWithHistoryState(PARTIAL_ABORTED_HISTORY_PARAMS);

    expect(await screen.findByText("部分儲存的參數已不在目前的題目設定中，保留為預設值。"))
      .toBeInTheDocument();
    expect(await screen.findByDisplayValue("中斷時保存的主題")).toBeInTheDocument();
    expect(screen.getByDisplayValue("中斷時已保存的小題指示")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "各小題配置", level: 4 })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    expect(await screen.findByText("中斷時保存的題幹")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));

    await waitFor(() => expect(generateMock).toHaveBeenCalledTimes(1));
    const submitted = generateMock.mock.calls[0][0] as Record<string, unknown>;
    expect(submitted.topic).toBe("中斷時保存的主題");
    expect(submitted.core_question).toBe("中斷時保存的題幹");
    const submittedPerQuestion = JSON.parse(submitted.per_question_params as string) as Array<Record<string, unknown>>;
    expect(JSON.parse(submittedPerQuestion[0].subquestion_configs as string)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          question_type: "Complex multiple-choice",
          instruction: "中斷時已保存的小題指示",
        }),
      ]),
    );
  });
});
