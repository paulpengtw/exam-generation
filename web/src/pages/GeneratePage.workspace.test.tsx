import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { FormParams } from "../components/ParamForm";
import type { AdmissionOutcome, ExamQuestion, UseGenerateReturn } from "../hooks/useGenerate";
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { importResultsWorkspace } from "../lib/workspace/adapters/resultsWorkspace";
import type { ConfirmationWorkspaceSnapshot, FormWorkspaceSnapshot, ResultsWorkspaceSnapshot } from "../lib/workspace/adapters/types";
import { resetRecoveryStoreForTests, useRecoveryStore } from "../lib/recovery/recoveryStore";

vi.stubGlobal("__BUILD_ENVIRONMENT__", "test");

const generateMock = vi.hoisted(() => vi.fn());
const buildOdt = vi.hoisted(() => vi.fn());
const capturedSubmit = vi.hoisted(() => ({ current: null as ((params: FormParams) => Promise<AdmissionOutcome> | undefined) | null }));
const capturedParamFormProps = vi.hoisted(() => ({
  current: null as {
    recoveredForm?: FormWorkspaceSnapshot;
    recoveredConfirmation?: ConfirmationWorkspaceSnapshot;
    onRecoveryAcknowledge?: () => boolean | void;
    onRecoveryDiscard?: () => boolean | void;
  } | null,
}));
let state: UseGenerateReturn;
vi.mock("../hooks/useGenerate", () => ({ useGenerate: () => state }));
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(), useLocation: () => ({ pathname: "/generate/math", state: null }),
  useBlocker: () => ({ state: "unblocked" }),
}));
vi.mock("../i18n/useT", () => ({ useT: () => (key: string) => key }));
vi.mock("../utils/odt", () => ({ buildExamOdt: buildOdt, formatTimestamp: () => "ts" }));
vi.mock("../components/ParamForm", () => ({
  default: ({
    onSubmit,
    recoveredForm,
    recoveredConfirmation,
    onRecoveryAcknowledge,
    onRecoveryDiscard,
  }: {
    onSubmit: typeof capturedSubmit.current;
    recoveredForm?: FormWorkspaceSnapshot;
    recoveredConfirmation?: ConfirmationWorkspaceSnapshot;
    onRecoveryAcknowledge?: () => boolean | void;
    onRecoveryDiscard?: () => boolean | void;
  }) => {
    capturedSubmit.current = onSubmit;
    capturedParamFormProps.current = { recoveredForm, recoveredConfirmation, onRecoveryAcknowledge, onRecoveryDiscard };
    return null;
  },
}));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
import GeneratePage from "./GeneratePage";

const question: ExamQuestion = { id: "q1", 情境: [], 題型種類: "single", 題型: "choice", 題目: ["question"], 正確解題分析: ["answer"] };
const params: FormParams = { count: 4, grade: 7, context: [], q_type: [], set_type: "", image_generation_mode: "html", skip_verify: false, sub_question_count: 3 };
const beginOperation = useWorkspaceStore.getState().beginOperation;
let end: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetWorkspaceStoreForTests();
  resetRecoveryStoreForTests();
  capturedParamFormProps.current = null;
  generateMock.mockReset();
  buildOdt.mockReset();
  state = {
    status: "idle", admission: "idle", admissionError: null,
    progressLines: [], results: [], displayResults: [], llmCalls: [], agentLanes: [],
    errorMessage: null, startedAt: null, finishedAt: null, generationLogId: null, subQuestionTotal: null,
    generate: generateMock, reset: vi.fn(), restoreResults: vi.fn(() => true),
  };
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  end = vi.fn();
  vi.spyOn(useWorkspaceStore.getState(), "beginOperation").mockImplementation((...args) => {
    const op = beginOperation(...args);
    return { id: op.id, end: (outcome) => { end(outcome); op.end(outcome); } };
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  useWorkspaceStore.setState({ beginOperation });
});

function withResults() {
  state = { ...state, results: [question], displayResults: [{ index: 0, question, isFinal: true }] };
}

function recoveryResults(): ResultsWorkspaceSnapshot {
  return {
    kind: "results", version: 1,
    results: [question],
    displayResults: [{ index: 0, question, isFinal: true, phase: "verified" }],
    progressLines: ["received"], errorMessage: null, startedAt: 1, finishedAt: 2,
    subQuestionTotal: null, requestedTotal: 1, submittedSubQuestionCount: null,
    completion: "unknown", processing: "unknown", terminalEvidence: false,
  };
}

