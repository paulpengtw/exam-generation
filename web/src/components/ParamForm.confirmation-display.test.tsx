import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
  resolveGenerate: resolveGenerateMock,
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
    { value: "n-IV-1", instruction: "理解數與量", 科目: "n", admitted_by: { 科目: ["數與量", "跨領域"] } },
    { value: "n-IV-2", instruction: "運用數與量", 科目: "n", admitted_by: { 科目: ["數與量", "跨領域"] } },
  ],
  學習內容: [
    { value: "N-7-1", instruction: "負數與數線", 科目: "N", admitted_by: { 科目: ["數與量", "跨領域"] } },
    { value: "N-7-2", instruction: "質因數分解", 科目: "N", admitted_by: { 科目: ["數與量", "跨領域"] } },
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
const SCIENCE_SCHEMA_WITH_CURRICULUM = {
  ...SCIENCE_SCHEMA,
  學習表現: MATH_SCHEMA_WITH_CURRICULUM.學習表現,
  學習內容: MATH_SCHEMA_WITH_CURRICULUM.學習內容,
};

function legacyConfirmationResolve(payload: Record<string, unknown>) {
  const rawRows = payload.per_question_params;
  const sourceRows = typeof rawRows === "string"
    ? JSON.parse(rawRows) as Record<string, unknown>[]
    : Array.isArray(rawRows)
      ? rawRows as Record<string, unknown>[]
      : [];
  const base = Object.fromEntries(
    Object.entries(payload).filter(([key]) => ![
      "subject", "count", "per_question_params", "drawn", "redraws",
    ].includes(key)),
  );
  const subject = payload.subject;
  const generatedSeed = typeof payload.seed !== "number";
  const seed = generatedSeed ? 900 : payload.seed as number;
  const resolvedRows = sourceRows.map((sourceRow, index) => {
    const row = { ...base, ...sourceRow };
    delete row.subject;
    delete row.count;
    delete row.per_question_params;
    delete row.drawn;
    delete row.redraws;
    if (sourceRow.seed === undefined || sourceRow.seed === null) row.seed = seed + index;
    if (row.context === undefined || (Array.isArray(row.context) && row.context.length === 0)) {
      row.context = [subject === "natural_sciences" ? "Personal" : "個人"];
    }
    if (row.subquestion_configs === undefined && payload.subquestion_configs !== undefined) {
      row.subquestion_configs = payload.subquestion_configs;
    }
    return row;
  });
  const drawn = sourceRows.flatMap((sourceRow, index) => {
    const paths: string[] = [];
    if (generatedSeed && (sourceRow.seed === undefined || sourceRow.seed === null)) {
      paths.push(`per_question_params[${index}].seed`);
    }
    if (sourceRow.context === undefined || (Array.isArray(sourceRow.context) && sourceRow.context.length === 0)) {
      paths.push(`per_question_params[${index}].情境`);
    }
    const rawConfigs = resolvedRows[index].subquestion_configs;
    const configs = typeof rawConfigs === "string"
      ? JSON.parse(rawConfigs) as Record<string, unknown>[]
      : Array.isArray(rawConfigs) ? rawConfigs as Record<string, unknown>[] : [];
    configs.forEach((config, subquestionIndex) => {
      if ((subject === "social_studies" || subject === "natural_sciences") && !config.question_type) {
        paths.push(`per_question_params[${index}].subquestion_configs[${subquestionIndex}].question_type`);
      }
      if (subject === "natural_sciences" && !config.reporting_scale) {
        paths.push(`per_question_params[${index}].subquestion_configs[${subquestionIndex}].reporting_scale`);
      }
    });
    return paths;
  });
  return {
    payload: {
      ...payload,
      ...(generatedSeed ? { seed } : {}),
      per_question_params: JSON.stringify(resolvedRows),
    },
    drawn: [...(generatedSeed ? ["seed"] : []), ...drawn],
  };
}

async function openConfirmation(subject = "math", initialParams = {}, onSubmit = vi.fn()) {
  render(<ParamForm subject={subject} onSubmit={onSubmit} disabled={false} initialParams={initialParams} />);
  fireEvent.click(await screen.findByRole("button", { name: "產生" }));
  return screen.findByRole("heading", { name: "發送前確認設定" });
}

function confirmationRow(label: string) {
  const term = screen.getByText(label, { selector: "dt" });
  return within(term.parentElement!);
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("ParamForm 發送前確認 display semantics", () => {
  beforeEach(() => {
    vi.clearAllMocks(); window.localStorage.clear(); getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
    planCoreQuestionsMock.mockResolvedValue({ candidates: ["候選核心問題"] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
    resolveGenerateMock.mockReset();
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) =>
      legacyConfirmationResolve(payload));
  });

  it("resolves blank 學習內容/學習表現 before showing 發送前確認", async () => {
    const onSubmit = vi.fn();
    getSchemasMock.mockResolvedValue({
      ...MATH_SCHEMA,
      學習內容: [{
        value: "RESOLVED-LC",
        instruction: "resolver content",
        admitted_by: { 科目: ["數與量"] },
      }],
      學習表現: [{
        value: "RESOLVED-LP",
        instruction: "resolver performance",
        admitted_by: { 科目: ["數與量"] },
      }],
    });
    const resolvedPayload = {
      subject: "math",
      grade: 7,
      count: 1,
      learning_content: ["RESOLVED-LC"],
      learning_performance: ["RESOLVED-LP"],
      per_question_params: JSON.stringify([{
        grade: 7,
        seed: 701,
        learning_content: ["RESOLVED-LC"],
        learning_performance: ["RESOLVED-LP"],
      }]),
    };
    resolveGenerateMock.mockResolvedValueOnce({
      payload: resolvedPayload,
      drawn: [
        "learning_content",
        "learning_performance",
        "per_question_params[0].learning_content",
        "per_question_params[0].learning_performance",
      ],
    });

    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ core_question: "固定核心問題" }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(1));
    expect(screen.getByText("RESOLVED-LC")).toBeInTheDocument();
    expect(screen.getByText("RESOLVED-LP")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      drawn: [
        "learning_content",
        "learning_performance",
        "per_question_params[0].learning_content",
        "per_question_params[0].learning_performance",
      ],
      per_question_params: resolvedPayload.per_question_params,
    }));
  });

  it("keeps resolver batch subquestion arrays in the generation wire shape", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA_WITH_CURRICULUM);
    const onSubmit = vi.fn();
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "natural_sciences",
        grade: 7,
        count: 1,
        sub_question_count: 3,
        per_question_params: [{
          seed: 701,
          subquestion_configs: [
            {
              question_type: "選擇題",
              learning_content: ["N-7-1"],
              learning_performance: ["n-IV-1"],
            },
          ],
        }],
      },
      drawn: [
        "per_question_params[0].subquestion_configs[0].learning_content",
        "per_question_params[0].subquestion_configs[0].learning_performance",
      ],
    });

    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ count: 1, sub_question_count: 3, core_question: "固定核心問題" }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByText("N-7-1");
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const submittedRows = JSON.parse(onSubmit.mock.calls[0][0].per_question_params) as Array<{
      subquestion_configs: string;
    }>;
    expect(typeof submittedRows[0].subquestion_configs).toBe("string");
    expect(JSON.parse(submittedRows[0].subquestion_configs)[0]).toEqual({
      question_type: "選擇題",
      learning_content: ["N-7-1"],
      learning_performance: ["n-IV-1"],
    });
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
    const previewPerQuestion = JSON.parse(previewPayload.per_question_params);
    expect(previewPerQuestion).toEqual([
      expect.objectContaining({
        seed: 700,
        topic: "分數",
        core_question: "如何比較分數？",
      }),
    ]);
    expect(previewPerQuestion[0]).not.toHaveProperty("subject");

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

  it("shows the selected core-question callback setting on 發送前確認", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ core_question: "已提供的核心問題" }}
      />,
    );

    const checkbox = await screen.findByRole("checkbox", {
      name: "末小題回扣核心問題",
    });
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "產生" }));

    const row = await screen.findByText("末小題回扣核心問題", { selector: "dt" });
    expect(within(row.parentElement!).getByText("否")).toBeInTheDocument();
  });

  it("uses the toggled core-question callback state in 提示詞預覽", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    previewGenerateMock.mockImplementation(async (params: { core_question_callback?: boolean }) => ({
      prompts: [{
        index: 0,
        system_prompt: "系統提示",
        user_prompt: params.core_question_callback ? "包含回扣核心問題" : "不包含回扣核心問題",
      }],
    }));
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ core_question: "已提供的核心問題" }}
      />,
    );

    const checkbox = await screen.findByRole("checkbox", {
      name: "末小題回扣核心問題",
    });
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "產生" }));

    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));
    expect(previewGenerateMock.mock.calls[0][0].core_question_callback).toBe(false);
    expect(await screen.findByText("不包含回扣核心問題")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "末小題回扣核心問題" }));
    fireEvent.click(screen.getByRole("button", { name: "產生" }));

    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2));
    expect(previewGenerateMock.mock.calls[1][0].core_question_callback).toBe(true);
    expect(await screen.findByText("包含回扣核心問題")).toBeInTheDocument();
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

  it("ignores a stale 提示詞預覽 response after returning and submitting again", async () => {
    const first = deferred<{ prompts: { index: number; system_prompt: string; user_prompt: string }[] }>();
    const second = deferred<{ prompts: { index: number; system_prompt: string; user_prompt: string }[] }>();
    previewGenerateMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(
      <ParamForm
        subject="math"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ core_question: "已提供的核心問題" }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));
    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(2));

    await act(async () => second.resolve({
      prompts: [{ index: 0, system_prompt: "最新系統提示", user_prompt: "最新使用者提示" }],
    }));
    expect(await screen.findByText("最新系統提示")).toBeInTheDocument();

    await act(async () => first.resolve({
      prompts: [{ index: 0, system_prompt: "過期系統提示", user_prompt: "過期使用者提示" }],
    }));
    expect(screen.queryByText("過期系統提示")).not.toBeInTheDocument();
    expect(screen.getByText("最新系統提示")).toBeInTheDocument();
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

    await screen.findByRole("region", { name: "第1題" });
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

  it("shows no warning and returns to the form when there is no 確認頁修改", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);

    await openConfirmation("social_studies", {
      count: 1,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [
        { instruction: "原始小題指示" },
        {},
        {},
      ],
    });

    expect(
      screen.queryByText("返回表單會捨棄您在確認頁所做的修改。"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));

    expect(screen.getByRole("button", { name: "產生" })).toBeInTheDocument();
  });

  it("shows an inline informational warning after a 確認頁修改 without blocking 返回修改", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);

    await openConfirmation("social_studies", {
      count: 1,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    });

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    fireEvent.change(firstQuestion.getAllByLabelText("出題指示")[0], {
      target: { value: "確認頁修改後的出題指示" },
    });

    const backButton = screen.getByRole("button", { name: "返回修改" });
    const warning = screen.getByText("返回表單會捨棄您在確認頁所做的修改。");
    expect(backButton.parentElement).toContainElement(warning);
    expect(backButton).toBeEnabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("discards 確認頁修改 and restores the original shared 各小題配置 on 返回修改", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const originalConfigs = [
      { instruction: "原始第一小題指示" },
      { instruction: "原始第二小題指示" },
      { instruction: "原始第三小題指示" },
    ];

    await openConfirmation("social_studies", {
      count: 1,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: originalConfigs,
    });

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    const firstInstruction = firstQuestion.getAllByLabelText("出題指示")[0];
    fireEvent.change(firstInstruction, {
      target: { value: "捨棄的確認頁修改" },
    });
    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));

    expect(screen.getByRole("button", { name: "產生" })).toBeInTheDocument();
    expect(screen.getAllByPlaceholderText("例如：請聚焦在資料判讀與因果推論")[0])
      .toHaveValue(originalConfigs[0].instruction);
    expect(screen.getAllByPlaceholderText("例如：請聚焦在資料判讀與因果推論")[0])
      .not.toHaveValue("捨棄的確認頁修改");
  });

  it("keeps confirmation instruction edits isolated per 題組 and leaves the form unchanged on 返回修改", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const originalConfigs = [
      {
        question_type: "選擇題",
        instruction: "原始小題指示一",
        text_word_limit: 11,
        question_word_limit: 22,
        option_word_limit: 33,
        content_type: "純文字",
        image_generation_mode: "html" as const,
      },
      {
        question_type: "選擇題",
        instruction: "原始小題指示二",
        text_word_limit: 44,
        question_word_limit: 55,
        option_word_limit: 66,
        content_type: "純文字",
        image_generation_mode: "gpt_image" as const,
      },
      {
        question_type: "選擇題",
        instruction: "原始小題指示三",
        text_word_limit: 77,
        question_word_limit: 88,
        option_word_limit: 99,
        content_type: "純文字",
        image_generation_mode: "html" as const,
      },
    ];

    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: originalConfigs,
    });

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    const secondQuestion = within(screen.getByRole("region", { name: "第2題" }));
    const firstInstruction = firstQuestion.getAllByRole("textbox")[0];
    const secondInstruction = secondQuestion.getAllByRole("textbox")[0];

    expect(firstInstruction).toHaveValue("原始小題指示一");
    expect(secondInstruction).toHaveValue("原始小題指示一");
    fireEvent.change(firstInstruction, { target: { value: "第一題組修改後" } });

    expect(firstInstruction).toHaveValue("第一題組修改後");
    expect(secondInstruction).toHaveValue("原始小題指示一");
    // Each card now has 3 textboxes: instruction(0), LC picker(1), LP picker(2).
    // Card 1's instruction is at index 3 (= 0 + 3 cards-worth).
    expect(firstQuestion.getAllByRole("textbox")[3]).toHaveValue("原始小題指示二");

    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));

    expect(screen.getByRole("button", { name: "產生" })).toBeInTheDocument();
    expect(screen.getAllByPlaceholderText("例如：請聚焦在資料判讀與因果推論")[0])
      .toHaveValue("原始小題指示一");
  });

  it("renders one inline labelled instruction textarea in every confirmation card without an edit toggle", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);

    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    });

    for (const questionNumber of [1, 2]) {
      const question = within(screen.getByRole("region", { name: `第${questionNumber}題` }));
      const cards = question.getAllByRole("listitem");
      expect(cards).toHaveLength(3);
      cards.forEach((card) => {
        expect(within(card).getByLabelText("出題指示")).toBeInTheDocument();
      });
      expect(question.queryByRole("button", { name: /編輯|edit/i })).not.toBeInTheDocument();
    }
  });

  it("renders a schema-backed 題型 select in every confirmation card", async () => {
    getSchemasMock.mockResolvedValue({
      ...SOCIAL_SCHEMA,
      題型: [
        { value: "選擇題", instruction: "" },
        { value: "開放式建構反應題", instruction: "" },
        { value: "schema追加題型", instruction: "" },
      ],
    });

    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    });

    for (const questionNumber of [1, 2]) {
      const question = within(screen.getByRole("region", { name: `第${questionNumber}題` }));
      const cards = question.getAllByRole("listitem");
      expect(cards).toHaveLength(3);
      cards.forEach((card) => {
        const select = within(card).getByLabelText("題型");
        expect(Array.from(select.querySelectorAll("option"), (option) => option.value)).toEqual([
          "",
          "選擇題",
          "開放式建構反應題",
          "schema追加題型",
        ]);
      });
    }
  });

  it("renders shared content type and image mode selects in every confirmation card", async () => {
    getSchemasMock.mockResolvedValue({
      ...SOCIAL_SCHEMA,
      題目內容類型: [
        { value: "純文字", instruction: "" },
        { value: "含圖片", instruction: "" },
        { value: "schema追加內容", instruction: "" },
      ],
    });

    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    });

    const expectedContentTypeOptions = ["", "純文字", "含圖片", "schema追加內容"];
    const expectedImageModeOptions = ["", "html", "gpt_image"];
    for (const questionNumber of [1, 2]) {
      const question = within(screen.getByRole("region", { name: `第${questionNumber}題` }));
      const cards = question.getAllByRole("listitem");
      expect(cards).toHaveLength(3);
      cards.forEach((card) => {
        expect(Array.from(
          within(card).getByLabelText("題目內容類型").querySelectorAll("option"),
          (option) => option.value,
        )).toEqual(expectedContentTypeOptions);
        expect(Array.from(
          within(card).getByLabelText("圖片生成模式").querySelectorAll("option"),
          (option) => option.value,
        )).toEqual(expectedImageModeOptions);
      });
    }

    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));
    expect(screen.getAllByLabelText("題目內容類型")).toHaveLength(3);
    expect(screen.getAllByLabelText("圖片生成模式")).toHaveLength(3);
    expect(Array.from(
      screen.getAllByLabelText("題目內容類型")[0].querySelectorAll("option"),
      (option) => option.value,
    )).toEqual(expectedContentTypeOptions);
    expect(Array.from(
      screen.getAllByLabelText("圖片生成模式")[0].querySelectorAll("option"),
      (option) => option.value,
    )).toEqual(expectedImageModeOptions);
  });

  it("updates only the edited 題型 of one 題組 and flips its badge", async () => {
    getSchemasMock.mockResolvedValue({
      ...SOCIAL_SCHEMA,
      題型: [
        { value: "選擇題", instruction: "" },
        { value: "開放式建構反應題", instruction: "" },
      ],
    });

    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    });

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    const secondQuestion = within(screen.getByRole("region", { name: "第2題" }));
    const firstQuestionType = within(firstQuestion.getAllByRole("listitem")[0]).getByLabelText("題型");
    const firstQuestionSecondType = within(firstQuestion.getAllByRole("listitem")[1]).getByLabelText("題型");
    const secondQuestionType = within(secondQuestion.getAllByRole("listitem")[0]).getByLabelText("題型");

    expect(firstQuestionType).toHaveValue("");
    expect(firstQuestionSecondType).toHaveValue("");
    expect(secondQuestionType).toHaveValue("");
    expect(within(firstQuestionType.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");

    fireEvent.change(firstQuestionType, { target: { value: "開放式建構反應題" } });

    expect(firstQuestionType).toHaveValue("開放式建構反應題");
    expect(within(firstQuestionType.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(within(firstQuestionSecondType.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(within(secondQuestionType.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");
  });

  it("submits the edited 題型 in the correct per-題組 subquestion_configs row", async () => {
    getSchemasMock.mockResolvedValue({
      ...SOCIAL_SCHEMA,
      題型: [
        { value: "選擇題", instruction: "" },
        { value: "開放式建構反應題", instruction: "" },
      ],
    });
    const onSubmit = vi.fn();

    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [
        { question_type: "選擇題", instruction: "固定指示一", question_word_limit: 11 },
        { question_type: "選擇題", instruction: "固定指示二", question_word_limit: 22 },
        { question_type: "選擇題", instruction: "固定指示三", question_word_limit: 33 },
      ],
    }, onSubmit);

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    fireEvent.change(
      within(firstQuestion.getAllByRole("listitem")[0]).getByLabelText("題型"),
      { target: { value: "開放式建構反應題" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const submittedPerQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ subquestion_configs: string }>;
    expect(JSON.parse(submittedPerQuestion[0].subquestion_configs)).toEqual([
      { question_type: "開放式建構反應題", instruction: "固定指示一", question_word_limit: 11 },
      { question_type: "選擇題", instruction: "固定指示二", question_word_limit: 22 },
      { question_type: "選擇題", instruction: "固定指示三", question_word_limit: 33 },
    ]);
    expect(JSON.parse(submittedPerQuestion[1].subquestion_configs)).toEqual([
      { question_type: "選擇題", instruction: "固定指示一", question_word_limit: 11 },
      { question_type: "選擇題", instruction: "固定指示二", question_word_limit: 22 },
      { question_type: "選擇題", instruction: "固定指示三", question_word_limit: 33 },
    ]);
    expect(submittedPerQuestion[0]).not.toHaveProperty("confirmation_edit");
  });

  it("keeps blank image modes inheriting the request-level mode until a 小題 is pinned", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();

    await openConfirmation("social_studies", {
      count: 1,
      image_generation_mode: "gpt_image",
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    }, onSubmit);

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const cards = question.getAllByRole("listitem");
    fireEvent.change(within(cards[0]).getByLabelText("圖片生成模式"), {
      target: { value: "html" },
    });
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const submittedPerQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ image_generation_mode: string; subquestion_configs: string }>;
    expect(submittedPerQuestion[0].image_generation_mode).toBe("gpt_image");
    expect(JSON.parse(submittedPerQuestion[0].subquestion_configs)).toEqual([
      { image_generation_mode: "html" },
      {},
      {},
    ]);
  });

  it("pins content and image edits in the matching 題組 row and flips only those badges", async () => {
    getSchemasMock.mockResolvedValue({
      ...SOCIAL_SCHEMA,
      題目內容類型: [
        { value: "純文字", instruction: "" },
        { value: "含圖片", instruction: "" },
      ],
    });
    const onSubmit = vi.fn();

    await openConfirmation("social_studies", {
      count: 2,
      image_generation_mode: "gpt_image",
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [
        { instruction: "固定指示一", question_word_limit: 11 },
        { content_type: "純文字", image_generation_mode: "html", option_word_limit: 22 },
        { content_type: "含圖片", image_generation_mode: "gpt_image", text_word_limit: 33 },
      ],
    }, onSubmit);

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    const secondQuestion = within(screen.getByRole("region", { name: "第2題" }));
    const firstCard = within(firstQuestion.getAllByRole("listitem")[0]);
    const firstContentType = firstCard.getByLabelText("題目內容類型");
    const firstImageMode = firstCard.getByLabelText("圖片生成模式");

    expect(within(firstContentType.parentElement!).getByText("沿用文本設定")).toHaveClass("text-gray-600");
    expect(within(firstImageMode.parentElement!).getByText("沿用文本設定")).toHaveClass("text-gray-600");
    expect(within(firstImageMode.parentElement!).queryByText("隨機抽取")).toBeNull();
    expect(within(firstQuestion.getAllByRole("listitem")[1]).getByLabelText("題目內容類型")).toHaveValue("純文字");
    expect(within(secondQuestion.getAllByRole("listitem")[0]).getByLabelText("題目內容類型")).toHaveValue("");

    fireEvent.change(firstContentType, { target: { value: "含圖片" } });
    fireEvent.change(firstImageMode, { target: { value: "html" } });

    expect(within(firstContentType.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(within(firstImageMode.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(within(firstQuestion.getAllByRole("listitem")[1]).getByLabelText("圖片生成模式")).toHaveValue("html");
    expect(within(secondQuestion.getAllByRole("listitem")[0]).getByLabelText("圖片生成模式")).toHaveValue("");

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const submittedPerQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ subquestion_configs: string }>;
    expect(JSON.parse(submittedPerQuestion[0].subquestion_configs)).toEqual([
      { instruction: "固定指示一", question_word_limit: 11, content_type: "含圖片", image_generation_mode: "html" },
      { content_type: "純文字", image_generation_mode: "html", option_word_limit: 22 },
      { content_type: "含圖片", image_generation_mode: "gpt_image", text_word_limit: 33 },
    ]);
    expect(JSON.parse(submittedPerQuestion[1].subquestion_configs)).toEqual([
      { instruction: "固定指示一", question_word_limit: 11 },
      { content_type: "純文字", image_generation_mode: "html", option_word_limit: 22 },
      { content_type: "含圖片", image_generation_mode: "gpt_image", text_word_limit: 33 },
    ]);
  });

  it("keeps untouched 小題 configurations unchanged after a 確認頁修改", async () => {
    getSchemasMock.mockResolvedValue({
      ...SOCIAL_SCHEMA,
      題目內容類型: [
        { value: "純文字", instruction: "" },
        { value: "含圖片", instruction: "" },
      ],
    });
    const onSubmit = vi.fn();

    await openConfirmation("social_studies", {
      count: 2,
      image_generation_mode: "html",
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [
        { instruction: "小題一", content_type: "純文字", image_generation_mode: "html", question_word_limit: 11 },
        { instruction: "小題二", content_type: "含圖片", image_generation_mode: "gpt_image", option_word_limit: 22 },
        { instruction: "小題三", content_type: "純文字", image_generation_mode: "html", text_word_limit: 33 },
      ],
    }, onSubmit);

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    fireEvent.change(
      within(firstQuestion.getAllByRole("listitem")[0]).getByLabelText("題目內容類型"),
      { target: { value: "含圖片" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const submittedPerQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ subquestion_configs: string }>;
    const untouchedRows = [
      { instruction: "小題二", content_type: "含圖片", image_generation_mode: "gpt_image", option_word_limit: 22 },
      { instruction: "小題三", content_type: "純文字", image_generation_mode: "html", text_word_limit: 33 },
    ];
    expect(JSON.parse(submittedPerQuestion[0].subquestion_configs)).toEqual([
      { instruction: "小題一", content_type: "含圖片", image_generation_mode: "html", question_word_limit: 11 },
      ...untouchedRows,
    ]);
    expect(JSON.parse(submittedPerQuestion[1].subquestion_configs)).toEqual([
      { instruction: "小題一", content_type: "純文字", image_generation_mode: "html", question_word_limit: 11 },
      ...untouchedRows,
    ]);
  });

  it("keeps untouched 題型 values and badges after a 確認頁修改", async () => {
    getSchemasMock.mockResolvedValue({
      ...SOCIAL_SCHEMA,
      題型: [
        { value: "選擇題", instruction: "" },
        { value: "開放式建構反應題", instruction: "" },
        { value: "填充題", instruction: "" },
      ],
    });

    await openConfirmation("social_studies", {
      count: 1,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [
        { question_type: "選擇題" },
        { question_type: "開放式建構反應題" },
        {},
      ],
    });

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const cards = question.getAllByRole("listitem");
    const firstType = within(cards[0]).getByLabelText("題型");
    const secondType = within(cards[1]).getByLabelText("題型");
    const thirdType = within(cards[2]).getByLabelText("題型");

    expect(secondType).toHaveValue("開放式建構反應題");
    expect(within(secondType.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(thirdType).toHaveValue("");
    expect(within(thirdType.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");

    fireEvent.change(firstType, { target: { value: "填充題" } });

    expect(firstType).toHaveValue("填充題");
    expect(secondType).toHaveValue("開放式建構反應題");
    expect(within(secondType.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(thirdType).toHaveValue("");
    expect(within(thirdType.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");
  });

  it("submits the edited instruction while preserving untouched nested rows and 題組 values", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();

    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [
        {
          question_type: "選擇題",
          instruction: "原始小題指示一",
          text_word_limit: 11,
          question_word_limit: 22,
          option_word_limit: 33,
          content_type: "純文字",
          image_generation_mode: "html",
        },
        {
          question_type: "選擇題",
          instruction: "原始小題指示二",
          text_word_limit: 44,
          question_word_limit: 55,
          option_word_limit: 66,
          content_type: "純文字",
          image_generation_mode: "gpt_image",
        },
        {
          question_type: "選擇題",
          instruction: "原始小題指示三",
          text_word_limit: 77,
          question_word_limit: 88,
          option_word_limit: 99,
          content_type: "純文字",
          image_generation_mode: "html",
        },
      ],
    }, onSubmit);

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    fireEvent.change(firstQuestion.getAllByLabelText("出題指示")[0], {
      target: { value: "第一題組修改後" },
    });
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const submittedPerQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ subquestion_configs: string }>;
    expect(JSON.parse(submittedPerQuestion[0].subquestion_configs)).toEqual([
      {
        question_type: "選擇題",
        instruction: "第一題組修改後",
        text_word_limit: 11,
        question_word_limit: 22,
        option_word_limit: 33,
        content_type: "純文字",
        image_generation_mode: "html",
      },
      {
        question_type: "選擇題",
        instruction: "原始小題指示二",
        text_word_limit: 44,
        question_word_limit: 55,
        option_word_limit: 66,
        content_type: "純文字",
        image_generation_mode: "gpt_image",
      },
      {
        question_type: "選擇題",
        instruction: "原始小題指示三",
        text_word_limit: 77,
        question_word_limit: 88,
        option_word_limit: 99,
        content_type: "純文字",
        image_generation_mode: "html",
      },
    ]);
    expect(JSON.parse(submittedPerQuestion[1].subquestion_configs)).toEqual([
      {
        question_type: "選擇題",
        instruction: "原始小題指示一",
        text_word_limit: 11,
        question_word_limit: 22,
        option_word_limit: 33,
        content_type: "純文字",
        image_generation_mode: "html",
      },
      {
        question_type: "選擇題",
        instruction: "原始小題指示二",
        text_word_limit: 44,
        question_word_limit: 55,
        option_word_limit: 66,
        content_type: "純文字",
        image_generation_mode: "gpt_image",
      },
      {
        question_type: "選擇題",
        instruction: "原始小題指示三",
        text_word_limit: 77,
        question_word_limit: 88,
        option_word_limit: 99,
        content_type: "純文字",
        image_generation_mode: "html",
      },
    ]);
  });

  it("flips only the edited instruction badge to user-supplied", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);

    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    });

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    const secondQuestion = within(screen.getByRole("region", { name: "第2題" }));
    const firstCard = within(firstQuestion.getAllByRole("listitem")[0]);
    const secondCard = within(secondQuestion.getAllByRole("listitem")[0]);
    const firstInstructionHeader = within(firstCard.getByLabelText("出題指示").parentElement!);
    const secondInstructionHeader = within(secondCard.getByLabelText("出題指示").parentElement!);

    expect(firstInstructionHeader.getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(secondInstructionHeader.getByText("隨機抽取")).toHaveClass("text-amber-700");
    fireEvent.change(firstCard.getByLabelText("出題指示"), {
      target: { value: "第一題組修改後" },
    });

    expect(firstInstructionHeader.getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(firstInstructionHeader.queryByText("隨機抽取")).not.toBeInTheDocument();
    expect(secondInstructionHeader.getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(secondInstructionHeader.queryByText("使用者選擇")).not.toBeInTheDocument();
  });

  it("keeps blank history instructions on the random badge", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);

    await openConfirmation("social_studies", {
      count: 2,
      core_question: "已提供的核心問題",
      per_question_params: JSON.stringify([
        { subquestion_configs: JSON.stringify([{ instruction: "" }]) },
        { subquestion_configs: JSON.stringify([{ instruction: "使用者原始指示" }]) },
      ]),
    });

    const firstCard = within(
      within(screen.getByRole("region", { name: "第1題" })).getAllByRole("listitem")[0],
    );
    const secondCard = within(
      within(screen.getByRole("region", { name: "第2題" })).getAllByRole("listitem")[0],
    );
    const firstInstructionHeader = within(firstCard.getByLabelText("出題指示").parentElement!);
    const secondInstructionHeader = within(secondCard.getByLabelText("出題指示").parentElement!);

    expect(firstInstructionHeader.getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(firstInstructionHeader.queryByText("使用者選擇")).not.toBeInTheDocument();
    expect(secondInstructionHeader.getByText("使用者選擇")).toHaveClass("text-green-700");
  });

  it("applies normal form instruction semantics without adding confirmation metadata", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();

    await openConfirmation("social_studies", {
      count: 1,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    }, onSubmit);

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    fireEvent.change(firstQuestion.getAllByLabelText("出題指示")[0], {
      target: { value: "  使用者指示  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const submittedPerQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<Record<string, unknown>>;
    expect(JSON.parse(submittedPerQuestion[0].subquestion_configs as string)).toEqual([
      { instruction: "使用者指示" },
      {},
      {},
    ]);
    expect(submittedPerQuestion[0]).not.toHaveProperty("confirmation_edit");
  });

  it("renders shared 年級 once and renders 種子 only in each per-question block", async () => {
    await openConfirmation("math", { count: 2, seed: 700 });

    const shared = within(screen.getByRole("region", { name: "共同設定" }));
    expect(shared.getByText("年級", { selector: "dt" })).toBeInTheDocument();
    expect(shared.queryByText("種子", { selector: "dt" })).not.toBeInTheDocument();
    for (const name of ["第1題", "第2題"]) {
      const question = within(screen.getByRole("region", { name }));
      expect(question.queryByText("年級", { selector: "dt" })).not.toBeInTheDocument();
      expect(question.getByText("種子", { selector: "dt" })).toBeInTheDocument();
    }
    expect(screen.getAllByText("年級", { selector: "dt" })).toHaveLength(1);
    expect(screen.getAllByText("種子", { selector: "dt" })).toHaveLength(2);
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
    expect(perQuestion.every((item: Record<string, unknown>) => !("subject" in item)))
      .toBe(true);
  });

  it("renders user-chosen 學習表現 and 學習內容 with codes, instructions, and selected captions per question", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA_WITH_CURRICULUM);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          count: 2,
          core_question: "已提供的核心問題",
          learning_performance: ["n-IV-1"],
          learning_content: ["N-7-1"],
        }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    await screen.findByRole("region", { name: "第1題" });
    for (const name of ["第1題", "第2題"]) {
      const question = within(screen.getByRole("region", { name }));
      expect(question.getByText("n-IV-1")).toBeInTheDocument();
      expect(question.getByText(/理解數與量/)).toBeInTheDocument();
      expect(question.getByText("N-7-1")).toBeInTheDocument();
      expect(question.getByText(/負數與數線/)).toBeInTheDocument();
      const captions = question.getAllByText("已選擇（1 項）");
      expect(captions).toHaveLength(2);
      captions.forEach((caption) => expect(caption).toHaveClass("text-green-700"));
    }
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const perQuestion = JSON.parse(onSubmit.mock.calls[0][0].per_question_params);
    expect(perQuestion.map((item: { learning_performance: string[] }) => item.learning_performance))
      .toEqual([["n-IV-1"], ["n-IV-1"]]);
    expect(perQuestion.map((item: { learning_content: string[] }) => item.learning_content))
      .toEqual([["N-7-1"], ["N-7-1"]]);
  });

  it("renders resolver-drawn 學習表現 and 學習內容 with codes, instructions, and random captions per question", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA_WITH_CURRICULUM);
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "natural_sciences",
        grade: 7,
        count: 1,
        per_question_params: JSON.stringify([{
          seed: 917,
          learning_performance: ["n-IV-2"],
          learning_content: ["N-7-2"],
        }]),
      },
      drawn: [
        "per_question_params[0].learning_performance",
        "per_question_params[0].learning_content",
      ],
    });

    await openConfirmation("natural_sciences", { core_question: "已提供的核心問題" });

    const question = within(screen.getByRole("region", { name: "第1題" }));
    expect(question.getByText("n-IV-2")).toBeInTheDocument();
    expect(question.getByText(/運用數與量/)).toBeInTheDocument();
    expect(question.getByText("N-7-2")).toBeInTheDocument();
    expect(question.getByText(/質因數分解/)).toBeInTheDocument();
    const captions = question.getAllByText("未手動選擇 — 已隨機抽取 1 項（將實際送出）：");
    expect(captions).toHaveLength(2);
    captions.forEach((caption) => expect(caption).toHaveClass("text-amber-700"));
  });

  it("renders independently resolved per-question values and badges them amber", async () => {
    getSchemasMock.mockResolvedValue(MATH_SCHEMA_WITH_CURRICULUM);
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "math",
        grade: 7,
        count: 2,
        per_question_params: JSON.stringify([
          { seed: 601, learning_performance: ["n-IV-1"] },
          { seed: 602, learning_performance: ["n-IV-2"] },
        ]),
      },
      drawn: [
        "per_question_params[0].learning_performance",
        "per_question_params[1].learning_performance",
      ],
    });
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

    await screen.findByRole("region", { name: "第1題" });
    for (const name of ["第1題", "第2題"]) {
      const row = within(screen.getByRole("region", { name }))
        .getByText("學習表現")
        .parentElement!;
      expect(within(row).getByText(/未手動選擇 — 已隨機抽取 \d+ 項/)).toHaveClass("text-amber-700");
      expect(within(row).queryByText("由後端隨機抽取（每題不同）")).not.toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const perQuestion = JSON.parse(onSubmit.mock.calls[0][0].per_question_params);
    expect(perQuestion[0].learning_performance).not.toEqual(perQuestion[1].learning_performance);
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

  it("discloses that generation will decide 核心問題 after planner failure and still submits", async () => {
    planCoreQuestionsMock.mockRejectedValue(new Error("planner unavailable"));
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} initialParams={{ topic: "分數" }} />);
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    await waitFor(() => expect(planCoreQuestionsMock).toHaveBeenCalled());
    expect(await confirmationRow("核心問題").findByText("將於生成時決定")).toBeInTheDocument();
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

  it("ignores a stale 核心問題 planner response after returning and submitting again", async () => {
    const first = deferred<{ candidates: string[] }>();
    const second = deferred<{ candidates: string[] }>();
    planCoreQuestionsMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ topic: "分數" }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await waitFor(() => expect(planCoreQuestionsMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));
    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    await waitFor(() => expect(planCoreQuestionsMock).toHaveBeenCalledTimes(2));

    await act(async () => second.resolve({ candidates: ["最新核心問題"] }));
    expect(await confirmationRow("核心問題").findByText("最新核心問題")).toBeInTheDocument();

    await act(async () => first.resolve({ candidates: ["過期核心問題"] }));
    expect(screen.queryByText("過期核心問題")).not.toBeInTheDocument();
    expect(confirmationRow("核心問題").getByText("最新核心問題")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ core_question: "最新核心問題" }));
    const perQuestion = JSON.parse(onSubmit.mock.calls[0][0].per_question_params);
    expect(perQuestion[0].core_question).toBe("最新核心問題");
  });

  it.each([
    ["math", MATH_SCHEMA],
    ["social_studies", SOCIAL_SCHEMA],
    ["natural_sciences", SCIENCE_SCHEMA],
  ])("%s discloses blank 主題 and 文本 as 未填寫 in 共同設定", async (subject, schema) => {
    getSchemasMock.mockResolvedValue(schema);
    await openConfirmation(subject);

    const shared = screen.getByRole("region", { name: "共同設定" });
    for (const label of ["主題", "文本"]) {
      const term = within(shared).getByText(label, { selector: "dt" });
      expect(within(term.parentElement!).getByText("未填寫")).toBeInTheDocument();
    }
  });

  it("renders a resolver-drawn blank 情境 as a concrete per-question draw", async () => {
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "math",
        grade: 7,
        count: 1,
        per_question_params: JSON.stringify([{
          seed: 611,
          context: ["個人"],
        }]),
      },
      drawn: ["per_question_params[0].context"],
    });
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

  it("renders the top-level 文本字數限制 row for math", async () => {
    await openConfirmation("math", { text_word_limit: 321 });
    expect(confirmationRow("文本字數限制").getByText("321")).toBeInTheDocument();
  });

  it("keeps resolver-completed math 文本字數限制 in the confirmed per-question payload", async () => {
    await openConfirmation("math", { text_word_limit: 321 });

    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));
    const payload = previewGenerateMock.mock.calls[0][0];
    expect(payload.text_word_limit).toBe(321);
    expect(JSON.parse(payload.per_question_params)[0]).toHaveProperty("text_word_limit", 321);
  });

  it.each([
    ["social_studies", SOCIAL_SCHEMA],
    ["natural_sciences", SCIENCE_SCHEMA],
  ])("renders the top-level 文本字數限制 value for %s", async (subject, schema) => {
    getSchemasMock.mockResolvedValue(schema);
    await openConfirmation(subject, { text_word_limit: 321 });
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
    const question = within(screen.getByRole("region", { name: "第1題" }));
    expect(screen.queryByText("[{},{},{}]")).not.toBeInTheDocument();

    for (const index of [1, 2, 3]) {
      const title = question.getByText(`第 ${index} 小題`);
      const card = within(title.closest("li")!);
      // Word-limit fields are now editable inputs (not static text)
      expect(card.getByLabelText("題目字數限制")).toBeInTheDocument();
      expect(card.getByLabelText("選項字數限制")).toBeInTheDocument();
      expect(card.getByLabelText("文本字數限制")).toBeInTheDocument();
      const contentType = card.getByLabelText("題目內容類型");
      expect(contentType).toHaveValue("");
      expect(within(contentType.parentElement!).getByText("沿用文本設定")).toHaveClass("text-gray-600");
      const imageMode = card.getByLabelText("圖片生成模式");
      expect(imageMode).toHaveValue("");
      expect(within(imageMode.parentElement!).getByText("沿用文本設定")).toHaveClass("text-gray-600");
      const questionType = card.getByLabelText("題型");
      expect(questionType).toHaveValue("");
      expect(within(questionType.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");
      expect(card.getByText("出題指示", { selector: "label" })).toBeInTheDocument();
      expect(card.getByPlaceholderText("例如：請聚焦在資料判讀與因果推論")).toHaveValue("");
      // Reporting Scale is now an editable select on confirmation cards
      const reportingScaleSelect = card.getByLabelText("Reporting Scale");
      expect(reportingScaleSelect).toHaveValue("");
      expect(within(reportingScaleSelect.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");
      // LC and LP are now editable SearchPickers in the confirmation view.
      expect(card.getByLabelText("學習內容")).toBeInTheDocument();
      expect(card.getByLabelText("學習表現")).toBeInTheDocument();
    }
  });

  it("renders an editable Reporting Scale select with exactly eight PISA levels in 自然科學 確認卡", async () => {
    // Criterion 1: 自然科學 cards render an editable Reporting Scale select with exactly the eight PISA levels
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    await openConfirmation("natural_sciences", { sub_question_count: 3, subquestion_configs: [{}, {}, {}] });
    const question = within(screen.getByRole("region", { name: "第1題" }));
    const cards = question.getAllByRole("listitem");
    expect(cards).toHaveLength(3);
    for (const card of cards) {
      const reportingScaleSelect = within(card).getByLabelText("Reporting Scale");
      expect(reportingScaleSelect).toBeInTheDocument();
      expect(
        Array.from(reportingScaleSelect.querySelectorAll("option"), (o) => (o as HTMLOptionElement).value),
      ).toEqual(["", "1c", "1b", "1a", "2", "3", "4", "5", "6"]);
    }
  });

  it("does not render editable Reporting Scale select in 數學 確認卡", async () => {
    // Criterion 2 (negative): 數學 cards never render the control
    await openConfirmation("math");
    expect(screen.queryByLabelText("Reporting Scale")).not.toBeInTheDocument();
  });

  it("does not render editable Reporting Scale select in 社會領域 確認卡", async () => {
    // Criterion 2 (negative): 社會領域 cards never render the control
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    await openConfirmation("social_studies", {
      sub_question_count: 3,
      subquestion_configs: [{}, {}, {}],
      core_question: "已提供的核心問題",
    });
    const question = within(screen.getByRole("region", { name: "第1題" }));
    const cards = question.getAllByRole("listitem");
    expect(cards).toHaveLength(3);
    for (const card of cards) {
      expect(within(card).queryByLabelText("Reporting Scale")).not.toBeInTheDocument();
    }
  });

  it("editing Reporting Scale flips badge amber→green and lands in the correct subquestion_configs row on 確認送出", async () => {
    // Criterion 3: Editing flips the badge and sends correct per-題組 subquestion_configs
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    const onSubmit = vi.fn();
    await openConfirmation("natural_sciences", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    }, onSubmit);

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    const secondQuestion = within(screen.getByRole("region", { name: "第2題" }));
    const firstCards = firstQuestion.getAllByRole("listitem");
    const secondCards = secondQuestion.getAllByRole("listitem");
    const firstCardFirstScale = within(firstCards[0]).getByLabelText("Reporting Scale");
    const firstCardSecondScale = within(firstCards[1]).getByLabelText("Reporting Scale");
    const secondCardFirstScale = within(secondCards[0]).getByLabelText("Reporting Scale");

    expect(firstCardFirstScale).toHaveValue("");
    expect(within(firstCardFirstScale.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");

    fireEvent.change(firstCardFirstScale, { target: { value: "3" } });

    expect(firstCardFirstScale).toHaveValue("3");
    expect(within(firstCardFirstScale.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(within(firstCardSecondScale.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(within(secondCardFirstScale.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);

    const submittedPerQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ subquestion_configs: string }>;
    const firstQConfigs = JSON.parse(submittedPerQuestion[0].subquestion_configs) as Array<Record<string, unknown>>;
    const secondQConfigs = JSON.parse(submittedPerQuestion[1].subquestion_configs) as Array<Record<string, unknown>>;

    expect(firstQConfigs[0]).toMatchObject({ reporting_scale: "3" });
    expect(firstQConfigs[1]).not.toHaveProperty("reporting_scale");
    expect(firstQConfigs[2]).not.toHaveProperty("reporting_scale");
    expect(secondQConfigs[0]).not.toHaveProperty("reporting_scale");
  });

  it("keeps untouched Reporting Scale values and badges unchanged after a 確認頁修改", async () => {
    // Criterion 4: Untouched 小題 unchanged
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    await openConfirmation("natural_sciences", {
      count: 1,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [
        { reporting_scale: "4" },
        {},
        {},
      ],
    });

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const cards = question.getAllByRole("listitem");
    const firstScale = within(cards[0]).getByLabelText("Reporting Scale");
    const secondScale = within(cards[1]).getByLabelText("Reporting Scale");
    const thirdScale = within(cards[2]).getByLabelText("Reporting Scale");

    expect(firstScale).toHaveValue("4");
    expect(within(firstScale.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(secondScale).toHaveValue("");
    expect(within(secondScale.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(thirdScale).toHaveValue("");
    expect(within(thirdScale.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");

    // Editing the second card should not affect the first or third
    fireEvent.change(secondScale, { target: { value: "2" } });
    expect(firstScale).toHaveValue("4");
    expect(within(firstScale.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(secondScale).toHaveValue("2");
    expect(within(secondScale.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
    expect(thirdScale).toHaveValue("");
    expect(within(thirdScale.parentElement!).getByText("隨機抽取")).toHaveClass("text-amber-700");
  });

  it("renders blank-everything confirmation for 數學 without （無）", async () => {
    await openConfirmation("math");
    expect(screen.queryByText("（無）")).not.toBeInTheDocument();
  });

  it("keeps natural-science and reference-fewshot rows out of 數學", async () => {
    await openConfirmation("math", {
      sub_context: "不應顯示",
      science_competency: ["不應顯示"],
      disable_reference_fewshot: false,
    });
    expect(screen.queryByText("情境子類別", { selector: "dt" })).not.toBeInTheDocument();
    expect(screen.queryByText("科學能力", { selector: "dt" })).not.toBeInTheDocument();
    expect(screen.queryByText("關閉參考範例：是", { selector: "dt" })).not.toBeInTheDocument();
  });

  it("keeps 題型 out of the 社會領域 per-question block", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    await openConfirmation("social_studies", { q_type: [] });

    const question = screen.getByRole("region", { name: "第1題" });
    expect(within(question).queryByText("題型", { selector: "dt" })).not.toBeInTheDocument();
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

  // ──── #442 Word-limit editable fields ────────────────────────────────────────

  it("#442 renders editable 題目字數限制 inputs in each card and shows 確定發送 enabled when blank", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    await openConfirmation("social_studies", {
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    });

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const cards = question.getAllByRole("listitem");
    expect(within(cards[0]).getByLabelText("題目字數限制")).toBeInTheDocument();
    expect(within(cards[1]).getByLabelText("題目字數限制")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "確定發送" })).toBeEnabled();
  });

  it("#442 shows inline error and disables 確認送出 when word limit is invalid, re-enables after correction", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    await openConfirmation("social_studies", {
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    });

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const card = within(question.getAllByRole("listitem")[0]);
    const input = card.getByLabelText("題目字數限制");
    const confirmBtn = screen.getByRole("button", { name: "確定發送" });

    // invalid: zero
    fireEvent.change(input, { target: { value: "0" } });
    expect(confirmBtn).toBeDisabled();

    // corrected: valid positive integer
    fireEvent.change(input, { target: { value: "50" } });
    expect(confirmBtn).toBeEnabled();
  });

  it("#442 word-limit edit lands in the correct subquestion_configs row on 確認送出", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    const onSubmit = vi.fn();

    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [
        { question_word_limit: 10 },
        { option_word_limit: 20 },
        {},
      ],
    }, onSubmit);

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    const firstCard = within(firstQuestion.getAllByRole("listitem")[0]);
    fireEvent.change(firstCard.getByLabelText("題目字數限制"), { target: { value: "99" } });

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const submittedPerQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ subquestion_configs: string }>;
    const firstQuestionConfigs = JSON.parse(submittedPerQuestion[0].subquestion_configs);
    expect(firstQuestionConfigs[0]).toMatchObject({ question_word_limit: 99 });
    // second 題組 is independent
    const secondQuestionConfigs = JSON.parse(submittedPerQuestion[1].subquestion_configs);
    expect(secondQuestionConfigs[0]).toMatchObject({ question_word_limit: 10 });
  });

  it("#442 unset word-limit badge shows neutral 不限 style, set badge shows 使用者選擇", async () => {
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    await openConfirmation("social_studies", {
      sub_question_count: 3,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}, {}],
    });

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const card = within(question.getAllByRole("listitem")[0]);
    const input = card.getByLabelText("題目字數限制");

    // unset → neutral gray badge
    const unsetBadge = within(input.parentElement!).getByText("不限");
    expect(unsetBadge).toHaveClass("text-gray-600");

    // set a value → user-chosen green badge
    fireEvent.change(input, { target: { value: "30" } });
    expect(within(input.parentElement!).getByText("使用者選擇")).toHaveClass("text-green-700");
  });

  it("does not render a 科目 row for 自然科學", async () => {
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ count: 2 }}
      />,
    );
    const subjectOption = await screen.findByRole("option", { name: "歷史" });
    fireEvent.change(subjectOption.closest("select")!, { target: { value: "歷史" } });
    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    await screen.findByRole("heading", { name: "發送前確認設定" });

    const sections = [
      screen.getByRole("region", { name: "共同設定" }),
      screen.getByRole("region", { name: "第1題" }),
      screen.getByRole("region", { name: "第2題" }),
    ];
    const subjectRows = sections.flatMap((section) =>
      within(section).queryAllByText("科目", { selector: "dt" }),
    );
    expect(subjectRows).toHaveLength(0);
  });
});
