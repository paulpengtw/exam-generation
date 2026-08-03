import { fireEvent, render, screen, within } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import type { Lang } from "../i18n/messages";
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
}));

import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import ParamForm from "./ParamForm";

const LOCALE: Lang = "zh-TW";
const NOW = new Date("2026-07-30T12:00:00.000Z");
const DRAFT_KEY = "exam_form_draft_teacher-summary";

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
  question_style: [{ value: "素養", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

const IDENTIFIABLE_FIELDS: FormFields = {
  grade: 8,
  style: "素養",
  contentType: "純文字",
  customContentType: "",
  context: ["社會"],
  setType: "單一題",
  qType: ["填充題"],
  count: 4,
  coverageMode: "balanced",
  skipVerify: false,
  disableReferenceFewshot: false,
  imageGenerationMode: "html",
  difficulty: "medium",
  subjectFilter: "數與量",
  passage: "這是一段保存的文本。",
  textWordLimit: 120,
  options: ["甲", "乙", "丙", "丁"],
  topic: "臺灣河川治理",
  coreQuestion: "人們如何在防洪與生態之間取得平衡？",
  subContext: "",
  scienceCompetency: [],
  learningPerformance: [],
  learningContent: [],
  subQuestionCount: 3,
  subquestionConfigs: [],
  modelPlan: "",
  modelExecute: "",
  effortPlan: "medium",
  effortExecute: "medium",
};

function signIn(): void {
  useAuthStore.getState().login("token", {
    id: "teacher-summary",
    email: "teacher@example.com",
    created_at: "2026-01-01T00:00:00.000Z",
  });
}

function storeDraft(
  fields: FormFields = IDENTIFIABLE_FIELDS,
  savedAt = new Date(NOW.getTime() - 2 * 24 * 60 * 60 * 1_000).toISOString(),
): void {
  localStorage.setItem(DRAFT_KEY, JSON.stringify({ savedAt, fields }));
}

describe("ParamForm draft summary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    useLangStore.setState({ lang: LOCALE });
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    signIn();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows a two-day-old draft with localized relative time", async () => {
    storeDraft();

    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    const expected = new Intl.RelativeTimeFormat(LOCALE, {
      numeric: "always",
    }).format(-2, "day");
    expect(await screen.findByRole("status")).toHaveTextContent(expected);
  });

  it("leads with typed identifying text before the saved class and question settings", async () => {
    storeDraft();

    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    const prompt = await screen.findByRole("status");
    const summary = within(prompt).getByRole("region", { name: "草稿摘要" });
    expect(
      Array.from(summary.querySelectorAll("dt"), (term) => term.textContent),
    ).toEqual([
      "主題",
      "核心問題",
      "年級",
      "科目",
      "題數",
      "小題數",
      "題型",
      "情境",
      "文本",
    ]);
    expect(summary).toHaveTextContent("臺灣河川治理");
    expect(summary).toHaveTextContent("人們如何在防洪與生態之間取得平衡？");
    expect(summary).toHaveTextContent("8");
    expect(summary).toHaveTextContent("數與量");
    expect(summary).toHaveTextContent("4");
    expect(summary).toHaveTextContent("3");
    expect(summary).toHaveTextContent("填充題");
    expect(summary).toHaveTextContent("社會");
  });

  it("hard-truncates a long pasted passage and constrains the visible excerpt", async () => {
    const longPassage = `辨認草稿的開頭${"甲".repeat(1_000)}不應出現的結尾`;
    storeDraft({ ...IDENTIFIABLE_FIELDS, passage: longPassage });

    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    const summary = within(await screen.findByRole("status")).getByRole(
      "region",
      { name: "草稿摘要" },
    );
    const excerpt = `${Array.from(longPassage).slice(0, 80).join("")}…`;
    const passageValue = within(summary).getByText(excerpt, { exact: true });
    expect(passageValue).toHaveClass("break-words", "max-h-16", "overflow-hidden");
    expect(summary).not.toHaveTextContent("不應出現的結尾");
  });

  it("renders an explicit localized marker for every unset identifying field", async () => {
    storeDraft({
      ...IDENTIFIABLE_FIELDS,
      grade: "",
      context: [],
      qType: [],
      subjectFilter: "",
      passage: "",
      topic: "",
      coreQuestion: null,
      subQuestionCount: "",
    });

    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    const summary = within(await screen.findByRole("status")).getByRole(
      "region",
      { name: "草稿摘要" },
    );
    for (const label of ["主題", "核心問題", "年級", "科目", "題型", "情境"]) {
      const row = within(summary).getByText(label, { selector: "dt" }).parentElement;
      expect(within(row!).getByText("未填寫")).toBeInTheDocument();
    }
  });

  it("keeps every remaining saved setting in a collapsed expander until opened", async () => {
    storeDraft();

    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    const prompt = await screen.findByRole("status");
    const toggle = within(prompt).getByText("完整設定", { selector: "summary" });
    const details = toggle.closest("details");
    expect(details).not.toHaveAttribute("open");

    fireEvent.click(toggle);

    expect(details).toHaveAttribute("open");
    expect(
      Array.from(details!.querySelectorAll("dt"), (term) => term.textContent),
    ).toEqual([
      "題目風格",
      "題目內容類型",
      "自訂題目內容類型",
      "題型種類",
      "出題模式",
      "略過驗證",
      "關閉參考範例",
      "圖片產生方式",
      "難度",
      "文本字數限制",
      "選項",
      "情境子類別",
      "科學能力",
      "學習表現",
      "學習內容",
      "各小題配置",
      "規劃模型",
      "出題模型",
    ]);
    expect(details).toHaveTextContent("素養");
    expect(details).toHaveTextContent("純文字");
    expect(details).toHaveTextContent("單一題");
    expect(details).toHaveTextContent("120");
    expect(details).toHaveTextContent("甲、乙、丙、丁");

    const customContentTypeRow = within(details!).getByText(
      "自訂題目內容類型",
      { selector: "dt" },
    ).parentElement;
    expect(within(customContentTypeRow!).getByText("未填寫")).toBeInTheDocument();
  });

  it("renders saved per-subquestion settings as labelled cards in the restore banner", async () => {
    const subquestionConfigs = [
      { question_type: "選擇題", learning_performance: ["n-IV-1"] },
      {},
    ];
    storeDraft({ ...IDENTIFIABLE_FIELDS, subquestionConfigs });

    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    const banner = await screen.findByRole("status");
    within(banner).getByRole("region", { name: "草稿摘要" });
    fireEvent.click(
      within(banner).getByText("完整設定", { selector: "summary" }),
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
      expect(banner).toHaveTextContent(label);
    }

    expect(banner).not.toHaveTextContent('"question_type"');
    expect(banner).not.toHaveTextContent(JSON.stringify(subquestionConfigs));

    const secondCard = within(banner)
      .getByRole("heading", { name: "第 2 小題" })
      .closest("li");
    expect(secondCard).not.toBeNull();
    expect(secondCard).toHaveTextContent("（隨機）");
    expect(secondCard).toHaveTextContent("（沿用文本設定）");
    expect(secondCard).toHaveTextContent("不限");
    expect(secondCard).toHaveTextContent("學習內容: （沿用全域設定）");
    expect(secondCard).toHaveTextContent("學習表現: （沿用全域設定）");
  });

  it("warns that starting over permanently discards the draft", async () => {
    storeDraft();

    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    expect(
      within(await screen.findByRole("status")).getByText(
        "捨棄草稿是永久的，且無法復原。",
      ),
    ).toBeVisible();
  });
});