describe("GeneratePage workspace", () => {
  it("threads the latched recovery confirmation beside the ordinary form snapshot", () => {
    const recoveredForm = {
      kind: "form" as const,
      version: 1 as const,
      fields: {} as never,
    };
    const recoveredConfirmation = {
      kind: "confirmation" as const,
      version: 1 as const,
      pendingParams: { subject: "math", topic: "captured" } as never,
      pendingPerQuestionParams: [{ topic: "captured row" }],
      clearedPaths: [],
      redraws: {},
      hasPendingConfirmationEdits: true,
      coreQuestionResolution: "generated" as const,
      historyDraftChoice: "history" as const,
    };
    useRecoveryStore.setState({
      pending: {
        schema: "exam-generation.recovery/1",
        snapshot_id: "snapshot-1",
        tab_id: "tab-1",
        route: "/generate/math",
        subject: "math",
        account_id: "u1",
        origin: "https://example.test",
        environment: "test",
        source_build_id: "build-a",
        target_build_id: "build-b",
        source_release_revision: 1,
        target_release_revision: 2,
        saved_at: new Date(0).toISOString(),
        workspace_revision: 1,
        form: recoveredForm,
        confirmation: recoveredConfirmation,
      },
      blocked: null,
    });

    render(<GeneratePage subject="math" />);

    expect(capturedParamFormProps.current).toMatchObject({ recoveredForm, recoveredConfirmation });
  });

  it("mirrors received results, exports submitted counts, and unregisters on unmount", () => {
    const { rerender, unmount } = render(<GeneratePage />);
    expect(useWorkspaceStore.getState().surfaces["generate.results"]).toMatchObject({
      readiness: "ready", hasEditableState: false, hasReceivedResults: false,
    });
    act(() => { capturedSubmit.current?.(params); });
    withResults();
    rerender(<GeneratePage />);
    const surface = useWorkspaceStore.getState().surfaces["generate.results"];
    expect(surface?.hasReceivedResults).toBe(true);
    expect(importResultsWorkspace(surface?.exportWorkspace?.())).toMatchObject({
      kind: "results", version: 1, requestedTotal: 4, submittedSubQuestionCount: 3,
      results: [question], displayResults: [{ index: 0, question, isFinal: true }],
    });
    state = { ...state, results: [], displayResults: [] };
    rerender(<GeneratePage />);
    expect(useWorkspaceStore.getState().surfaces["generate.results"]?.hasReceivedResults).toBe(false);
    unmount();
    expect(useWorkspaceStore.getState().surfaces["generate.results"]).toBeUndefined();
  });

  it("hydrates received results through the hook before recovery can be acknowledged", () => {
    const results = recoveryResults();
    useRecoveryStore.setState({
      pending: {
        schema: "exam-generation.recovery/1", snapshot_id: "snapshot-results", tab_id: "tab-1",
        route: "/generate/math", subject: "math", account_id: "u1", origin: "https://example.test",
        environment: "test", source_build_id: "build-a", target_build_id: "build-b",
        source_release_revision: 1, target_release_revision: 2, saved_at: new Date(0).toISOString(),
        workspace_revision: 1, form: { kind: "form", version: 1, fields: {} as never }, results,
      },
      blocked: null,
    });
    render(<GeneratePage subject="math" />);

    expect(state.restoreResults).toHaveBeenCalledWith(results);
    expect(capturedParamFormProps.current?.onRecoveryAcknowledge?.()).toBe(true);
    expect(useRecoveryStore.getState().pending).toBeNull();
  });

  it("returns the admission promise from onSubmit", async () => {
    const promise = Promise.resolve<AdmissionOutcome>({ outcome: "admitted" });
    generateMock.mockReturnValue(promise);
    render(<GeneratePage />);
    let returned: unknown;
    act(() => { returned = capturedSubmit.current?.(params); });
    expect(returned).toBe(promise);
    await expect(returned).resolves.toEqual({ outcome: "admitted" });
  });

  it("observes JSON creation and download synchronously", () => {
    withResults();
    render(<GeneratePage />);
    vi.mocked(URL.createObjectURL).mockImplementation(() => {
      expect(useWorkspaceStore.getState().operations).toEqual([
        expect.objectContaining({ kind: "export_json", surface: "generate.results" }),
      ]);
      return "blob:test";
    });
    fireEvent.click(screen.getByRole("button", { name: "generate.btn_download_all" }));
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    expect(end).toHaveBeenCalledWith("completed");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
  });

  it.each([true, false])("observes ODT until it settles with success=%s", async (success) => {
    let resolve!: (blob: Blob) => void;
    let reject!: (error: Error) => void;
    buildOdt.mockReturnValue(new Promise<Blob>((yes, no) => { resolve = yes; reject = no; }));
    withResults();
    render(<GeneratePage />);
    const before = document.body.textContent;
    fireEvent.click(screen.getByRole("button", { name: "generate.btn_download_all_odt" }));
    expect(useWorkspaceStore.getState().operations).toEqual([
      expect.objectContaining({ kind: "export_odt", surface: "generate.results" }),
    ]);
    await act(async () => { if (success) resolve(new Blob(["odt"])); else reject(new Error("export failed")); });
    expect(end).toHaveBeenCalledWith(success ? "completed" : "failed");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
    expect(document.body.textContent).toBe(before);
  });
});
