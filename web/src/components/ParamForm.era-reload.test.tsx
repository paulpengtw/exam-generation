import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => ({ payload, drawn: [] })),
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";
import { toGenerateParams } from "../utils/toGenerateParams";

const KNOWING = "Knowing–Defining and Describing";
const REASONING = "Reasoning and Applying–Interpret information";

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "公共", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "開放式建構反應題", instruction: "" },
  ],
  認知歷程: [
    { value: KNOWING, instruction: "" },
    { value: REASONING, instruction: "" },
  ],
  內容領域: [
    { value: "Civic Institutions and Systems", instruction: "" },
    { value: "Civic Participation", instruction: "" },
  ],
  題目內容類型: [{ value: "含圖片", instruction: "" }, { value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  數學思考: [],
  學習表現: [],
  學習內容: [],
  digital_only_question_types: [],
};

const RETIRED_SOCIAL_ROWS = [
  {
    question_type: "選擇題",
    instruction: "保留第一小題指示",
    content_type: "含圖片",
    question_word_limit: 21,
    learning_content: ["歷Ka-Ⅳ-1"],
  },
  {
    question_type: "封閉式建構反應題",
    instruction: "保留第二小題指示",
    content_type: "純文字",
    question_word_limit: 22,
    question_style: "PISA風格",
  },
  {
    question_type: "開放式建構反應題",
    instruction: "保留第三小題指示",
    content_type: "含圖片",
  },
];

const PISA_SOCIAL_HISTORY_PARAMS = {
  grade: 9,
  context: ["公共"],
  set_type: "題組題",
  q_type: ["封閉式建構反應題"],
  count: 1,
  skip_verify: true,
  image_generation_mode: "html",
  content_type: "含圖片",
  topic: "清代港口",
  text_word_limit: 240,
  learning_content: ["歷Ka-Ⅳ-1"],
  sub_question_count: 3,
  閱讀歷程: ["擷取訊息"],
  文本形式: "連續文本",
  question_style: ["PISA風格"],
  subquestion_configs: JSON.stringify(RETIRED_SOCIAL_ROWS),
  per_question_params: JSON.stringify([
    {
      seed: 303,
      context: ["公共"],
      set_type: "題組題",
      q_type: [],
      content_type: "含圖片",
      question_style: "PISA風格",
      sub_question_count: 3,
      subquestion_configs: JSON.stringify([
        RETIRED_SOCIAL_ROWS[0],
        { ...RETIRED_SOCIAL_ROWS[1], question_type: "開放式建構反應題" },
        RETIRED_SOCIAL_ROWS[2],
      ]),
    },
  ]),
};

const ICCS_SOCIAL_ROWS = [
  { question_type: "選擇題", cognitive_process: KNOWING },
  {},
  { question_type: "開放式建構反應題", cognitive_process: REASONING },
];

function renderSocial(
  initialParams: Record<string, unknown>,
  onSubmit = vi.fn(),
) {
  render(
    <ParamForm
      subject="social_studies"
      initialParams={initialParams}
      onSubmit={onSubmit}
      disabled={false}
    />,
  );
  return onSubmit;
}

async function submitForm() {
  fireEvent.click(await screen.findByRole("button", { name: "產生" }));
  fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));
}

