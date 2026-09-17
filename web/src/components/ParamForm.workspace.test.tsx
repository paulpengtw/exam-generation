import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FormFields } from "./ParamForm";
import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import { importFormWorkspace } from "../lib/workspace/adapters/formWorkspace";
import { importConfirmationWorkspace } from "../lib/workspace/adapters/confirmationWorkspace";
import {
  resetWorkspaceStoreForTests, useWorkspaceStore,
  type OperationKind, type OperationOutcome,
} from "../lib/workspace/workspaceStore";

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

const DRAFT_KEY = "exam_form_draft_teacher-1";
const SAVED_AT = new Date(Date.now() - 60_000).toISOString();
const SAVED_FIELDS: FormFields = {
  grade: 8,
  style: "素養",
  contentType: "customized",
  customContentType: "圖表判讀",
  context: ["社會"],
  setType: "單一題",
  qType: ["填充題"],
  count: 2,
  coverageMode: "random",
  skipVerify: true,
  disableReferenceFewshot: true,
  coreQuestionCallback: true,
  imageGenerationMode: "gpt_image",
  difficulty: "hard",
  reportingScale: "",
  subjectFilter: "數與量",
  passage: "保存的文本",
  textWordLimit: 120,
  textInstruction: "請以在地案例切入",
  options: ["甲", "乙", "丙", "丁"],
  topic: "保存的主題",
  coreQuestion: "保存的核心問題",
  subContext: "保存的情境子類別",
  scienceCompetency: ["保存的科學能力"],
  learningPerformance: ["n-IV-1"],
  learningContent: ["N-7-1"],
  subQuestionCount: 3,
  subquestionConfigs: [
    { question_type: "填充題", instruction: "第一小題" },
    { content_type: "純文字", question_word_limit: 60 },
    { image_generation_mode: "gpt_image", option_word_limit: 20 },
  ],
  modelPlan: "planner-model",
  modelExecute: "execute-model",
  modelVerify: "",
  modelCorrect: "",
  effortPlan: "high",
  effortExecute: "max",
  effortVerify: "",
  effortCorrect: "",
  allowDuplicateFigureKinds: false,
};

function resolveConfirmationPayload(payload: Record<string, unknown>) {
  const rawRows = payload.per_question_params;
  const sourceRows = typeof rawRows === "string"
    ? JSON.parse(rawRows) as Record<string, unknown>[]
    : [];
  const base = Object.fromEntries(
    Object.entries(payload).filter(([key]) => ![
      "subject", "count", "per_question_params", "drawn", "redraws",
    ].includes(key)),
  );
  const seed = typeof payload.seed === "number" ? payload.seed : 900;
  const rows = sourceRows.map((row, index) => ({
    ...base,
    ...row,
    seed: row.seed ?? seed + index,
  }));
  return {
    payload: {
      ...payload,
      ...(typeof payload.seed === "number" ? {} : { seed }),
      per_question_params: JSON.stringify(rows),
    },
    drawn: [],
  };
}

// Deferred network work lets the real registry expose each lifecycle boundary.
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const MODEL_RESPONSE = { allowed: [], defaults: { plan: "", execute: "" } };
const INITIAL_PARAMS = {
  sub_question_count: 3,
  subquestion_configs: [{}, {}, {}],
  core_question: "測試核心問題",
  topic: "台灣歷史",
};
const REDRAW_PATH = "per_question_params[0].subquestion_configs[0].learning_content";
const LC_A = "RESOLVER-LC-A";
const LP_A = "RESOLVER-LP-A";
const beginOperation = useWorkspaceStore.getState().beginOperation;
let observed: Array<{ id: number; kind: OperationKind; outcomes: OperationOutcome[] }>;

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  useAuthStore.setState({ token: null, user: null });
  useLangStore.setState({ lang: "zh-TW" });
  resetWorkspaceStoreForTests();
  getSchemasMock.mockResolvedValue(SOCIAL_SCHEMA);
  getAvailableModelsMock.mockResolvedValue(MODEL_RESPONSE);
  planCoreQuestionsMock.mockResolvedValue({ candidates: ["候選一", "候選二", "候選三"] });
  previewGenerateMock.mockResolvedValue({ prompts: [] });
  resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) =>
    resolveConfirmationPayload(payload));
  observed = [];
  vi.spyOn(useWorkspaceStore.getState(), "beginOperation").mockImplementation((...args) => {
    const op = beginOperation(...args);
    const entry = { id: op.id, kind: args[0], outcomes: [] as OperationOutcome[] };
    observed.push(entry);
    return { id: op.id, end: (outcome) => { entry.outcomes.push(outcome); op.end(outcome); } };
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  useWorkspaceStore.setState({ beginOperation });
  resetWorkspaceStoreForTests();
});

