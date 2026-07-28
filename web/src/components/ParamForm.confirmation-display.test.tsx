import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
const MATH_SCHEMA_WITH_CURRICULUM = {
  ...MATH_SCHEMA,
  學習表現: [
    { value: "n-IV-1", instruction: "理解數與量", 科目: "n" },
    { value: "n-IV-2", instruction: "運用數與量", 科目: "n" },
  ],
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
    planCoreQuestionsMock.mockResolvedValue({ candidates: ["候選核心問題"] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  it("requests 提示詞預覽 once with the exact payload that 確定發送 submits", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ count: 1, seed: 700, topic: "分數", core_question: "如何比較分數？" }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));
    const previewPayload = previewGenerateMock.mock.calls[0][0];
    expect(previewPayload).toEqual(expect.objectContaining({
      subject: "math",
      grade: 7,
      count: 1,
      topic: "分數",
      core_question: "如何比較分數？",
    }));
    expect(JSON.parse(previewPayload.per_question_params)).toEqual([
      expect.objectContaining({
        subject: "math",
        seed: 700,
        topic: "分數",
        core_question: "如何比較分數？",
      }),
    ]);

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(previewPayload.per_question_params).toBe(onSubmit.mock.calls[0][0].per_question_params);
  });

  it("renders the returned system and user prompts as literal text in the matching question", async () => {
    previewGenerateMock.mockResolvedValue({
      prompts: [{
        index: 0,
        system_prompt: "# 系統提示\n請保留 **星號**",
        user_prompt: "## 使用者提示\n題目：1 < 2",
      }],
    });

    await openConfirmation("math", { core_question: "已提供的核心問題" });

    const question = screen.getByRole("region", { name: "第1題" });
    await within(question).findByText("文本生成器將送出的提示詞");
    const prompts = question.querySelectorAll("pre");
    expect(prompts[0]).toHaveTextContent("# 系統提示\n請保留 **星號**", { normalizeWhitespace: false });
    expect(prompts[1]).toHaveTextContent("## 使用者提示\n題目：1 < 2", { normalizeWhitespace: false });
  });

  it("keeps 將送出的提示詞 collapsed by default and expands it on interaction", async () => {
    previewGenerateMock.mockResolvedValue({
      prompts: [{ index: 0, system_prompt: "系統內容", user_prompt: "使用者內容" }],
    });
    await openConfirmation("math", { core_question: "已提供的核心問題" });

    const toggle = await screen.findByText("文本生成器將送出的提示詞", { selector: "summary" });
    const details = toggle.closest("details");
    expect(details).not.toHaveAttribute("open");

    fireEvent.click(toggle);
    expect(details).toHaveAttribute("open");
  });

  it("matches each 社會領域 文本生成器 preview to its question by index", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    previewGenerateMock.mockResolvedValue({
      prompts: [
        { index: 0, system_prompt: "第一題文本系統", user_prompt: "第一題文本使用者" },
        { index: 0, subquestion_index: 0, system_prompt: "第一題小題一系統", user_prompt: "第一題小題一使用者" },
        { index: 0, subquestion_index: 1, system_prompt: "第一題小題二系統", user_prompt: "第一題小題二使用者" },
        { index: 0, subquestion_index: 2, system_prompt: "第一題小題三系統", user_prompt: "第一題小題三使用者" },
        { index: 1, system_prompt: "第二題文本系統", user_prompt: "第二題文本使用者" },
        { index: 1, subquestion_index: 0, system_prompt: "第二題小題一系統", user_prompt: "第二題小題一使用者" },
        { index: 1, subquestion_index: 1, system_prompt: "第二題小題二系統", user_prompt: "第二題小題二使用者" },
        { index: 1, subquestion_index: 2, system_prompt: "第二題小題三系統", user_prompt: "第二題小題三使用者" },
      ],
    });
    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
    });

    const first = screen.getByRole("region", { name: "第1題" });
    const second = screen.getByRole("region", { name: "第2題" });
    await within(first).findByText("第一題文本系統");
    expect(within(first).queryByText("第二題文本系統")).not.toBeInTheDocument();
    expect(within(second).getByText("第二題文本系統")).toBeInTheDocument();
    expect(within(second).queryByText("第一題文本系統")).not.toBeInTheDocument();
  });

  it("renders each 子題產生器 preview in subquestion_index order inside its question", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    previewGenerateMock.mockResolvedValue({
      prompts: [
        { index: 0, system_prompt: "文本系統", user_prompt: "文本使用者" },
        { index: 0, subquestion_index: 2, system_prompt: "小題三系統", user_prompt: "小題三使用者" },
        { index: 0, subquestion_index: 0, system_prompt: "小題一系統", user_prompt: "小題一使用者" },
        { index: 0, subquestion_index: 1, system_prompt: "小題二系統", user_prompt: "小題二使用者" },
      ],
    });
    await openConfirmation("social_studies", {
      sub_question_count: 3,
      core_question: "已提供的核心問題",
    });

    const question = screen.getByRole("region", { name: "第1題" });
    const summaries = await within(question).findAllByText(/子題產生器.*第[123]小題/, {
      selector: "summary",
    });
    expect(summaries.map((summary) => summary.textContent)).toEqual([
      "子題產生器（第1小題）將送出的提示詞",
      "子題產生器（第2小題）將送出的提示詞",
      "子題產生器（第3小題）將送出的提示詞",
    ]);
    expect(within(question).getByText("小題一系統")).toBeInTheDocument();
    expect(within(question).getByText("小題二系統")).toBeInTheDocument();
    expect(within(question).getByText("小題三系統")).toBeInTheDocument();
    for (const summary of summaries) {
      expect(summary.closest("details")).not.toHaveAttribute("open");
    }
  });

  it("renders 子題產生器 placeholder tokens verbatim", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const placeholders = [
      "{{核心問題：由前一階段產生}}",
      "{{文本：由前一階段產生}}",
      "{{取材來源：由前一階段產生}}",
      "{{子題 plan：由前一階段產生}}",
    ];
    previewGenerateMock.mockResolvedValue({
      prompts: [
        { index: 0, system_prompt: "文本系統", user_prompt: "文本使用者" },
        {
          index: 0,
          subquestion_index: 0,
          system_prompt: placeholders.slice(0, 2).join("\n"),
          user_prompt: placeholders.slice(2).join("\n"),
        },
      ],
    });
    await openConfirmation("social_studies", {
      sub_question_count: 3,
      core_question: "已提供的核心問題",
    });

    const question = screen.getByRole("region", { name: "第1題" });
    for (const placeholder of placeholders) {
      expect(await within(question).findByText(placeholder, { exact: false })).toBeInTheDocument();
    }
  });

  it("renders only the 文本生成器 preview for 數學", async () => {
    previewGenerateMock.mockResolvedValue({
      prompts: [
        { index: 0, system_prompt: "數學系統", user_prompt: "數學使用者" },
      ],
    });
    await openConfirmation("math", { core_question: "已提供的核心問題" });

    const question = screen.getByRole("region", { name: "第1題" });
    expect(await within(question).findByText("數學系統")).toBeInTheDocument();
    expect(within(question).getByText("文本生成器將送出的提示詞")).toBeInTheDocument();
    expect(within(question).queryByText(/子題產生器/)).not.toBeInTheDocument();
  });

  it("keeps 發送前確認 usable and 確定發送 working when 提示詞預覽 returns malformed data", async () => {
    previewGenerateMock.mockResolvedValue({ prompts: null });
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ core_question: "已提供的核心問題" }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));

    expect(screen.getByRole("heading", { name: "發送前確認設定" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "第1題" })).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "確定發送" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not re-fire 提示詞預覽 when the same confirmation screen re-renders", async () => {
    const onSubmit = vi.fn();
    const initialParams = { core_question: "已提供的核心問題" };
    const { rerender } = render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={initialParams}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));

    rerender(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled
        initialParams={initialParams}
      />,
    );

    expect(screen.getByRole("heading", { name: "發送前確認設定" })).toBeInTheDocument();
    expect(previewGenerateMock).toHaveBeenCalledTimes(1);
  });

  it("calls the core-question planner once when entering confirmation with 核心問題 blank", async () => {
    await openConfirmation("math", { topic: "分數" });

    await waitFor(() => expect(planCoreQuestionsMock).toHaveBeenCalledTimes(1));
    expect(planCoreQuestionsMock).toHaveBeenCalledWith({
      topic: "分數",
      subject: "math",
      subject_filter: undefined,
      grade: 7,
    });
  });

  it("N=1 displays and submits the same one-element per-question payload", async () => {
    getSchemasMock.mockResolvedValue(MATH_SCHEMA_WITH_CURRICULUM);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ count: 1, learning_performance: ["n-IV-1"] }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    const block = await screen.findByRole("region", { name: "第1題" });
    expect(within(block).getByText("n-IV-1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const payload = onSubmit.mock.calls[0][0];
    const perQuestion = JSON.parse(payload.per_question_params);
    expect(perQuestion).toHaveLength(1);
    expect(perQuestion[0].learning_performance).toEqual(["n-IV-1"]);
  });

  it("resolves, displays, and submits one seed per question", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ count: 2 }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    const displayedSeeds = [1, 2].map((number) => {
      const block = screen.getByRole("region", { name: `第${number}題` });
      const seedTerm = within(block).getByText("種子", { selector: "dt" });
      const seedRow = within(seedTerm.parentElement!);
      expect(seedRow.getByText("預抽")).toHaveClass("text-amber-700");
      return seedRow.getByText(/^\d+$/).textContent;
    });

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const perQuestion = JSON.parse(onSubmit.mock.calls[0][0].per_question_params);
    expect(perQuestion.map((item: { seed: number }) => String(item.seed))).toEqual(displayedSeeds);
  });

  it("derives user-supplied seeds per question and displays the user badge", async () => {
    await openConfirmation("math", { count: 2, seed: 700 });

    [700, 701].forEach((seed, index) => {
      const block = screen.getByRole("region", { name: `第${index + 1}題` });
      const seedTerm = within(block).getByText("種子", { selector: "dt" });
      const seedRow = within(seedTerm.parentElement!);
      expect(seedRow.getByText(String(seed))).toBeInTheDocument();
      expect(seedRow.getByText("使用者選擇")).toHaveClass("text-green-700");
    });
  });

  it("N>1 renders one labelled block per question", async () => {
    await openConfirmation("math", { count: 3 });

    expect(screen.getByRole("region", { name: "第1題" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "第2題" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "第3題" })).toBeInTheDocument();
  });

  it.each([
    ["math", MATH_SCHEMA],
    ["social_studies", SOCIAL_SCHEMA],
    ["natural_sciences", SCIENCE_SCHEMA],
  ])("%s sends one resolved object per requested question", async (subject, schema) => {
    getSchemasMock.mockResolvedValue(schema);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject={subject}
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ count: 2 }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));

    const perQuestion = JSON.parse(onSubmit.mock.calls[0][0].per_question_params);
    expect(perQuestion).toHaveLength(2);
    expect(perQuestion.map((item: { subject: string }) => item.subject))
      .toEqual([subject, subject]);
  });

  it("copies a user-chosen parameter across the batch and badges it green", async () => {
    getSchemasMock.mockResolvedValue(MATH_SCHEMA_WITH_CURRICULUM);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ count: 2, learning_performance: ["n-IV-1"] }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    for (const name of ["第1題", "第2題"]) {
      const row = within(screen.getByRole("region", { name }))
        .getByText("學習表現")
        .parentElement!;
      expect(within(row).getByText("使用者選擇")).toHaveClass("text-green-700");
    }
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const perQuestion = JSON.parse(onSubmit.mock.calls[0][0].per_question_params);
    expect(perQuestion.map((item: { learning_performance: string[] }) => item.learning_performance))
      .toEqual([["n-IV-1"], ["n-IV-1"]]);
  });

  it("draws an unchosen parameter independently and badges each concrete value amber", async () => {
    getSchemasMock.mockResolvedValue(MATH_SCHEMA_WITH_CURRICULUM);
    const random = vi.spyOn(Math, "random");
    [0, 0, 0, 0, 0, 0.9, 0].forEach((value) => random.mockReturnValueOnce(value));
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ count: 2 }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    for (const name of ["第1題", "第2題"]) {
      const row = within(screen.getByRole("region", { name }))
        .getByText("學習表現")
        .parentElement!;
      expect(within(row).getByText("隨機抽取")).toHaveClass("text-amber-700");
      expect(within(row).queryByText("由後端隨機抽取（每題不同）")).not.toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const perQuestion = JSON.parse(onSubmit.mock.calls[0][0].per_question_params);
    expect(perQuestion[0].learning_performance).not.toEqual(perQuestion[1].learning_performance);
    random.mockRestore();
  });

  it("auto-selects a planned core question and renders it with the 預先產生 badge", async () => {
    await openConfirmation("math", { topic: "分數" });

    await screen.findByText("候選核心問題");
    const row = confirmationRow("核心問題");
    expect(row.getByText("候選核心問題")).toBeInTheDocument();
    expect(row.getByText("預先產生")).toHaveClass("text-amber-700");
  });

  it("submits the pre-generated value as core_question", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} initialParams={{ topic: "分數" }} />);
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByText("候選核心問題");

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ core_question: "候選核心問題" }));
  });

  it("preserves a user-supplied core question without calling the planner", async () => {
    await openConfirmation("math", { topic: "分數", core_question: "使用者的核心問題" });

    expect(confirmationRow("核心問題").getByText("使用者的核心問題")).toBeInTheDocument();
    expect(confirmationRow("核心問題").queryByText("預先產生")).not.toBeInTheDocument();
    expect(planCoreQuestionsMock).not.toHaveBeenCalled();
  });

  it("keeps confirmation usable and defers 核心問題 when planning fails", async () => {
    planCoreQuestionsMock.mockRejectedValue(new Error("planner unavailable"));
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} initialParams={{ topic: "分數" }} />);
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    await waitFor(() => expect(planCoreQuestionsMock).toHaveBeenCalled());
    const confirm = screen.getByRole("button", { name: "確定發送" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ core_question: undefined }));
  });

  it("does not re-fire the planner when the same confirmation screen re-renders", async () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <ParamForm subject="math" onSubmit={onSubmit} disabled={false} initialParams={{ topic: "分數" }} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByText("候選核心問題");

    rerender(<ParamForm subject="math" onSubmit={onSubmit} disabled initialParams={{ topic: "分數" }} />);

    expect(screen.getByRole("heading", { name: "發送前確認設定" })).toBeInTheDocument();
    expect(planCoreQuestionsMock).toHaveBeenCalledTimes(1);
  });

  it("renders a blank 主題 as 未填寫 instead of （無）", async () => {
    await openConfirmation();
    expect(screen.queryByText("主題", { selector: "dt" })).not.toBeInTheDocument();
    expect(screen.queryByText("（無）")).not.toBeInTheDocument();
  });

  it("renders a blank 情境 as a concrete per-question draw", async () => {
    await openConfirmation();
    const row = confirmationRow("情境");
    expect(row.getByText("個人")).toBeInTheDocument();
    expect(row.getByText("隨機抽取")).toHaveClass("text-amber-700");
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
    const row = confirmationRow("各小題配置");
    expect(row.getByText("[{},{},{}]")).toBeInTheDocument();
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
