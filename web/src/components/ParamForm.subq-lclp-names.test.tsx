/**
 * Issue #318: 確認頁 各小題配置 card shows "code — name" for pre-drawn
 * 學習內容 and 學習表現.
 *
 * TDD Cycles:
 *   1. Red: 小題 card renders a 學習內容 code with its curriculum name → Green
 *   2. Red: same for 學習表現 → Green
 *   3. Red: unknown code renders bare without crashing → Green (regression)
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

// Schema with named LC and LP entries (non-empty instruction fields).
// Includes one LP entry with an empty instruction to test the graceful
// degradation path (same rendering logic as "completely unknown code").
const NS_SCHEMA_WITH_NAMES = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple-multiple-choice", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  question_style: [{ value: "standard", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  學習表現: [
    { value: "tr-IV-1", instruction: "科學探究能力", 科目: "自然科學" },
    { value: "tr-IV-2", instruction: "觀察與問題", 科目: "自然科學" },
    // tr-IV-NONAME: valid code but no instruction → renders as bare code
    { value: "tr-IV-NONAME", instruction: "", 科目: "自然科學" },
  ],
  學習內容: [
    { value: "INc-IV-1", instruction: "物質的組成與性質", 科目: "自然科學" },
    { value: "INc-IV-2", instruction: "自然界的尺度與單位", 科目: "自然科學" },
  ],
};

// Social-studies schema with named LC and LP entries
const SS_SCHEMA_WITH_NAMES = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "開放式建構反應題", instruction: "" },
  ],
  閱讀歷程: [{ value: "擷取訊息", instruction: "" }],
  文本形式: [{ value: "連續文本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: [
    { value: "社1a-Ⅳ-1", instruction: "理解歷史時序", 科目: "社" },
    { value: "社1a-Ⅳ-2", instruction: "解讀史料", 科目: "社" },
  ],
  學習內容: [
    { value: "歷Ka-Ⅳ-1", instruction: "臺灣早期歷史", 科目: "歷史" },
    { value: "歷Ka-Ⅳ-2", instruction: "清代臺灣社會", 科目: "歷史" },
  ],
};

async function openConfirmation(subject: string, initialParams = {}) {
  render(
    <ParamForm
      subject={subject}
      onSubmit={vi.fn()}
      disabled={false}
      initialParams={initialParams}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "產生" }));
  return screen.findByRole("heading", { name: "發送前確認設定" });
}

describe("各小題配置 card: code — name display (issue #318)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(NS_SCHEMA_WITH_NAMES);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  // ------------------------------------------------------------------
  // Cycle 1: 學習內容 code with its curriculum name
  // ------------------------------------------------------------------

  it("renders the curriculum name alongside the 學習內容 code in the 小題 card (natural_sciences)", async () => {
    await openConfirmation("natural_sciences", {
      sub_question_count: 3,
      subquestion_configs: [{ learning_content: ["INc-IV-1"] }, {}, {}],
    });

    // Find the subquestion card
    const cardTitle = await screen.findByText("第 1 小題");
    const card = within(cardTitle.closest("li")!);

    // The code must still appear
    expect(card.getByText("INc-IV-1")).toBeInTheDocument();
    // The curriculum name (instruction) must appear — this is the RED assertion before #318 fix
    expect(card.getByText(/物質的組成與性質/)).toBeInTheDocument();
  });

  it("renders the curriculum name alongside the 學習內容 code in the 小題 card (social_studies)", async () => {
    getSchemasMock.mockResolvedValue(SS_SCHEMA_WITH_NAMES);

    await openConfirmation("social_studies", {
      sub_question_count: 3,
      subquestion_configs: [{ learning_content: ["歷Ka-Ⅳ-1"] }, {}, {}],
    });

    const cardTitle = await screen.findByText("第 1 小題");
    const card = within(cardTitle.closest("li")!);

    expect(card.getByText("歷Ka-Ⅳ-1")).toBeInTheDocument();
    // RED assertion: curriculum name not currently shown
    expect(card.getByText(/臺灣早期歷史/)).toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Cycle 2: 學習表現 code with its curriculum name
  // ------------------------------------------------------------------

  it("renders the curriculum name alongside the 學習表現 code in the 小題 card (natural_sciences)", async () => {
    await openConfirmation("natural_sciences", {
      sub_question_count: 3,
      subquestion_configs: [{ learning_performance: ["tr-IV-1"] }, {}, {}],
    });

    const cardTitle = await screen.findByText("第 1 小題");
    const card = within(cardTitle.closest("li")!);

    expect(card.getByText("tr-IV-1")).toBeInTheDocument();
    // RED assertion: curriculum name not currently shown
    expect(card.getByText(/科學探究能力/)).toBeInTheDocument();
  });

  it("renders the curriculum name alongside the 學習表現 code in the 小題 card (social_studies)", async () => {
    getSchemasMock.mockResolvedValue(SS_SCHEMA_WITH_NAMES);

    await openConfirmation("social_studies", {
      sub_question_count: 3,
      subquestion_configs: [{ learning_performance: ["社1a-Ⅳ-1"] }, {}, {}],
    });

    const cardTitle = await screen.findByText("第 1 小題");
    const card = within(cardTitle.closest("li")!);

    expect(card.getByText("社1a-Ⅳ-1")).toBeInTheDocument();
    // RED assertion: curriculum name not currently shown
    expect(card.getByText(/理解歷史時序/)).toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Cycle 3: Unknown code degrades to bare code (regression assertion)
  // ------------------------------------------------------------------

  it("renders an unknown 學習內容 code as bare code without crashing", async () => {
    await openConfirmation("natural_sciences", {
      sub_question_count: 3,
      subquestion_configs: [{ learning_content: ["UNKNOWN-99-99"] }, {}, {}],
    });

    const cardTitle = await screen.findByText("第 1 小題");
    const card = within(cardTitle.closest("li")!);

    // Bare code must still render
    expect(card.getByText("UNKNOWN-99-99")).toBeInTheDocument();
    // No literal "undefined" or "null" text must appear
    expect(card.queryByText("undefined")).not.toBeInTheDocument();
    expect(card.queryByText("null")).not.toBeInTheDocument();
  });

  it("renders a 學習表現 code that has no instruction as bare code without crashing", async () => {
    // tr-IV-NONAME is in the schema (so it is not filtered out) but has an
    // empty instruction — the same rendering branch as a code absent from the
    // schema entirely (the lookup returns undefined / no instruction).
    await openConfirmation("natural_sciences", {
      sub_question_count: 3,
      subquestion_configs: [{ learning_performance: ["tr-IV-NONAME"] }, {}, {}],
    });

    const cardTitle = await screen.findByText("第 1 小題");
    const card = within(cardTitle.closest("li")!);

    // The code must render as a span
    const codeEl = card.getByText("tr-IV-NONAME");
    expect(codeEl).toBeInTheDocument();
    // No "undefined" or "null" text must appear
    expect(card.queryByText("undefined")).not.toBeInTheDocument();
    expect(card.queryByText("null")).not.toBeInTheDocument();
    // The li containing this code must not have an em-dash sibling span
    // (confirming bare-code rendering for codes with no instruction)
    const codeItem = codeEl.closest("li")!;
    expect(within(codeItem).queryByText(/—/)).not.toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Format consistency: no disc bullets (matches question-level section)
  // ------------------------------------------------------------------

  it("does not use a disc-bulleted list for 學習內容 in the 小題 card", async () => {
    await openConfirmation("natural_sciences", {
      sub_question_count: 3,
      subquestion_configs: [{ learning_content: ["INc-IV-1"] }, {}, {}],
    });

    const cardTitle = await screen.findByText("第 1 小題");
    const card = cardTitle.closest("li")!;

    // The <ul> containing the LC entries must not use list-disc
    const lists = card.querySelectorAll("ul.list-disc");
    // Look specifically for list-disc within the LC/LP section (not at ancestor level)
    const lcLists = Array.from(lists).filter((ul) =>
      ul.textContent?.includes("INc-IV-1"),
    );
    expect(lcLists).toHaveLength(0);
  });
});