describe("ParamForm era-aware history reload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "", verify: "", correct: "" },
    });
  });

  it("restores surviving PISA fields, explains every retired value, and submits clean ICCS params", async () => {
    const onSubmit = renderSocial(PISA_SOCIAL_HISTORY_PARAMS);

    expect(await screen.findByDisplayValue("保留第一小題指示")).toBeInTheDocument();
    expect(screen.getByDisplayValue("保留第二小題指示")).toBeInTheDocument();
    expect(screen.getByLabelText("題數")).toHaveValue(1);

    const firstRow = screen.getByText("第1小題").parentElement!;
    const secondRow = screen.getByText("第2小題").parentElement!;
    expect(within(firstRow).getAllByRole("combobox")[0]).toHaveValue("選擇題");
    expect(within(secondRow).getAllByRole("combobox")[0]).toHaveValue("");
    expect(within(secondRow).queryByRole("option", { name: "封閉式建構反應題" })).not.toBeInTheDocument();

    expect(await screen.findByText(
      "以下設定已停用，未帶入：閱讀歷程（擷取訊息）、文本形式（連續文本）、question_style（PISA風格）、題型（封閉式建構反應題）、題型（封閉式建構反應題，第2小題）",
    )).toBeInTheDocument();

    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const submitted = onSubmit.mock.calls[0][0];
    const wire = toGenerateParams("social_studies", submitted);
    const wirePerQuestion = JSON.parse(wire.per_question_params as string) as Record<string, unknown>[];
    const wireRows = JSON.parse(wire.subquestion_configs as string) as Record<string, unknown>[];
    const wireHistoryRows = JSON.parse(wirePerQuestion[0].subquestion_configs as string) as Record<string, unknown>[];

    expect(wire).not.toHaveProperty("閱讀歷程");
    expect(wire).not.toHaveProperty("文本形式");
    expect(wire).not.toHaveProperty("question_style");
    expect(JSON.stringify(wire)).not.toContain("封閉式建構反應題");
    expect(wireRows[0]).toEqual(expect.objectContaining({
      question_type: "選擇題",
      instruction: "保留第一小題指示",
    }));
    expect(wireRows[1]).not.toHaveProperty("question_type");
    expect(wireHistoryRows[1]).toEqual(expect.objectContaining({
      question_type: "開放式建構反應題",
    }));
    expect(wireHistoryRows[1]).not.toHaveProperty("閱讀歷程");
    expect(wireHistoryRows[1]).not.toHaveProperty("文本形式");
    expect(wireHistoryRows[1]).not.toHaveProperty("question_style");
  });

  it("restores ICCS domain, digital surface, and only the cognitive-process pins", async () => {
    const onSubmit = renderSocial({
      grade: 9,
      context: ["公共"],
      set_type: "題組題",
      count: 1,
      content_type: "含圖片",
      content_domain: "Civic Participation",
      target_surface: "數位",
      sub_question_count: 3,
      subquestion_configs: JSON.stringify(ICCS_SOCIAL_ROWS),
    });

    expect(await screen.findByLabelText("內容領域")).toHaveValue("Civic Participation");
    expect(screen.getByLabelText("卷面")).toHaveValue("數位");

    const rows = [1, 2, 3].map((n) => screen.getByText(`第${n}小題`).parentElement!);
    expect(within(rows[0]).getByLabelText("認知歷程")).toHaveValue(KNOWING);
    expect(within(rows[1]).getByLabelText("認知歷程")).toHaveValue("");
    expect(within(rows[2]).getByLabelText("認知歷程")).toHaveValue(REASONING);

    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const submitted = onSubmit.mock.calls[0][0];
    const wire = toGenerateParams("social_studies", submitted);
    const wireRows = JSON.parse(wire.subquestion_configs as string) as Record<string, unknown>[];

    expect(wire).toEqual(expect.objectContaining({
      content_domain: "Civic Participation",
      target_surface: "數位",
    }));
    expect(wireRows[0]).toEqual(expect.objectContaining({ cognitive_process: KNOWING }));
    expect(wireRows[1]).not.toHaveProperty("cognitive_process");
    expect(wireRows[2]).toEqual(expect.objectContaining({ cognitive_process: REASONING }));
  });

  it("defaults an ICCS history entry without target_surface to 紙本 and omits the wire override", async () => {
    const onSubmit = renderSocial({
      grade: 9,
      context: ["公共"],
      set_type: "題組題",
      count: 1,
      content_type: "含圖片",
      content_domain: "Civic Institutions and Systems",
      sub_question_count: 3,
      subquestion_configs: JSON.stringify([{}, {}, {}]),
    });

    expect(await screen.findByLabelText("卷面")).toHaveValue("紙本");
    await submitForm();
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));

    const wire = toGenerateParams("social_studies", onSubmit.mock.calls[0][0]);
    expect(wire).not.toHaveProperty("target_surface");
  });
});
