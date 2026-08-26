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
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

function resolveConfirmationPayload(payload: Record<string, unknown>) {
  const sourceRows = typeof payload.per_question_params === "string"
    ? JSON.parse(payload.per_question_params) as Record<string, unknown>[]
    : [];
  const base = Object.fromEntries(
    Object.entries(payload).filter(([key]) => ![
      "subject", "count", "per_question_params", "drawn", "redraws",
    ].includes(key)),
  );
  return {
    payload: {
      ...payload,
      per_question_params: JSON.stringify(sourceRows.map((row) => ({ ...base, ...row }))),
    },
    drawn: [],
  };
}

const SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "開放式建構反應題", instruction: "" },
  ],
  認知歷程: [
    { value: "Knowing–Defining and Describing", instruction: "" },
    { value: "Knowing–Illustrating with examples", instruction: "" },
    { value: "Reasoning and Applying–Interpret information", instruction: "" },
    { value: "Reasoning and Applying–Relate or Integrate", instruction: "" },
  ],
  內容領域: [
    { value: "Civic Institutions and Systems", instruction: "" },
    { value: "Civic Principles", instruction: "" },
    { value: "Civic Participation", instruction: "" },
    { value: "Civic Roles and Identities", instruction: "" },
  ],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }, { value: "跨科", instruction: "" }],
  數學思考: [],
  學習表現: [],
  學習內容: [],
  digital_only_question_types: [],
};

async function renderSocial(initialParams: Record<string, unknown> = {}) {
  render(
    <ParamForm
      subject="social_studies"
      onSubmit={vi.fn()}
      disabled={false}
      initialParams={initialParams}
    />,
  );
  await screen.findByRole("button", { name: "產生" });
}

async function submitForm() {
  fireEvent.click(screen.getByRole("button", { name: "產生" }));
  fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));
}