const formSurface = () => useWorkspaceStore.getState().surfaces["generate.form"];
const confirmationSurface = () => useWorkspaceStore.getState().surfaces["generate.confirmation"];
const confirmation = () => importConfirmationWorkspace(confirmationSurface()?.exportWorkspace?.());
function operation(kind: OperationKind, index = 0) {
  const entry = observed.filter((op) => op.kind === kind)[index];
  expect(entry, `${kind} operation ${index} was begun`).toBeDefined();
  return entry;
}
function expectActive(entry: { id: number; kind: OperationKind }) {
  expect(useWorkspaceStore.getState().operations).toContainEqual(expect.objectContaining({
    id: entry.id, kind: entry.kind, surface: "generate.confirmation",
  }));
}
function expectEnded(entry: { id: number; outcomes: OperationOutcome[] }, outcome: OperationOutcome) {
  // end is idempotent: cleanup can follow completion, but the first outcome wins.
  expect(entry.outcomes[0]).toBe(outcome);
  expect(useWorkspaceStore.getState().operations.some((op) => op.id === entry.id)).toBe(false);
}
function storeDraft() {
  useAuthStore.getState().login("token", {
    id: "teacher-1", email: "teacher@example.com", created_at: "2026-01-01T00:00:00.000Z",
  });
  localStorage.setItem(DRAFT_KEY, JSON.stringify({ savedAt: SAVED_AT, fields: SAVED_FIELDS }));
}
async function renderForm(initialParams: Record<string, unknown> = INITIAL_PARAMS, subject = "social_studies") {
  const onSubmit = vi.fn();
  const view = render(<ParamForm subject={subject} onSubmit={onSubmit} disabled={false} initialParams={initialParams} />);
  await screen.findByRole("button", { name: "產生" });
  return { ...view, onSubmit };
}
async function openConfirmationWithSubquestions(initialParams = INITIAL_PARAMS) {
  const view = await renderForm(initialParams);
  fireEvent.click(screen.getByRole("button", { name: "產生" }));
  await screen.findByRole("heading", { name: "發送前確認設定" });
  return view;
}
function editInstruction(value: string) {
  fireEvent.change(screen.getAllByLabelText("出題指示")[0], { target: { value } });
}
async function advanceDebounce() {
  await act(async () => { vi.advanceTimersByTime(500); });
}
function responseFor(
  payload: Record<string, unknown>,
  learningContent: string,
): { payload: Record<string, unknown>; drawn: string[] } {
  const rows = JSON.parse(payload.per_question_params as string) as Record<string, unknown>[];
  const firstRow = rows[0] ?? {};
  const configs = JSON.parse(firstRow.subquestion_configs as string) as Record<string, unknown>[];
  const completedConfigs = configs.map((config, index) => index === 0
    ? { ...config, learning_content: [learningContent], learning_performance: [LP_A] }
    : config);
  const completedRows = rows.map((row, index) => index === 0
    ? {
        ...row,
        seed: 604,
        learning_content: ["RESOLVER-GLOBAL-LC"],
        learning_performance: ["RESOLVER-GLOBAL-LP"],
        subquestion_configs: JSON.stringify(completedConfigs),
      }
    : row);
  return {
    payload: {
      ...payload,
      seed: 604,
      sub_question_count: 3,
      learning_content: ["RESOLVER-GLOBAL-LC"],
      learning_performance: ["RESOLVER-GLOBAL-LP"],
      per_question_params: JSON.stringify(completedRows),
    },
    drawn: [REDRAW_PATH, "per_question_params[0].subquestion_configs[0].learning_performance"],
  };
}

