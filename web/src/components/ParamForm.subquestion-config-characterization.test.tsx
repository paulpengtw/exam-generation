import { fireEvent, render, screen, within } from "@testing-library/react";
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
  useT: () => (key: string) =>
    key === "form.reporting_scale" ? "Reporting Scale" : key,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "社會選擇題", instruction: "" },
    { value: "社會開放題", instruction: "" },
  ],
  數學思考: [],
  question_style: [],
  題目內容類型: [
    { value: "純文字", instruction: "" },
    { value: "含圖片", instruction: "" },
  ],
  科目: [{ value: "歷史", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

const NATURAL_SCIENCES_SCHEMA = {
  ...SOCIAL_SCHEMA,
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "Maintenance of health", parent: "Personal", instruction: "" }],
  題型: [
    { value: "Simple multiple-choice", instruction: "" },
    { value: "Complex multiple-choice", instruction: "" },
    { value: "Constructed response", instruction: "" },
  ],
  科學能力: [{ value: "能力一", instruction: "" }],
  科目: [],
};

const CONFIGS = [
  {
    question_type: "Simple multiple-choice",
    instruction: "第一小題指示",
    text_word_limit: 11,
    question_word_limit: 22,
    option_word_limit: 33,
    content_type: "含圖片",
    image_generation_mode: "gpt_image" as const,
    reporting_scale: "4",
  },
  {
    question_type: "Complex multiple-choice",
    instruction: "第二小題指示",
    text_word_limit: 44,
    question_word_limit: 55,
    option_word_limit: 66,
    content_type: "純文字",
    image_generation_mode: "html" as const,
    reporting_scale: "5",
  },
  {
    question_type: "Constructed response",
    instruction: "第三小題指示",
    text_word_limit: 77,
    question_word_limit: 88,
    option_word_limit: 99,
    content_type: "含圖片",
    image_generation_mode: "gpt_image" as const,
    reporting_scale: "6",
  },
];

const SOCIAL_CONFIGS = CONFIGS.map((config, index) => ({
  ...config,
  question_type: index === 0 ? "社會選擇題" : "社會開放題",
  reporting_scale: undefined,
}));

function row(index: number): ReturnType<typeof within> {
  return within(screen.getByText(`第${index}小題`).closest("div")!);
}

describe("ParamForm 子題設定 rows characterization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    getSchemasMock.mockImplementation(async (subject: string) =>
      subject === "natural_sciences" ? NATURAL_SCIENCES_SCHEMA : SOCIAL_SCHEMA,
    );
  });

  it.each([
    ["social_studies", false],
    ["natural_sciences", true],
  ] as const)(
    "keeps all editable simple fields and change callbacks for %s rows",
    async (subject, hasReportingScale) => {
      const onUnsubmittedInput = vi.fn();
      render(
        <ParamForm
          subject={subject}
          onSubmit={vi.fn()}
          disabled={false}
          initialParams={{
            grade: 8,
            set_type: "題組題",
            sub_question_count: 3,
            subquestion_configs: hasReportingScale ? CONFIGS : SOCIAL_CONFIGS,
          }}
          onUnsubmittedInput={onUnsubmittedInput}
        />,
      );

      await screen.findByText("第1小題");

      for (const index of [1, 2, 3]) {
        const currentRow = row(index);
        expect(currentRow.getByText("題型", { selector: "label" })).toBeInTheDocument();
        expect(currentRow.getByText("文本字數限制", { selector: "label" })).toBeInTheDocument();
        expect(currentRow.getByText("題目字數限制", { selector: "label" })).toBeInTheDocument();
        expect(currentRow.getByText("選項字數限制", { selector: "label" })).toBeInTheDocument();
        expect(currentRow.getByText("題目內容類型", { selector: "label" })).toBeInTheDocument();
        expect(currentRow.getByText("圖片生成模式", { selector: "label" })).toBeInTheDocument();
        expect(currentRow.getByPlaceholderText("例如：請聚焦在資料判讀與因果推論")).toBeInTheDocument();
        expect(currentRow.getAllByRole("spinbutton")).toHaveLength(3);
        expect(currentRow.getAllByRole("combobox")).toHaveLength(hasReportingScale ? 4 : 3);
        if (hasReportingScale) {
          expect(currentRow.getByText("Reporting Scale", { selector: "label" })).toBeInTheDocument();
        } else {
          expect(currentRow.queryByText("Reporting Scale", { selector: "label" })).not.toBeInTheDocument();
        }
      }

      const firstRow = row(1);
      const selects = firstRow.getAllByRole("combobox");
      const numberInputs = firstRow.getAllByRole("spinbutton");
      const instruction = firstRow.getByPlaceholderText("例如：請聚焦在資料判讀與因果推論");
      const initialConfig = hasReportingScale ? CONFIGS[0] : SOCIAL_CONFIGS[0];

      expect(selects[0]).toHaveValue(initialConfig.question_type);
      expect(numberInputs.map((input) => (input as HTMLInputElement).value)).toEqual(["11", "22", "33"]);
      expect(selects[1]).toHaveValue(initialConfig.content_type);
      expect(selects[2]).toHaveValue(initialConfig.image_generation_mode);
      expect(instruction).toHaveValue(initialConfig.instruction);
      if (hasReportingScale) expect(selects[3]).toHaveValue(initialConfig.reporting_scale);

      const changes = [
        () => fireEvent.change(selects[0], { target: { value: "" } }),
        () => fireEvent.change(numberInputs[0], { target: { value: "101" } }),
        () => fireEvent.change(numberInputs[1], { target: { value: "202" } }),
        () => fireEvent.change(numberInputs[2], { target: { value: "303" } }),
        () => fireEvent.change(selects[1], { target: { value: "純文字" } }),
        () => fireEvent.change(selects[2], { target: { value: "html" } }),
        () => fireEvent.change(instruction, { target: { value: "更新後指示" } }),
      ];
      if (hasReportingScale) {
        changes.push(() => fireEvent.change(selects[3], { target: { value: "6" } }));
      }

      for (const change of changes) {
        onUnsubmittedInput.mockClear();
        change();
        expect(onUnsubmittedInput).toHaveBeenCalled();
      }

      expect(selects[0]).toHaveValue("");
      expect(numberInputs.map((input) => (input as HTMLInputElement).value)).toEqual(["101", "202", "303"]);
      expect(selects[1]).toHaveValue("純文字");
      expect(selects[2]).toHaveValue("html");
      expect(instruction).toHaveValue("更新後指示");
      if (hasReportingScale) expect(selects[3]).toHaveValue("6");
    },
  );
});
