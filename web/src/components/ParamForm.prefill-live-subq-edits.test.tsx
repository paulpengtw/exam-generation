import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: resolveGenerateMock,
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm, { type FormParams } from "./ParamForm";
import { buildQueryString } from "../hooks/useGenerate";
import { toGenerateParams } from "../utils/toGenerateParams";

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [8],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "社歷史-舊題型", instruction: "歷史舊題型" },
    { value: "社使用者-題型", instruction: "使用者挑選的題型" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  學習表現: [
    {
      value: "社全域-表現",
      instruction: "全域表現",
      科目: "社",
      admitted_by: { 科目: ["歷史"] },
    },
    {
      value: "社使用者-表現",
      instruction: "使用者挑選的表現",
      科目: "社",
      admitted_by: { 科目: ["歷史"] },
    },
    {
      value: "社歷史-舊表現",
      instruction: "歷史舊表現",
      科目: "社",
      admitted_by: { 科目: ["歷史"] },
    },
    {
      value: "社兄弟-未觸碰表現",
      instruction: "未觸碰的兄弟小題表現",
      科目: "社",
      admitted_by: { 科目: ["歷史"] },
    },
  ],
  學習內容: [
    {
      value: "社全域-內容",
      instruction: "全域內容",
      科目: "社",
      admitted_by: { 科目: ["歷史"] },
    },
    {
      value: "社使用者-內容",
      instruction: "使用者挑選的內容",
      科目: "社",
      admitted_by: { 科目: ["歷史"] },
    },
  ],
};

const NATURAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [8],
  情境: [{ value: "個人", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "Simple multiple-choice", instruction: "" },
    { value: "Complex multiple-choice", instruction: "" },
    { value: "Constructed response", instruction: "" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  科學能力: [{ value: "探究能力", instruction: "" }],
  學習表現: [
    { value: "自然全域-表現", instruction: "全域表現", 科目: "自然科學" },
    { value: "自然使用者-表現", instruction: "使用者挑選的表現", 科目: "自然科學" },
  ],
  學習內容: [
    { value: "自然全域-內容", instruction: "全域內容", 科目: "自然科學" },
    { value: "自然使用者-內容", instruction: "使用者挑選的內容", 科目: "自然科學" },
  ],
};

function subquestionRow(index: number): ReturnType<typeof within> {
  return within(screen.getByText(`第${index}小題`).closest("div.rounded")!);
}

function requestQuery(subject: string, onSubmit: ReturnType<typeof vi.fn>): URLSearchParams {
  const formParams = onSubmit.mock.calls.at(-1)?.[0] as FormParams;
  return new URLSearchParams(
    buildQueryString(toGenerateParams(subject, formParams)),
  );
}

describe("ParamForm prefilled live 各小題配置 edits", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({
      payload,
      drawn: [],
    }));
  });

  it("sends a live 各小題配置 學習表現 selection through 發送前確認 when history has no per-小題 codes", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          learning_performance: ["社全域-表現"],
          learning_content: ["社全域-內容"],
          sub_question_count: 2,
          per_question_params: JSON.stringify([{
            seed: 6381,
            sub_question_count: 2,
            learning_performance: ["社全域-表現"],
            learning_content: ["社全域-內容"],
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const learningPerformancePicker = firstRow.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(learningPerformancePicker, { target: { value: "社使用者-表現" } });
    fireEvent.mouseDown(firstRow.getByRole("button", { name: /社使用者-表現/ }));

    const generateButton = await screen.findByText("form.btn_generate");
    fireEvent.submit(generateButton.closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const perQuestion = JSON.parse(
      requestQuery("social_studies", onSubmit).get("per_question_params")!,
    ) as Array<{ subquestion_configs?: string }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs!) as Array<{
      learning_performance?: string[];
    }>;
    expect(rows[0].learning_performance).toEqual(["社使用者-表現"]);
  });

  it("merges a live 各小題配置 學習表現 edit over history and keeps an untouched sibling code", async () => {
    const onSubmit = vi.fn();
    const historyRows = [
      { learning_performance: ["社歷史-舊表現"] },
      { learning_performance: ["社兄弟-未觸碰表現"] },
    ];
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          learning_performance: ["社全域-表現"],
          learning_content: ["社全域-內容"],
          sub_question_count: 2,
          subquestion_configs: JSON.stringify(historyRows),
          per_question_params: JSON.stringify([{
            seed: 6382,
            sub_question_count: 2,
            subquestion_configs: JSON.stringify(historyRows),
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    fireEvent.click(firstRow.getByRole("button", { name: "×" }));
    const learningPerformancePicker = firstRow.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(learningPerformancePicker, { target: { value: "社使用者-表現" } });
    fireEvent.mouseDown(firstRow.getByRole("button", { name: /社使用者-表現/ }));

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const perQuestion = JSON.parse(
      requestQuery("social_studies", onSubmit).get("per_question_params")!,
    ) as Array<{ subquestion_configs: string }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs) as Array<{
      learning_performance?: string[];
    }>;
    expect(rows).toEqual([
      { learning_performance: ["社使用者-表現"] },
      { learning_performance: ["社兄弟-未觸碰表現"] },
    ]);
  });

  it("sends a live 各小題配置 學習內容 selection when history has no per-小題 codes", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          learning_performance: ["社全域-表現"],
          learning_content: ["社全域-內容"],
          sub_question_count: 2,
          per_question_params: JSON.stringify([{
            seed: 6383,
            sub_question_count: 2,
            learning_performance: ["社全域-表現"],
            learning_content: ["社全域-內容"],
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const learningContentPicker = firstRow.getByPlaceholderText("搜尋學習內容...");
    fireEvent.change(learningContentPicker, { target: { value: "社使用者-內容" } });
    fireEvent.mouseDown(firstRow.getByRole("button", { name: /社使用者-內容/ }));

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const perQuestion = JSON.parse(
      requestQuery("social_studies", onSubmit).get("per_question_params")!,
    ) as Array<{ subquestion_configs: string }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs) as Array<{
      learning_content?: string[];
    }>;
    expect(rows[0].learning_content).toEqual(["社使用者-內容"]);
  });

  it("merges live 各小題配置 題型、出題指示、圖片生成模式 and 字數限制 over history", async () => {
    const onSubmit = vi.fn();
    const historyRows = [{
      question_type: "社歷史-舊題型",
      instruction: "歷史舊出題指示",
      content_type: "純文字",
      image_generation_mode: "html",
      question_word_limit: 31,
      option_word_limit: 41,
      text_word_limit: 51,
    }];
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          learning_performance: ["社全域-表現"],
          learning_content: ["社全域-內容"],
          sub_question_count: 1,
          subquestion_configs: JSON.stringify(historyRows),
          per_question_params: JSON.stringify([{
            seed: 6384,
            sub_question_count: 1,
            subquestion_configs: JSON.stringify(historyRows),
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const selects = firstRow.getAllByRole("combobox");
    fireEvent.change(selects[0], { target: { value: "社使用者-題型" } });
    fireEvent.change(selects[2], { target: { value: "gpt_image" } });
    fireEvent.change(
      firstRow.getByPlaceholderText("form.confirm_subq_instruction_placeholder"),
      { target: { value: "使用者新的出題指示" } },
    );
    const wordLimits = firstRow.getAllByRole("spinbutton");
    fireEvent.change(wordLimits[0], { target: { value: "303" } });
    fireEvent.change(wordLimits[1], { target: { value: "101" } });
    fireEvent.change(wordLimits[2], { target: { value: "202" } });

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const perQuestion = JSON.parse(
      requestQuery("social_studies", onSubmit).get("per_question_params")!,
    ) as Array<{ subquestion_configs: string }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs) as Array<Record<string, unknown>>;
    expect(rows[0]).toEqual({
      question_type: "社使用者-題型",
      instruction: "使用者新的出題指示",
      content_type: "純文字",
      image_generation_mode: "gpt_image",
      question_word_limit: 101,
      option_word_limit: 202,
      text_word_limit: 303,
    });
  });

  it("sends a live 自然科學 各小題配置 學習表現 edit from a prefilled history row", async () => {
    getSchemasMock.mockResolvedValue(NATURAL_SCHEMA);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        initialParams={{
          grade: 8,
          context: ["個人"],
          sub_context: "健康",
          set_type: "題組題",
          q_type: ["Simple multiple-choice"],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          science_competency: ["探究能力"],
          learning_performance: ["自然全域-表現"],
          learning_content: ["自然全域-內容"],
          sub_question_count: 2,
          per_question_params: JSON.stringify([{
            seed: 6385,
            sub_question_count: 2,
            learning_performance: ["自然全域-表現"],
            learning_content: ["自然全域-內容"],
          }]),
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const learningPerformancePicker = firstRow.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(learningPerformancePicker, { target: { value: "自然使用者-表現" } });
    fireEvent.mouseDown(firstRow.getByRole("button", { name: /自然使用者-表現/ }));

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const perQuestion = JSON.parse(
      requestQuery("natural_sciences", onSubmit).get("per_question_params")!,
    ) as Array<{ subquestion_configs: string }>;
    const rows = JSON.parse(perQuestion[0].subquestion_configs) as Array<{
      learning_performance?: string[];
    }>;
    expect(rows[0].learning_performance).toEqual(["自然使用者-表現"]);
  });

  it("keeps non-prefilled 各小題配置 submission ready for the existing 全域池 auto-draw", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        initialParams={{
          grade: 8,
          context: ["個人"],
          set_type: "題組題",
          q_type: [],
          count: 1,
          content_type: "純文字",
          image_generation_mode: "html",
          subject_filter: ["歷史"],
          learning_performance: ["社全域-表現"],
          learning_content: ["社全域-內容"],
          sub_question_count: 2,
        }}
        onSubmit={onSubmit}
        disabled={false}
      />,
    );

    await screen.findByText("第1小題");
    const firstRow = subquestionRow(1);
    const learningPerformancePicker = firstRow.getByPlaceholderText("搜尋學習表現...");
    fireEvent.change(learningPerformancePicker, { target: { value: "社使用者-表現" } });
    fireEvent.mouseDown(firstRow.getByRole("button", { name: /社使用者-表現/ }));

    fireEvent.submit(screen.getByText("form.btn_generate").closest("form")!);
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const query = requestQuery("social_studies", onSubmit);
    expect(JSON.parse(query.get("subquestion_configs")!)).toEqual([
      { learning_performance: ["社使用者-表現"] },
      {},
    ]);
    expect(JSON.parse(query.get("per_question_params")!)).toEqual([{}]);
  });
});
