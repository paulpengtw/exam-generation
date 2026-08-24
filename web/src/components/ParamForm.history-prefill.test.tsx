import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

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
  題目內容類型: [
    { value: "純文字", instruction: "" },
    { value: "含圖片", instruction: "" },
  ],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [
    { value: "n-IV-1", instruction: "理解數與量", 科目: "n" },
    { value: "a-IV-1", instruction: "理解代數", 科目: "a" },
  ],
  學習內容: [
    { value: "N-7-1", instruction: "負數與數線", 科目: "N" },
    { value: "A-7-2", instruction: "一元一次方程式", 科目: "A" },
  ],
};

const MATH_PER_QUESTION_PARAMS = [
  {
    seed: 101,
    style: ["課本"],
    content_type: "含圖片",
    context: ["個人"],
    set_type: "單一題",
    q_type: ["選擇題"],
    difficulty: "hard",
    skip_verify: true,
    image_generation_mode: "html",
    passage: null,
    options: ["甲選項", "乙選項", "丙選項", "丁選項"],
    topic: "歷史河川",
    core_question: "河川如何影響聚落？",
    learning_performance: ["n-IV-1"],
    learning_content: ["N-7-1"],
    text_word_limit: 180,
  },
  {
    seed: 202,
    style: ["素養"],
    content_type: "純文字",
    context: ["社會"],
    set_type: "單一題",
    q_type: ["填充題"],
    difficulty: "easy",
    skip_verify: true,
    image_generation_mode: "html",
    passage: null,
    options: ["甲選項", "乙選項", "丙選項", "丁選項"],
    topic: "歷史河川",
    core_question: "河川如何影響聚落？",
    learning_performance: ["a-IV-1"],
    learning_content: ["A-7-2"],
    text_word_limit: 180,
  },
];

const MATH_HISTORY_PARAMS = {
  grade: 8,
  style: ["課本"],
  content_type: "含圖片",
  context: ["個人"],
  set_type: "單一題",
  q_type: ["選擇題"],
  count: 2,
  skip_verify: true,
  disable_reference_fewshot: true,
  image_generation_mode: "html",
  difficulty: "hard",
  passage: null,
  options: ["甲選項", "乙選項", "丙選項", "丁選項"],
  topic: "歷史河川",
  core_question: "河川如何影響聚落？",
  learning_performance: ["n-IV-1"],
  learning_content: ["N-7-1"],
  text_word_limit: 180,
  per_question_params: JSON.stringify(MATH_PER_QUESTION_PARAMS),
};

const SOCIAL_SCHEMA = {
  ...MATH_SCHEMA,
  情境: [
    { value: "個人", instruction: "" },
    { value: "公共", instruction: "" },
  ],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "開放式建構反應題", instruction: "" },
  ],
  科目: [
    { value: "歷史", instruction: "" },
    { value: "地理", instruction: "" },
  ],
  學習表現: [
    { value: "社1a-Ⅳ-1", instruction: "理解歷史時序", 科目: "社" },
    { value: "社1a-Ⅳ-2", instruction: "解讀史料", 科目: "社" },
  ],
  學習內容: [
    { value: "歷Ka-Ⅳ-1", instruction: "臺灣早期歷史", 科目: "歷" },
    { value: "歷Ka-Ⅳ-2", instruction: "清代臺灣社會", 科目: "歷" },
  ],
};

const SOCIAL_ROWS_ONE = [
  {
    question_type: "選擇題",
    instruction: "第一小題指示",
    content_type: "含圖片",
    image_generation_mode: "html",
    question_word_limit: 21,
    option_word_limit: 31,
    text_word_limit: 41,
    learning_content: ["歷Ka-Ⅳ-1"],
    learning_performance: ["社1a-Ⅳ-1"],
  },
  {
    question_type: "開放式建構反應題",
    instruction: "第二小題指示",
    content_type: "純文字",
    image_generation_mode: "gpt_image",
    question_word_limit: 22,
    option_word_limit: 32,
    text_word_limit: 42,
    learning_content: ["歷Ka-Ⅳ-2"],
    learning_performance: ["社1a-Ⅳ-2"],
  },
  {
    question_type: "開放式建構反應題",
    instruction: "第三小題指示",
    content_type: "含圖片",
    image_generation_mode: "html",
    question_word_limit: 23,
    option_word_limit: 33,
    text_word_limit: 43,
    learning_content: ["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2"],
    learning_performance: ["社1a-Ⅳ-1", "社1a-Ⅳ-2"],
  },
];

