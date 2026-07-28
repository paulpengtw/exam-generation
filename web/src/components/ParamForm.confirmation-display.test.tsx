import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ getSchemas: getSchemasMock, getAvailableModels: getAvailableModelsMock, planCoreQuestions: vi.fn() }));
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) => selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

const MATH_SCHEMA = {
  學習階段: "第四學習階段", grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }], 題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }], 數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }], 題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }], 學習表現: [], 學習內容: [],
};
const SOCIAL_SCHEMA = {
  ...MATH_SCHEMA,
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
};
const SCIENCE_SCHEMA = {
  ...SOCIAL_SCHEMA,
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
};

async function openConfirmation(subject = "math", initialParams = {}) {
  render(<ParamForm subject={subject} onSubmit={vi.fn()} disabled={false} initialParams={initialParams} />);
  fireEvent.click(await screen.findByRole("button", { name: "產生" }));
  return screen.findByRole("heading", { name: "發送前確認設定" });
}

function confirmationRow(label: string) {
  const term = screen.getByText(label, { selector: "dt" });
  return within(term.parentElement!);
}

describe("ParamForm 發送前確認 display semantics", () => {
  beforeEach(() => {
    vi.clearAllMocks(); window.localStorage.clear(); getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
  });

  it("renders a blank 主題 as 未填寫 instead of （無）", async () => {
    await openConfirmation();
    expect(confirmationRow("主題").getByText("未填寫")).toBeInTheDocument();
    expect(screen.queryByText("（無）")).not.toBeInTheDocument();
  });

  it("labels a blank 情境 as backend-sampled per question", async () => {
    await openConfirmation();
    expect(confirmationRow("情境").getByText("由後端隨機抽取（每題不同）")).toBeInTheDocument();
  });

  it("renders blank 難度 as its resolved medium default", async () => {
    await openConfirmation();
    expect(confirmationRow("難度").getByText("medium")).toBeInTheDocument();
  });

  it("renders supplied passage under 文本 rather than 文本字數限制", async () => {
    await openConfirmation("math", { passage: "共享文本" });
    expect(confirmationRow("文本").getByText("共享文本")).toBeInTheDocument();
  });

  it("renders the top-level 文本字數限制 value", async () => {
    await openConfirmation("math", { text_word_limit: 321 });
    expect(confirmationRow("文本字數限制").getByText("321")).toBeInTheDocument();
  });

  it("renders rows for 情境子類別, 科學能力, 規劃模型, and 出題模型", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({ allowed: ["plan-x", "execute-y"], defaults: { plan: "plan-x", execute: "execute-y" } });
    await openConfirmation("natural_sciences", { sub_context: "健康", science_competency: ["能力一"] });
    expect(screen.getByText("情境子類別", { selector: "dt" })).toBeInTheDocument();
    expect(screen.getByText("科學能力", { selector: "dt" })).toBeInTheDocument();
    expect(screen.getByText("規劃模型", { selector: "dt" })).toBeInTheDocument();
    expect(screen.getByText("出題模型", { selector: "dt" })).toBeInTheDocument();
  });

  it("renders all ten natural-science 各小題配置 fields when unset", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    await openConfirmation("natural_sciences", { sub_question_count: 3, subquestion_configs: [{}, {}, {}] });
    const card = screen.getByText("第 1 小題").closest("li")!;
    expect(within(card).getByText(/題型:.*（隨機）/)).toBeInTheDocument();
    expect(within(card).getByText(/出題指示:.*未填寫/)).toBeInTheDocument();
    expect(within(card).getAllByText(/（沿用文本設定）/)).toHaveLength(2);
    expect(within(card).getAllByText(/不限/)).toHaveLength(3);
    expect(within(card).getByText(/報告等級:.*（隨機）/)).toBeInTheDocument();
    expect(within(card).getByText(/學習表現:.*（沿用全域設定）/)).toBeInTheDocument();
    expect(within(card).getByText(/學習內容:.*（沿用全域設定）/)).toBeInTheDocument();
  });

  it("renders blank-everything confirmation for 數學 without （無）", async () => {
    await openConfirmation("math");
    expect(screen.queryByText("（無）")).not.toBeInTheDocument();
  });

  it("does not render natural-science-only rows for 數學", async () => {
    await openConfirmation("math");
    expect(screen.queryByText("情境子類別", { selector: "dt" })).not.toBeInTheDocument();
    expect(screen.queryByText("科學能力", { selector: "dt" })).not.toBeInTheDocument();
  });

  it("renders blank-everything confirmation for 社會領域 without （無）", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    await openConfirmation("social_studies");
    expect(screen.queryByText("（無）")).not.toBeInTheDocument();
  });

  it("renders blank-everything confirmation for 自然科學 without （無）", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    await openConfirmation("natural_sciences");
    expect(screen.queryByText("（無）")).not.toBeInTheDocument();
  });

  it("does not render a 科目 row for 自然科學", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    await openConfirmation("natural_sciences");
    expect(screen.queryByText("科目", { selector: "dt" })).not.toBeInTheDocument();
  });
});