function redrawResponse(payload: Record<string, unknown>) {
  return responseFor(resolveConfirmationPayload(payload).payload, LC_A);
}
function redrawLearningContent() {
  const question = within(screen.getByRole("region", { name: "第1題" }));
  const heading = question.getByRole("heading", { name: "各小題配置", level: 4 });
  const card = within(heading.closest("section")!).getAllByRole("listitem")[0];
  fireEvent.click(within(card).getAllByRole("button", { name: "重抽" })[0]);
}

describe("ParamForm 工作區參與", () => {
  it.each(["schemas", "models"])("stays hydrating until schemas, models and defaults resolve (%s first)", async (first) => {
    const schemas = deferred<typeof SOCIAL_SCHEMA>();
    const models = deferred<typeof MODEL_RESPONSE>();
    getSchemasMock.mockReturnValue(schemas.promise);
    getAvailableModelsMock.mockReturnValue(models.promise);
    const { unmount } = render(<ParamForm onSubmit={vi.fn()} disabled={false} />);
    expect(formSurface()).toMatchObject({ readiness: "hydrating", hasEditableState: false, hasReceivedResults: false });
    await act(async () => { if (first === "schemas") schemas.resolve(SOCIAL_SCHEMA); else models.resolve(MODEL_RESPONSE); });
    expect(formSurface()?.readiness).toBe("hydrating");
    await act(async () => { if (first === "schemas") models.resolve(MODEL_RESPONSE); else schemas.resolve(SOCIAL_SCHEMA); });
    expect(formSurface()?.readiness).toBe("ready");
    unmount();
    expect(formSurface()).toBeUndefined();
  });

  it("exports the current form and becomes editable only after typing", async () => {
    await renderForm();
    expect(formSurface()?.hasEditableState).toBe(false);
    fireEvent.change(screen.getByPlaceholderText("例如：氣候變遷與都市規劃"), { target: { value: "臺灣史" } });
    expect(formSurface()).toMatchObject({ readiness: "ready", hasEditableState: true, hasReceivedResults: false });
    expect(importFormWorkspace(formSurface()?.exportWorkspace?.())).toMatchObject({ topic: "臺灣史", subQuestionCount: 3 });
  });

  it.each(["還原草稿", "重新開始"])("reports restoring during the draft prompt, then ready after %s", async (choice) => {
    storeDraft();
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    await renderForm({}, "math");
    await screen.findByText("找到未完成的出題表單。");
    expect(formSurface()?.readiness).toBe("restoring");
    fireEvent.click(screen.getByRole("button", { name: choice }));
    expect(formSurface()?.readiness).toBe("ready");
    expect(importFormWorkspace(formSurface()?.exportWorkspace?.())?.topic).toBe(choice === "還原草稿" ? "保存的主題" : "");
  });

  it.each([
    ["還原草稿", "draft"],
    ["使用從歷史紀錄帶入的設定", "history"],
    ["重新開始", "defaults"],
  ])("reports restoring during draft vs History and exports the %s choice", async (button, choice) => {
    storeDraft();
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    const historyPrefill = { topic: "歷史主題", core_question: "歷史核心問題" };
    await renderForm(historyPrefill, "math");
    const dialog = await screen.findByRole("dialog");
    expect(formSurface()?.readiness).toBe("restoring");
    fireEvent.change(screen.getByPlaceholderText("例如：氣候變遷與都市規劃"), { target: { value: "編輯" } });
    expect(formSurface()?.hasEditableState).toBe(true);
    fireEvent.click(within(dialog).getByRole("button", { name: button }));
    expect(formSurface()?.readiness).toBe("ready");
    if (choice !== "draft") expect(formSurface()?.hasEditableState).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    await screen.findByRole("heading", { name: "發送前確認設定" });
    expect(confirmation()?.historyDraftChoice).toBe(choice);
    expect(confirmation()?.pendingPrefill).toEqual(
      choice === "draft" ? SAVED_FIELDS : choice === "history" ? historyPrefill : null,
    );
  });

  it.each(["確定發送", "返回修改"])("registers confirmation only while open, unregistering on %s", async (button) => {
    const { onSubmit } = await openConfirmationWithSubquestions();
    expect(confirmationSurface()).toMatchObject({ readiness: "ready", hasEditableState: true, hasReceivedResults: false });
    expect(formSurface()?.hasEditableState).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(confirmationSurface()).toBeUndefined();
    expect(formSurface()).toBeDefined();
    expect(onSubmit).toHaveBeenCalledTimes(button === "確定發送" ? 1 : 0);
  });

  it("round trips the resolved confirmation and reads live redraw counters after one 重抽", async () => {
    let resolved!: ReturnType<typeof redrawResponse>;
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => {
      resolved = redrawResponse(payload);
      return resolved;
    });
    await openConfirmationWithSubquestions();
    const snapshot = confirmationSurface()?.exportWorkspace?.();
    expect(snapshot).toMatchObject({ kind: "confirmation", version: 1 });
    expect(confirmation()).toEqual({
      pendingParams: { ...resolved.payload, drawn: resolved.drawn },
      pendingPerQuestionParams: JSON.parse(resolved.payload.per_question_params),
      pendingPrefill: INITIAL_PARAMS,
      clearedPaths: [], redraws: {}, hasPendingConfirmationEdits: false,
      coreQuestionResolution: "idle", historyDraftChoice: null,
    });
    redrawLearningContent();
    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(2));
    expect(confirmation()?.redraws).toEqual({ [REDRAW_PATH]: 1 });
    expect(importConfirmationWorkspace(snapshot)?.redraws).toEqual({});
  });
});

