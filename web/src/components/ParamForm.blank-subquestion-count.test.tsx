import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const SS_LC = ["FIRST-LC-0", "FIRST-LC-1", "FIRST-LC-2", "FIRST-LC-3", "FIRST-LC-4", "PIN-LC"];
const SS_LP = ["FIRST-LP-0", "FIRST-LP-1", "FIRST-LP-2", "FIRST-LP-3", "FIRST-LP-4", "PIN-LP"];
const NS_LC = ["NS-LC-0", "NS-LC-1", "NS-LC-2", "NS-LC-3", "NS-LC-4"];
const NS_LP = ["NS-LP-0", "NS-LP-1", "NS-LP-2", "NS-LP-3", "NS-LP-4"];

const SS_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: SS_LP.map((value) => ({ value, instruction: value, 科目: "歷史" })),
  學習內容: SS_LC.map((value) => ({ value, instruction: value, 科目: "歷史" })),
};

const NS_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "Health", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple multiple-choice", instruction: "" }],
  科學能力: [{ value: "Ability one", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  學習表現: NS_LP.map((value) => ({ value, instruction: value })),
  學習內容: NS_LC.map((value) => ({ value, instruction: value })),
};

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

type Slot = Record<string, unknown>;

function slot(prefix: string, index: number): Slot {
  return {
    question_type: "選擇題",
    cognitive_process: `${prefix}-認知-${index}`,
    reporting_scale: String(index + 1),
    learning_content: [`${prefix}-LC-${index}`],
    learning_performance: [`${prefix}-LP-${index}`],
  };
}

function drawnFor(
  count: number,
  fields: string[],
  omitted: Set<string> = new Set(),
): string[] {
  return [
    "per_question_params[0].sub_question_count",
    ...Array.from({ length: count }, (_, index) => fields
      .filter((field) => !omitted.has(`${index}.${field}`))
      .map((field) => `per_question_params[0].subquestion_configs[${index}].${field}`))
      .flat(),
  ];
}

function socialResponse(configs: Slot[], count = configs.length, drawn = drawnFor(
  configs.length,
  ["question_type", "認知歷程", "learning_content", "learning_performance"],
)): { payload: Record<string, unknown>; drawn: string[] } {
  const row = {
    seed: 606,
    grade: 8,
    context: ["個人"],
    set_type: "題組題",
    subject_filter: ["歷史"],
    content_domain: "Civic Institutions and Systems",
    target_surface: "紙本",
    sub_question_count: count,
    subquestion_configs: JSON.stringify(configs),
  };
  return {
    payload: {
      subject: "social_studies",
      grade: 8,
      count: 1,
      per_question_params: JSON.stringify([row]),
    },
    drawn,
  };
}

function naturalResponse(configs: Slot[]): { payload: Record<string, unknown>; drawn: string[] } {
  const count = configs.length;
  const row = {
    seed: 607,
    grade: 8,
    context: ["Personal"],
    sub_context: "Health",
    set_type: "題組題",
    sub_question_count: count,
    subquestion_configs: JSON.stringify(configs),
  };
  return {
    payload: {
      subject: "natural_sciences",
      grade: 8,
      count: 1,
      per_question_params: JSON.stringify([row]),
    },
    drawn: drawnFor(count, ["question_type", "reporting_scale", "learning_content", "learning_performance"]),
  };
}

function mathResponse(count: number): { payload: Record<string, unknown>; drawn: string[] } {
  return {
    payload: {
      subject: "math",
      grade: 8,
      count: 1,
      per_question_params: JSON.stringify([{ seed: 608, set_type: "題組題", sub_question_count: count }]),
    },
    drawn: ["per_question_params[0].sub_question_count"],
  };
}

function countRow(questionIndex = 0) {
  const question = within(screen.getByRole("region", { name: `第${questionIndex + 1}題` }));
  const label = question.getByText("小題數", { selector: "dt" });
  return label.parentElement!;
}

function configSection(questionIndex = 0) {
  const question = within(screen.getByRole("region", { name: `第${questionIndex + 1}題` }));
  const heading = question.queryByRole("heading", { name: "各小題配置", level: 4 });
  return heading ? within(heading.closest("section") as HTMLElement) : null;
}

describe("ParamForm blank 小題數 confirmation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SS_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  it("shows a resolver-drawn count and exactly its resolved social slots without changing the form draft", async () => {
    const onSubmit = vi.fn();
    const onUnsubmittedInput = vi.fn();
    const configs = [0, 1, 2, 3].map((index) => slot("FIRST", index));
    resolveGenerateMock.mockResolvedValueOnce(socialResponse(configs));

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        onUnsubmittedInput={onUnsubmittedInput}
        disabled={false}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    await screen.findByText("FIRST-LC-0");
    expect(countRow()).toHaveTextContent("4");
    expect(within(countRow()).getByText("隨機抽取")).toBeInTheDocument();
    expect(within(countRow()).getByRole("button", { name: "重抽" })).toBeInTheDocument();
    expect(configSection()?.getAllByRole("listitem")).toHaveLength(4);
    expect(onUnsubmittedInput).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));
    expect(screen.getByLabelText("小題數")).toHaveValue(null);
    expect(screen.queryByText("FIRST-LC-0")).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("clears and redraws the count, preserves the request rows, and renders the rebuilt slots", async () => {
    const pinned = {
      ...slot("FIRST", 0),
      cognitive_process: "PIN-認知",
      learning_content: ["PIN-LC"],
      learning_performance: ["PIN-LP"],
    };
    const initialConfigs = [pinned, ...[1, 2].map((index) => slot("FIRST", index))];
    const rebuiltConfigs = [pinned, ...[1, 2, 3, 4].map((index) => slot("SECOND", index))];
    const pinnedFields = new Set([
      "0.question_type",
      "0.認知歷程",
      "0.learning_content",
      "0.learning_performance",
    ]);
    resolveGenerateMock
      .mockResolvedValueOnce(socialResponse(
        initialConfigs,
        initialConfigs.length,
        drawnFor(initialConfigs.length, ["question_type", "認知歷程", "learning_content", "learning_performance"], pinnedFields),
      ))
      .mockResolvedValueOnce(socialResponse(
        rebuiltConfigs,
        5,
        drawnFor(5, ["question_type", "認知歷程", "learning_content", "learning_performance"], new Set([
          "0.question_type",
          "0.認知歷程",
          "0.learning_content",
          "0.learning_performance",
        ])),
      ));

    render(<ParamForm subject="social_studies" onSubmit={vi.fn()} disabled={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByText("PIN-LC");
    fireEvent.click(within(countRow()).getByRole("button", { name: "重抽" }));

    await screen.findByText("PIN-LC");
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(2));
    const [redrawPayload, redraws] = resolveGenerateMock.mock.calls[1] as [Record<string, unknown>, Record<string, number>];
    expect(redraws).toEqual({ "per_question_params[0].sub_question_count": 1 });
    expect(redrawPayload.sub_question_count).toBeUndefined();
    const redrawRows = JSON.parse(redrawPayload.per_question_params as string) as Record<string, unknown>[];
    expect(redrawRows[0].sub_question_count).toBeUndefined();
    expect(JSON.parse(redrawRows[0].subquestion_configs as string)[0]).toEqual(
      expect.objectContaining(pinned),
    );
    expect(redrawPayload.drawn).toContain(
      "per_question_params[0].subquestion_configs[1].learning_content",
    );
    expect(countRow()).toHaveTextContent("5");
    expect(configSection()?.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.queryByText("FIRST-LC-1")).not.toBeInTheDocument();
  });

  it("edits the resolved count and rebuilds slots through the resolver", async () => {
    const pinned = {
      ...slot("FIRST", 0),
      cognitive_process: "PIN-認知",
      learning_content: ["PIN-LC"],
      learning_performance: ["PIN-LP"],
    };
    const initialConfigs = [pinned, slot("FIRST", 1), slot("FIRST", 2)];
    const rebuiltConfigs = [pinned, ...[1, 2, 3, 4].map((index) => slot("SECOND", index))];
    const pinnedFields = new Set([
      "0.question_type",
      "0.認知歷程",
      "0.learning_content",
      "0.learning_performance",
    ]);
    resolveGenerateMock
      .mockResolvedValueOnce(socialResponse(
        initialConfigs,
        initialConfigs.length,
        drawnFor(initialConfigs.length, ["question_type", "認知歷程", "learning_content", "learning_performance"], pinnedFields),
      ))
      .mockResolvedValueOnce(socialResponse(
        rebuiltConfigs,
        5,
        drawnFor(5, ["question_type", "認知歷程", "learning_content", "learning_performance"], new Set([
          "0.question_type",
          "0.認知歷程",
          "0.learning_content",
          "0.learning_performance",
        ])),
      ));

    render(<ParamForm subject="social_studies" onSubmit={vi.fn()} disabled={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByText("PIN-LC");
    fireEvent.click(within(countRow()).getByRole("button", { name: "編輯" }));
    fireEvent.change(within(countRow()).getByRole("spinbutton", { name: "小題數" }), {
      target: { value: "5" },
    });

    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(2));
    const [editPayload, redraws] = resolveGenerateMock.mock.calls[1] as [Record<string, unknown>, Record<string, number>];
    const editRows = JSON.parse(editPayload.per_question_params as string) as Record<string, unknown>[];
    expect(editRows[0].sub_question_count).toBe(5);
    expect(JSON.parse(editRows[0].subquestion_configs as string)[0]).toEqual(
      expect.objectContaining(pinned),
    );
    expect(redraws).toEqual({ "per_question_params[0].sub_question_count": 1 });
    expect(countRow()).toHaveTextContent("5");
    expect(configSection()?.getAllByRole("listitem")).toHaveLength(5);
  });

  it("shows the same drawn count row for natural-sciences slots", async () => {
    getSchemasMock.mockResolvedValue(NS_SCHEMA);
    const configs = [0, 1, 2, 3, 4].map((index) => slot("NS", index));
    resolveGenerateMock.mockResolvedValueOnce(naturalResponse(configs));

    render(<ParamForm subject="natural_sciences" onSubmit={vi.fn()} disabled={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByText("NS-LC-0");

    expect(countRow()).toHaveTextContent("5");
    expect(within(countRow()).getByText("隨機抽取")).toBeInTheDocument();
    expect(within(countRow()).getByRole("button", { name: "重抽" })).toBeInTheDocument();
    expect(configSection()?.getAllByRole("listitem")).toHaveLength(5);
  });

  it("shows a resolver-derived math group count with the redraw control", async () => {
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    resolveGenerateMock.mockResolvedValueOnce(mathResponse(6));

    render(
      <ParamForm
        subject="math"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ set_type: "題組題" }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    expect(await screen.findByText("6")).toBeInTheDocument();
    expect(within(countRow()).getByText("隨機抽取")).toBeInTheDocument();
    expect(within(countRow()).getByRole("button", { name: "重抽" })).toBeInTheDocument();
    expect(configSection()).toBeNull();
  });
});
