import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { FormParams } from "../components/ParamForm";
import type { AdmissionOutcome, ExamQuestion, UseGenerateReturn } from "../hooks/useGenerate";
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { importResultsWorkspace } from "../lib/workspace/adapters/resultsWorkspace";

const generateMock = vi.hoisted(() => vi.fn());
const buildOdt = vi.hoisted(() => vi.fn());
const capturedSubmit = vi.hoisted(() => ({ current: null as ((params: FormParams) => Promise<AdmissionOutcome> | undefined) | null }));
let state: UseGenerateReturn;
vi.mock("../hooks/useGenerate", () => ({ useGenerate: () => state }));
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(), useLocation: () => ({ state: null }),
  useBlocker: () => ({ state: "unblocked" }),
}));
vi.mock("../i18n/useT", () => ({ useT: () => (key: string) => key }));
vi.mock("../utils/odt", () => ({ buildExamOdt: buildOdt, formatTimestamp: () => "ts" }));
vi.mock("../components/ParamForm", () => ({
  default: ({ onSubmit }: { onSubmit: typeof capturedSubmit.current }) => {
    capturedSubmit.current = onSubmit;
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
  generateMock.mockReset();
  buildOdt.mockReset();
  state = {
    status: "idle", admission: "idle", admissionError: null,
    progressLines: [], results: [], displayResults: [], llmCalls: [], agentLanes: [],
    errorMessage: null, startedAt: null, finishedAt: null, generationLogId: null, subQuestionTotal: null,
    generate: generateMock, reset: vi.fn(), restoreResults: vi.fn(),
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

describe("GeneratePage workspace", () => {
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