describe("ParamForm 可觀察作業", () => {
  it.each([true, false])("observes resolve until success=%s", async (success) => {
    const request = deferred<ReturnType<typeof resolveConfirmationPayload>>();
    resolveGenerateMock.mockReturnValue(request.promise);
    await renderForm();
    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    const op = operation("resolve");
    expectActive(op);
    expect(confirmationSurface()).toBeUndefined();
    await act(async () => {
      if (success) request.resolve(resolveConfirmationPayload(resolveGenerateMock.mock.calls[0][0]));
      else request.reject(new Error("resolve failed"));
    });
    expectEnded(op, success ? "completed" : "failed");
  });

  it.each([true, false])("supersedes the older resolve before its success=%s response arrives", async (success) => {
    const older = deferred<ReturnType<typeof resolveConfirmationPayload>>();
    const newer = deferred<ReturnType<typeof resolveConfirmationPayload>>();
    resolveGenerateMock.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    await renderForm();
    const form = screen.getByRole("button", { name: "產生" }).closest("form")!;
    fireEvent.submit(form);
    const first = operation("resolve");
    // Drive the submit handler directly, as in the existing dormant-guard tests.
    fireEvent.submit(form);
    expectEnded(first, "superseded");
    const second = operation("resolve", 1);
    expectActive(second);
    await act(async () => {
      if (success) older.resolve(resolveConfirmationPayload(resolveGenerateMock.mock.calls[0][0]));
      else older.reject(new Error("stale resolve"));
    });
    expect(confirmationSurface()).toBeUndefined();
    expectActive(second);
    await act(async () => { newer.resolve(resolveConfirmationPayload(resolveGenerateMock.mock.calls[1][0])); });
    expectEnded(second, "completed");
    expect(confirmationSurface()).toBeDefined();
  });

  it("supersedes an in-flight redraw on confirmation cancel", async () => {
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => redrawResponse(payload));
    await openConfirmationWithSubquestions();
    const redraw = deferred<ReturnType<typeof redrawResponse>>();
    resolveGenerateMock.mockReturnValueOnce(redraw.promise);
    redrawLearningContent();
    const op = operation("resolve", 1);
    expectActive(op);
    fireEvent.click(screen.getByRole("button", { name: "返回修改" }));
    expectEnded(op, "superseded");
    await act(async () => { redraw.resolve(redrawResponse(resolveGenerateMock.mock.calls[1][0])); });
    expect(confirmationSurface()).toBeUndefined();
  });

  it.each(["completed", "empty", "rejected", "aborted"])("observes planning outcome %s", async (result) => {
    const planning = deferred<{ candidates: string[] }>();
    planCoreQuestionsMock.mockReturnValue(planning.promise);
    const { unmount } = await openConfirmationWithSubquestions({ ...INITIAL_PARAMS, core_question: "" });
    await waitFor(() => {
      expect(observed.some(({ kind }) => kind === "core_question_planning")).toBe(true);
    });
    const op = operation("core_question_planning");
    expectActive(op);
    expect(confirmation()?.coreQuestionResolution).toBe("loading");
    if (result === "aborted") unmount();
    await act(async () => {
      if (result === "rejected") planning.reject(new Error("planning failed"));
      else planning.resolve({ candidates: result === "empty" ? [] : ["候選一", "候選二", "候選三"] });
    });
    expectEnded(op, result === "completed" ? "completed" : result === "aborted" ? "aborted" : "failed");
    if (result !== "aborted") expect(confirmation()?.coreQuestionResolution).toBe(result === "completed" ? "generated" : "failed");
  });

  it.each(["completed", "failed", "superseded"])("observes the initial preview outcome %s", async (outcome) => {
    const preview = deferred<{ prompts: never[] }>();
    previewGenerateMock.mockReturnValueOnce(preview.promise);
    const { unmount } = await openConfirmationWithSubquestions();
    const op = operation("prompt_preview");
    expectActive(op);
    if (outcome === "superseded") unmount();
    await act(async () => {
      if (outcome === "failed") preview.reject(new Error("preview failed"));
      else preview.resolve({ prompts: [] });
    });
    expectEnded(op, outcome);
  });

  it.each([true, false])("begins debounced previews only when fetching and supersedes stale success=%s", async (success) => {
    await openConfirmationWithSubquestions();
    vi.useFakeTimers();
    const older = deferred<{ prompts: never[] }>();
    const newer = deferred<{ prompts: never[] }>();
    previewGenerateMock.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    editInstruction("指示A");
    expect(observed.filter((op) => op.kind === "prompt_preview")).toHaveLength(1);
    await advanceDebounce();
    const first = operation("prompt_preview", 1);
    expectActive(first);
    editInstruction("指示B");
    await advanceDebounce();
    const second = operation("prompt_preview", 2);
    expectActive(second);
    await act(async () => {
      if (success) older.resolve({ prompts: [] });
      else older.reject(new Error("stale preview"));
    });
    expectEnded(first, "superseded");
    expectActive(second);
    await act(async () => { newer.resolve({ prompts: [] }); });
    expectEnded(second, "completed");
  });

  it.each(["completed", "failed", "superseded-success", "superseded-failure"])("observes failed refetch and manual preview retry ending %s", async (result) => {
    await openConfirmationWithSubquestions();
    // Let the confirmation's initial preview settle before replacing the mock
    // for the debounced refetch. Otherwise the initial promise can race the
    // first operation assertion under the full suite.
    await waitFor(() => expect(operation("prompt_preview").outcomes[0]).toBe("completed"));
    vi.useFakeTimers();
    previewGenerateMock.mockRejectedValueOnce(new Error("refetch failed"));
    editInstruction("失敗的指示");
    await advanceDebounce();
    expectEnded(operation("prompt_preview", 1), "failed");
    const retry = deferred<{ prompts: never[] }>();
    previewGenerateMock.mockReturnValueOnce(retry.promise);
    fireEvent.click(screen.getByRole("button", { name: "重新載入預覽" }));
    const op = operation("prompt_preview", 2);
    expectActive(op);
    if (result.startsWith("superseded")) editInstruction("新的指示");
    await act(async () => {
      if (result === "failed" || result === "superseded-failure") retry.reject(new Error("retry failed"));
      else retry.resolve({ prompts: [] });
    });
    expectEnded(op, result.startsWith("superseded") ? "superseded" : result as OperationOutcome);
    if (result === "failed") expect(screen.getByRole("button", { name: "重新載入預覽" })).toBeInTheDocument();
    if (result === "completed") expect(screen.queryByRole("button", { name: "重新載入預覽" })).not.toBeInTheDocument();
  });
});