describe("ParamForm 社會領域 ICCS domain and surface controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "", verify: "", correct: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) =>
      resolveConfirmationPayload(payload));
  });

  it("renders all four content domains and omits an unset domain pin", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm subject="social_studies" onSubmit={onSubmit} disabled={false} />,
    );

    const domainSelect = await screen.findByLabelText("內容領域");
    expect(Array.from(domainSelect.querySelectorAll("option"), (option) => option.value)).toEqual([
      "",
      "Civic Institutions and Systems",
      "Civic Principles",
      "Civic Participation",
      "Civic Roles and Identities",
    ]);
    expect(domainSelect).toHaveValue("");

    await submitForm();

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty("content_domain");
  });

  it("sends a selected content domain and digital surface", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm subject="social_studies" onSubmit={onSubmit} disabled={false} />,
    );

    fireEvent.change(await screen.findByLabelText("內容領域"), {
      target: { value: "Civic Participation" },
    });
    fireEvent.change(screen.getByLabelText("卷面"), {
      target: { value: "數位" },
    });

    await submitForm();

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toEqual(expect.objectContaining({
      content_domain: "Civic Participation",
      target_surface: "數位",
    }));
  });

  it("defaults to 紙本 and omits target_surface from the old request shape", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm subject="social_studies" onSubmit={onSubmit} disabled={false} />,
    );

    expect(await screen.findByLabelText("卷面")).toHaveValue("紙本");
    await submitForm();

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty("target_surface");
  });

  it("shows the request-level domain and effective surface on 發送前確認", async () => {
    await renderSocial({
      content_domain: "Civic Principles",
      target_surface: "數位",
    });

    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    await screen.findByRole("heading", { name: "發送前確認設定" });

    const shared = screen.getByRole("region", { name: "共同設定" });
    const domainRow = within(shared).getByText("內容領域", { selector: "dt" });
    expect(within(domainRow.parentElement!).getByText("Civic Principles")).toBeInTheDocument();
    const surfaceRow = within(shared).getByText("卷面", { selector: "dt" });
    expect(within(surfaceRow.parentElement!).getByText("數位")).toBeInTheDocument();
  });

  it("round-trips a per-subquestion cognitive-process pin and shows it in confirmation", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          sub_question_count: 3,
          subquestion_configs: [{}, {}, {}],
        }}
      />,
    );

    const firstRow = (await screen.findByText("第1小題")).parentElement!;
    const cognitiveSelect = within(firstRow).getByLabelText("認知歷程");
    expect(Array.from(cognitiveSelect.querySelectorAll("option"), (option) => option.value)).toEqual([
      "",
      "Knowing–Defining and Describing",
      "Knowing–Illustrating with examples",
      "Reasoning and Applying–Interpret information",
      "Reasoning and Applying–Relate or Integrate",
    ]);

    fireEvent.change(cognitiveSelect, {
      target: { value: "Reasoning and Applying–Relate or Integrate" },
    });
    fireEvent.click(screen.getByRole("button", { name: "產生" }));

    const question = await screen.findByRole("region", { name: "第1題" });
    const card = within(question).getByText("第 1 小題").closest("li");
    expect(within(card!).getByText("認知歷程: Reasoning and Applying–Relate or Integrate")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as { subquestion_configs: string };
    expect(JSON.parse(payload.subquestion_configs)[0]).toEqual(expect.objectContaining({
      cognitive_process: "Reasoning and Applying–Relate or Integrate",
    }));
  });

  it("names each violated composition rule and removes warnings as pins are resolved", async () => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          subject_filter: "跨科",
          sub_question_count: 3,
          subquestion_configs: [
            { cognitive_process: "Knowing–Defining and Describing" },
            { cognitive_process: "Knowing–Defining and Describing" },
            { cognitive_process: "Reasoning and Applying–Interpret information" },
          ],
        }}
      />,
    );

    await screen.findByText("第1小題");
    const knowingRule = "至多1題 Knowing–Defining and Describing";
    const crossSubjectRule = "跨科需含 Relate-or-Integrate";
    expect(await screen.findByText(knowingRule)).toBeInTheDocument();
    expect(screen.getByText(crossSubjectRule)).toBeInTheDocument();

    const firstRow = screen.getByText("第1小題").parentElement!;
    fireEvent.change(within(firstRow).getByLabelText("認知歷程"), {
      target: { value: "Knowing–Illustrating with examples" },
    });
    await waitFor(() => expect(screen.queryByText(knowingRule)).not.toBeInTheDocument());
    expect(screen.getByText(crossSubjectRule)).toBeInTheDocument();

    const thirdRow = screen.getByText("第3小題").parentElement!;
    fireEvent.change(within(thirdRow).getByLabelText("認知歷程"), {
      target: { value: "Reasoning and Applying–Relate or Integrate" },
    });
    await waitFor(() => {
      expect(screen.queryByText(knowingRule)).not.toBeInTheDocument();
      expect(screen.queryByText(crossSubjectRule)).not.toBeInTheDocument();
    });
  });

  it("keeps the form submittable while composition warnings are visible", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          subject_filter: "跨科",
          sub_question_count: 3,
          subquestion_configs: [
            { cognitive_process: "Knowing–Defining and Describing" },
            { cognitive_process: "Knowing–Defining and Describing" },
            { cognitive_process: "Reasoning and Applying–Interpret information" },
          ],
        }}
      />,
    );

    expect(await screen.findByText("至多1題 Knowing–Defining and Describing")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it("filters synthetic digital-only question types by the selected surface", async () => {
    getSchemasMock.mockResolvedValue({
      ...SOCIAL_SCHEMA,
      題型: [...SOCIAL_SCHEMA.題型, { value: "拖放題", instruction: "" }],
      digital_only_question_types: ["拖放題"],
    });
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ sub_question_count: 3, subquestion_configs: [{}, {}, {}] }}
      />,
    );

    const firstRow = (await screen.findByText("第1小題")).parentElement!;
    const questionTypeSelect = within(firstRow).getAllByRole("combobox")[0];
    expect(questionTypeSelect).not.toHaveTextContent("拖放題");

    fireEvent.change(screen.getByLabelText("卷面"), { target: { value: "數位" } });
    await waitFor(() => expect(questionTypeSelect).toHaveTextContent("拖放題"));
  });

  it("clears and explains an existing digital-only pin when switching back to 紙本", async () => {
    const onSubmit = vi.fn();
    getSchemasMock.mockResolvedValue({
      ...SOCIAL_SCHEMA,
      題型: [...SOCIAL_SCHEMA.題型, { value: "拖放題", instruction: "" }],
      digital_only_question_types: ["拖放題"],
    });
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          target_surface: "數位",
          sub_question_count: 3,
          subquestion_configs: [{ question_type: "拖放題" }, {}, {}],
        }}
      />,
    );

    const firstRow = (await screen.findByText("第1小題")).parentElement!;
    const questionTypeSelect = within(firstRow).getAllByRole("combobox")[0];
    expect(questionTypeSelect).toHaveValue("拖放題");

    fireEvent.change(screen.getByLabelText("卷面"), { target: { value: "紙本" } });
    await waitFor(() => expect(questionTypeSelect).toHaveValue(""));
    expect(await screen.findByText("已因切換為紙本清除數位限定題型釘選：拖放題")).toBeInTheDocument();
    expect(questionTypeSelect).not.toHaveTextContent("拖放題");

    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    const payload = onSubmit.mock.calls[0][0] as { subquestion_configs: string };
    expect(JSON.parse(payload.subquestion_configs)[0]).not.toHaveProperty("question_type");
  });
});