const SOCIAL_ROWS_TWO = [
  {
    question_type: "開放式建構反應題",
    instruction: "第二題第一小題",
    content_type: "純文字",
    image_generation_mode: "html",
    question_word_limit: 51,
    option_word_limit: 61,
    text_word_limit: 71,
    learning_content: ["歷Ka-Ⅳ-2"],
    learning_performance: ["社1a-Ⅳ-2"],
  },
  {
    question_type: "選擇題",
    instruction: "第二題第二小題",
    content_type: "含圖片",
    image_generation_mode: "gpt_image",
    question_word_limit: 52,
    option_word_limit: 62,
    text_word_limit: 72,
    learning_content: ["歷Ka-Ⅳ-1"],
    learning_performance: ["社1a-Ⅳ-1"],
  },
  {
    question_type: "開放式建構反應題",
    instruction: "第二題第三小題",
    content_type: "純文字",
    image_generation_mode: "html",
    question_word_limit: 53,
    option_word_limit: 63,
    text_word_limit: 73,
    learning_content: ["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2"],
    learning_performance: ["社1a-Ⅳ-1", "社1a-Ⅳ-2"],
  },
];

const SOCIAL_PER_QUESTION_PARAMS = [
  {
    seed: 303,
    context: ["公共"],
    set_type: "題組題",
    q_type: [],
    skip_verify: false,
    disable_reference_fewshot: false,
    image_generation_mode: "gpt_image",
    coverage_mode: "random",
    subject_filter: ["歷史"],
    content_type: "含圖片",
    topic: "清代港口",
    core_question: "港口如何改變地方社會？",
    learning_performance: ["社1a-Ⅳ-1"],
    learning_content: ["歷Ka-Ⅳ-1"],
    sub_question_count: 3,
    subquestion_configs: JSON.stringify(SOCIAL_ROWS_ONE),
  },
  {
    seed: 404,
    context: ["公共"],
    set_type: "題組題",
    q_type: [],
    skip_verify: false,
    disable_reference_fewshot: false,
    image_generation_mode: "gpt_image",
    coverage_mode: "random",
    subject_filter: ["歷史"],
    content_type: "含圖片",
    topic: "清代港口",
    core_question: "港口如何改變地方社會？",
    learning_performance: ["社1a-Ⅳ-1"],
    learning_content: ["歷Ka-Ⅳ-1"],
    sub_question_count: 3,
    subquestion_configs: JSON.stringify(SOCIAL_ROWS_TWO),
  },
];

const SOCIAL_HISTORY_PARAMS = {
  grade: 9,
  context: ["公共"],
  set_type: "題組題",
  q_type: [],
  count: 2,
  skip_verify: false,
  disable_reference_fewshot: false,
  image_generation_mode: "gpt_image",
  coverage_mode: "random",
  subject_filter: ["歷史"],
  content_type: "含圖片",
  topic: "清代港口",
  core_question: "港口如何改變地方社會？",
  learning_performance: ["社1a-Ⅳ-1"],
  learning_content: ["歷Ka-Ⅳ-1"],
  text_word_limit: 240,
  sub_question_count: 3,
  subquestion_configs: JSON.stringify(SOCIAL_ROWS_ONE),
  per_question_params: JSON.stringify(SOCIAL_PER_QUESTION_PARAMS),
};

const NATURAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "自然選擇題", instruction: "" },
    { value: "自然開放題", instruction: "" },
  ],
  科學能力: [{ value: "探究能力", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  學習表現: [
    { value: "tr-IV-1", instruction: "觀察與推理", 科目: "自然科學" },
    { value: "tr-IV-2", instruction: "分析資料", 科目: "自然科學" },
  ],
  學習內容: [
    { value: "INc-IV-1", instruction: "物質組成", 科目: "自然科學" },
    { value: "INc-IV-2", instruction: "尺度與單位", 科目: "自然科學" },
  ],
};

const NATURAL_SUBQUESTION_ROWS = [
  {
    question_type: "自然選擇題",
    instruction: "第一自然小題",
    content_type: "純文字",
    text_word_limit: 44,
    reporting_scale: "4",
    learning_content: ["INc-IV-1"],
    learning_performance: ["tr-IV-1"],
  },
  {
    question_type: "自然開放題",
    instruction: "第二自然小題",
    content_type: "純文字",
    text_word_limit: 45,
    reporting_scale: "5",
    learning_content: ["INc-IV-2"],
    learning_performance: ["tr-IV-2"],
  },
  {
    question_type: "自然選擇題",
    instruction: "第三自然小題",
    content_type: "純文字",
    text_word_limit: 46,
    reporting_scale: "6",
    learning_content: ["INc-IV-1", "INc-IV-2"],
    learning_performance: ["tr-IV-1", "tr-IV-2"],
  },
];

const NATURAL_PER_QUESTION_PARAMS = [{
  seed: 505,
  context: ["個人"],
  set_type: "題組題",
  q_type: ["自然選擇題"],
  skip_verify: true,
  disable_reference_fewshot: true,
  image_generation_mode: "gpt_image",
  content_type: "純文字",
  sub_context: "健康",
  science_competency: ["探究能力"],
  topic: "校園飲水",
  core_question: "如何判斷飲水安全？",
  learning_performance: ["tr-IV-1", "tr-IV-2"],
  learning_content: ["INc-IV-1", "INc-IV-2"],
  sub_question_count: 3,
  reporting_scale: "3",
  text_word_limit: 260,
  subquestion_configs: JSON.stringify(NATURAL_SUBQUESTION_ROWS),
}];

const NATURAL_HISTORY_PARAMS = {
  grade: 7,
  context: ["個人"],
  set_type: "題組題",
  q_type: ["自然選擇題"],
  count: 1,
  skip_verify: true,
  disable_reference_fewshot: true,
  image_generation_mode: "gpt_image",
  core_question_callback: false,
  content_type: "純文字",
  sub_context: "健康",
  science_competency: ["探究能力"],
  topic: "校園飲水",
  core_question: "如何判斷飲水安全？",
  learning_performance: ["tr-IV-1", "tr-IV-2"],
  learning_content: ["INc-IV-1", "INc-IV-2"],
  sub_question_count: 3,
  reporting_scale: "3",
  text_word_limit: 260,
  subquestion_configs: JSON.stringify(NATURAL_SUBQUESTION_ROWS),
  per_question_params: JSON.stringify(NATURAL_PER_QUESTION_PARAMS),
};

describe("ParamForm history prefill", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
  });

  it("re-submits a math history entry with its resolved per-question parameters pinned", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        initialParams={MATH_HISTORY_PARAMS}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    fireEvent.click(await screen.findByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;

    expect(submitted).toEqual(expect.objectContaining({
      grade: 8,
      style: "課本",
      content_type: "含圖片",
      context: ["個人"],
      set_type: "單一題",
      q_type: ["選擇題"],
      count: 2,
      skip_verify: true,
      disable_reference_fewshot: true,
      image_generation_mode: "html",
      difficulty: "hard",
      passage: undefined,
      options: ["甲選項", "乙選項", "丙選項", "丁選項"],
      topic: "歷史河川",
      core_question: "河川如何影響聚落？",
      learning_performance: ["n-IV-1"],
      learning_content: ["N-7-1"],
      text_word_limit: 180,
    }));
    expect(submitted.predrawn_fields).toBe("[]");
    expect(JSON.parse(submitted.per_question_params as string)).toEqual(
      MATH_PER_QUESTION_PARAMS,
    );
  });

  it("restores a provenance-marked request-level slot to random before re-submitting", async () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      const onSubmit = vi.fn();
      render(
        <ParamForm
          subject="math"
          initialParams={{
            grade: 7,
            style: "課本",
            content_type: "純文字",
            context: ["個人"],
            set_type: "單一題",
            q_type: ["選擇題"],
            count: 1,
            learning_performance: ["n-IV-1"],
            learning_content: ["N-7-1"],
            predrawn_fields: JSON.stringify(["learning_content"]),
          }}
          onSubmit={onSubmit}
          disabled={false}
        />,
      );

      fireEvent.click(await screen.findByText("form.btn_generate"));
      await screen.findByText("form.confirm_title");

      const learningContentRow = screen
        .getByText("form.confirm_learning_content", { selector: "dt" })
        .parentElement!;
      expect(learningContentRow).toHaveTextContent("form.confirm_lc_random_pool");
      expect(learningContentRow).toHaveTextContent("A-7-2");

      fireEvent.click(screen.getByText("form.btn_confirm_send"));
      await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      const predrawnFields = JSON.parse(submitted.predrawn_fields as string) as string[];

      expect(submitted.learning_content).toEqual(["A-7-2"]);
      expect(submitted.learning_performance).toEqual(["n-IV-1"]);
      expect(predrawnFields).toContain("learning_content");
      expect(predrawnFields).not.toContain("learning_performance");
    } finally {
      random.mockRestore();
    }
  });

  it("restores a provenance-marked per-question slot while preserving its siblings", async () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      const onSubmit = vi.fn();
      render(
        <ParamForm
          subject="math"
          initialParams={{
            ...MATH_HISTORY_PARAMS,
            predrawn_fields: JSON.stringify(["per_question_params[0].style"]),
          }}
          onSubmit={onSubmit}
          disabled={false}
        />,
      );

      fireEvent.click(await screen.findByText("form.btn_generate"));
      await screen.findByText("form.confirm_title");

      const styleRows = screen.getAllByText("form.confirm_style", { selector: "dt" });
      expect(styleRows[0].parentElement).toHaveTextContent("form.confirm_badge_random");
      expect(styleRows[1].parentElement).toHaveTextContent("form.confirm_badge_user");

      fireEvent.click(screen.getByText("form.btn_confirm_send"));
      await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      const perQuestion = JSON.parse(submitted.per_question_params as string) as Record<string, unknown>[];
      const predrawnFields = JSON.parse(submitted.predrawn_fields as string) as string[];

      expect(perQuestion[0].style).toEqual(["素養"]);
      expect(perQuestion[0].seed).toBe(101);
      expect(perQuestion[1]).toEqual(MATH_PER_QUESTION_PARAMS[1]);
      expect(predrawnFields).toContain("per_question_params[0].style");
      expect(predrawnFields).not.toContain("per_question_params[1].style");
    } finally {
      random.mockRestore();
    }
  });

  it("restores a provenance-marked social-studies per-question slot", async () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
      const onSubmit = vi.fn();
      render(
        <ParamForm
          subject="social_studies"
          initialParams={{
            ...SOCIAL_HISTORY_PARAMS,
            predrawn_fields: JSON.stringify(["per_question_params[0].subject_filter"]),
          }}
          onSubmit={onSubmit}
          disabled={false}
        />,
      );

      fireEvent.click(await screen.findByText("form.btn_generate"));
      await screen.findByText("form.confirm_title");

      const questionRegions = screen.getAllByRole("region", { name: "form.confirm_question_block" });
      const subjectFilterRows = questionRegions.map((region) =>
        within(region).getByText("form.confirm_subject_filter", { selector: "dt" }),
      );
      expect(subjectFilterRows[0].parentElement).toHaveTextContent("form.confirm_badge_random");
      expect(subjectFilterRows[1].parentElement).toHaveTextContent("form.confirm_badge_user");

      fireEvent.click(screen.getByText("form.btn_confirm_send"));
      await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      const perQuestion = JSON.parse(submitted.per_question_params as string) as Record<string, unknown>[];
      const predrawnFields = JSON.parse(submitted.predrawn_fields as string) as string[];

      expect(perQuestion[0].subject_filter).toEqual(["地理"]);
      expect(perQuestion[1]).toEqual(SOCIAL_PER_QUESTION_PARAMS[1]);
      expect(predrawnFields).toContain("per_question_params[0].subject_filter");
      expect(predrawnFields).not.toContain("per_question_params[1].subject_filter");
    } finally {
      random.mockRestore();
    }
  });

  it("restores a provenance-marked natural-sciences per-question slot", async () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      getSchemasMock.mockResolvedValue(NATURAL_SCHEMA);
      const onSubmit = vi.fn();
      render(
        <ParamForm
          subject="natural_sciences"
          initialParams={{
            ...NATURAL_HISTORY_PARAMS,
            predrawn_fields: JSON.stringify(["per_question_params[0].q_type"]),
          }}
          onSubmit={onSubmit}
          disabled={false}
        />,
      );

      fireEvent.click(await screen.findByText("form.btn_generate"));
      await screen.findByText("form.confirm_title");

      const questionTypeRows = screen.getAllByText("form.confirm_q_type", { selector: "dt" });
      expect(questionTypeRows[0].parentElement).toHaveTextContent("form.confirm_badge_random");

      fireEvent.click(screen.getByText("form.btn_confirm_send"));
      await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      const perQuestion = JSON.parse(submitted.per_question_params as string) as Record<string, unknown>[];
      const predrawnFields = JSON.parse(submitted.predrawn_fields as string) as string[];

      expect(perQuestion[0].q_type).toEqual(["自然開放題"]);
      expect(predrawnFields).toContain("per_question_params[0].q_type");
    } finally {
      random.mockRestore();
    }
  });

  it("restores a provenance-marked social-studies per-小題 slot", async () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
      const onSubmit = vi.fn();
      render(
        <ParamForm
          subject="social_studies"
          initialParams={{
            ...SOCIAL_HISTORY_PARAMS,
            learning_content: ["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2"],
            predrawn_fields: JSON.stringify([
              "per_question_params[0].subquestion_configs[0].learning_content",
            ]),
          }}
          onSubmit={onSubmit}
          disabled={false}
        />,
      );

      fireEvent.click(await screen.findByText("form.btn_generate"));
      await screen.findByText("form.confirm_title");

      const questionRegions = screen.getAllByRole("region", { name: "form.confirm_question_block" });
      expect(within(questionRegions[0]).getByText("form.confirm_subq_lc_random_pool")).toBeInTheDocument();

      fireEvent.click(screen.getByText("form.btn_confirm_send"));
      await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      const perQuestion = JSON.parse(submitted.per_question_params as string) as Record<string, unknown>[];
      const firstQuestionRows = JSON.parse(perQuestion[0].subquestion_configs as string) as Record<string, unknown>[];
      const secondQuestionRows = JSON.parse(perQuestion[1].subquestion_configs as string) as Record<string, unknown>[];
      const predrawnFields = JSON.parse(submitted.predrawn_fields as string) as string[];

      expect(firstQuestionRows[0].learning_content).toEqual(["歷Ka-Ⅳ-2"]);
      expect(firstQuestionRows[1]).toEqual(SOCIAL_ROWS_ONE[1]);
      expect(secondQuestionRows).toEqual(SOCIAL_ROWS_TWO);
      expect(predrawnFields).toContain(
        "per_question_params[0].subquestion_configs[0].learning_content",
      );
    } finally {
      random.mockRestore();
    }
  });

  it("restores a provenance-marked natural-sciences per-小題 slot", async () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      getSchemasMock.mockResolvedValue(NATURAL_SCHEMA);
      const onSubmit = vi.fn();
      render(
        <ParamForm
          subject="natural_sciences"
          initialParams={{
            ...NATURAL_HISTORY_PARAMS,
            predrawn_fields: JSON.stringify([
              "per_question_params[0].subquestion_configs[0].learning_content",
            ]),
          }}
          onSubmit={onSubmit}
          disabled={false}
        />,
      );

      fireEvent.click(await screen.findByText("form.btn_generate"));
      await screen.findByText("form.confirm_title");

      const questionRegions = screen.getAllByRole("region", { name: "form.confirm_question_block" });
      expect(within(questionRegions[0]).getByText("form.confirm_subq_lc_random_pool")).toBeInTheDocument();

      fireEvent.click(screen.getByText("form.btn_confirm_send"));
      await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      const perQuestion = JSON.parse(submitted.per_question_params as string) as Record<string, unknown>[];
      const rows = JSON.parse(perQuestion[0].subquestion_configs as string) as Record<string, unknown>[];
      const predrawnFields = JSON.parse(submitted.predrawn_fields as string) as string[];

      expect(rows[0].learning_content).toEqual(["INc-IV-2"]);
      expect(rows[1]).toEqual(NATURAL_SUBQUESTION_ROWS[1]);
      expect(rows[2]).toEqual(NATURAL_SUBQUESTION_ROWS[2]);
      expect(predrawnFields).toContain(
        "per_question_params[0].subquestion_configs[0].learning_content",
      );
    } finally {
      random.mockRestore();
    }
  });

  it("re-submits social-studies history with coverage mode and every 各小題配置 row preserved", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        initialParams={SOCIAL_HISTORY_PARAMS}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    expect(await screen.findByDisplayValue("第一小題指示")).toBeInTheDocument();
    expect(screen.getByDisplayValue("41")).toBeInTheDocument();

    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(submitted).toEqual(expect.objectContaining({
      grade: 9,
      context: ["公共"],
      set_type: "題組題",
      count: 2,
      coverage_mode: "random",
      subject_filter: "歷史",
      content_type: "含圖片",
      topic: "清代港口",
      core_question: "港口如何改變地方社會？",
      text_word_limit: 240,
      sub_question_count: 3,
    }));
    expect(JSON.parse(submitted.per_question_params as string)).toEqual(
      SOCIAL_PER_QUESTION_PARAMS,
    );
  });

  it("re-submits natural-sciences history with Reporting Scale, pools, rows, and saved model tiers", async () => {
    const naturalSchema = {
      ...SOCIAL_SCHEMA,
      情境: [{ value: "個人", instruction: "" }],
      情境子類別: [{ value: "健康", parent: "個人", instruction: "" }],
      題型種類: [{ value: "題組題", instruction: "" }],
      題型: [
        { value: "自然選擇題", instruction: "" },
        { value: "自然開放題", instruction: "" },
      ],
      科學能力: [{ value: "探究能力", instruction: "" }],
      科目: [{ value: "自然科學", instruction: "" }],
      學習表現: [
        { value: "tr-IV-1", instruction: "觀察與推理", 科目: "自然科學" },
        { value: "tr-IV-2", instruction: "分析資料", 科目: "自然科學" },
      ],
      學習內容: [
        { value: "INc-IV-1", instruction: "物質組成", 科目: "自然科學" },
        { value: "INc-IV-2", instruction: "尺度與單位", 科目: "自然科學" },
      ],
    };
    const naturalRows = [
      {
        question_type: "自然選擇題",
        instruction: "第一自然小題",
        content_type: "含圖片",
        image_generation_mode: "html",
        question_word_limit: 24,
        option_word_limit: 34,
        text_word_limit: 44,
        reporting_scale: "4",
        learning_content: ["INc-IV-1"],
        learning_performance: ["tr-IV-1"],
      },
      {
        question_type: "自然開放題",
        instruction: "第二自然小題",
        content_type: "純文字",
        image_generation_mode: "gpt_image",
        question_word_limit: 25,
        option_word_limit: 35,
        text_word_limit: 45,
        reporting_scale: "5",
        learning_content: ["INc-IV-2"],
        learning_performance: ["tr-IV-2"],
      },
      {
        question_type: "自然選擇題",
        instruction: "第三自然小題",
        content_type: "含圖片",
        image_generation_mode: "html",
        question_word_limit: 26,
        option_word_limit: 36,
        text_word_limit: 46,
        reporting_scale: "6",
        learning_content: ["INc-IV-1", "INc-IV-2"],
        learning_performance: ["tr-IV-1", "tr-IV-2"],
      },
    ];
    const naturalPerQuestion = [{
      seed: 505,
      context: ["個人"],
      set_type: "題組題",
      q_type: ["自然選擇題"],
      skip_verify: true,
      disable_reference_fewshot: true,
      image_generation_mode: "gpt_image",
      content_type: "含圖片",
      sub_context: "健康",
      science_competency: ["探究能力"],
      topic: "校園飲水",
      core_question: "如何判斷飲水安全？",
      learning_performance: ["tr-IV-1"],
      learning_content: ["INc-IV-1"],
      sub_question_count: 3,
      reporting_scale: "3",
      text_word_limit: 260,
      model_plan: "saved-plan",
      model_execute: "saved-execute",
      model_verify: "saved-verify",
      model_correct: "saved-correct",
      effort_plan: "high",
      effort_execute: "low",
      effort_verify: "high",
      effort_correct: "low",
      subquestion_configs: JSON.stringify(naturalRows),
    }];
    const naturalHistory = {
      grade: 7,
      context: ["個人"],
      set_type: "題組題",
      q_type: ["自然選擇題"],
      count: 1,
      skip_verify: true,
      disable_reference_fewshot: true,
      image_generation_mode: "gpt_image",
      core_question_callback: false,
      content_type: "含圖片",
      sub_context: "健康",
      science_competency: ["探究能力"],
      topic: "校園飲水",
      core_question: "如何判斷飲水安全？",
      learning_performance: ["tr-IV-1"],
      learning_content: ["INc-IV-1"],
      sub_question_count: 3,
      reporting_scale: "3",
      text_word_limit: 260,
      model_plan: "saved-plan",
      model_execute: "saved-execute",
      model_verify: "saved-verify",
      model_correct: "saved-correct",
      effort_plan: "high",
      effort_execute: "low",
      effort_verify: "high",
      effort_correct: "low",
      subquestion_configs: JSON.stringify(naturalRows),
      per_question_params: JSON.stringify(naturalPerQuestion),
    };
    getSchemasMock.mockResolvedValue(naturalSchema);
    getAvailableModelsMock.mockResolvedValue({
      allowed: ["saved-plan", "saved-execute", "saved-verify", "saved-correct"],
      defaults: { plan: "", execute: "" },
      effort: {
        "saved-plan": ["low", "high"],
        "saved-execute": ["low", "high"],
        "saved-verify": ["low", "high"],
        "saved-correct": ["low", "high"],
      },
    });
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        initialParams={naturalHistory}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    expect(await screen.findByDisplayValue("第一自然小題")).toBeInTheDocument();
    // The form-level Reporting Scale select has id="reporting_scale" (static);
    // subquestion editor selects use useId() so multiple labels share the same text.
    expect(screen.getAllByLabelText("form.reporting_scale")[0]).toHaveValue("3");

    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(submitted).toEqual(expect.objectContaining({
      grade: 7,
      context: ["個人"],
      set_type: "題組題",
      q_type: ["自然選擇題"],
      count: 1,
      skip_verify: true,
      disable_reference_fewshot: true,
      image_generation_mode: "gpt_image",
      core_question_callback: false,
      content_type: "含圖片",
      sub_context: "健康",
      science_competency: ["探究能力"],
      topic: "校園飲水",
      core_question: "如何判斷飲水安全？",
      learning_performance: ["tr-IV-1"],
      learning_content: ["INc-IV-1"],
      sub_question_count: 3,
      reporting_scale: "3",
      text_word_limit: 260,
      model_plan: "saved-plan",
      model_execute: "saved-execute",
      model_verify: "saved-verify",
      model_correct: "saved-correct",
      effort_plan: "high",
      effort_execute: "low",
      effort_verify: "high",
      effort_correct: "low",
    }));
    expect(JSON.parse(submitted.per_question_params as string)).toEqual(
      naturalPerQuestion,
    );
  });
});
