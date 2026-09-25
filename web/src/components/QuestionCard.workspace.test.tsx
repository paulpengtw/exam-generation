import type { FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExamQuestion } from "../hooks/useGenerate";
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { importModificationWorkspace } from "../lib/workspace/adapters/modificationWorkspace";
import type { ModificationWorkspaceSnapshot } from "../lib/workspace/adapters/types";

const buildOdt = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());
const fetchEventSourceMock = vi.hoisted(() => vi.fn<(url: string, init: FetchEventSourceInit) => Promise<void>>());
vi.mock("@microsoft/fetch-event-source", () => ({ fetchEventSource: fetchEventSourceMock }));
vi.mock("../api/client", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/client")>(),
  submitModificationBatch: vi.fn().mockResolvedValue({ run_id: "run-1", status: "accepted" }),
}));
vi.mock("../store/langStore", () => ({ useLangStore: (selector: (s: { lang: string }) => unknown) => selector({ lang: "en-US" }) }));
vi.mock("../utils/odt", () => ({ buildExamOdt: buildOdt, formatTimestamp: () => "ts" }));
import QuestionCard from "./QuestionCard";

const question: ExamQuestion = {
  id: "q1", 情境: [], 題型種類: "single", 題型: "choice",
  題目: ["A passage that can be selected"], 正確解題分析: ["answer"],
  image_base64: "aW1hZ2U=", verification: { passed: true },
};

const recoveredModification: ModificationWorkspaceSnapshot = {
  kind: "modification",
  version: 1,
  route: "/history/record-1",
  subject: "math",
  recordId: "record-1",
  questionId: "q1",
  contentIdentity: "canonical-q1",
  contentRevision: null,
  eligibility: { status: "completed", verified: true, eligible: true },
  annotations: [
    {
      segments: [{ field_path: "題目[0]", start: 2, end: 9, quoted_text: "passage" }],
      instruction: "Fix the passage",
    },
    {
      segments: [{ field_path: "題目[0]", start: 10, end: 16, quoted_text: "that can" }],
      instruction: "Clarify the wording",
    },
  ],
  replacement: {
    record_id: "record-1",
    question: { ...question, 題目: ["Updated passage"] },
    ripple_report: [],
    verified: true,
    verification: { passed: true },
    failure_details: null,
  },
};
const beginOperation = useWorkspaceStore.getState().beginOperation;
let end: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetWorkspaceStoreForTests();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  buildOdt.mockReset();
  fetchEventSourceMock.mockReset().mockResolvedValue(undefined);
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
  vi.unstubAllGlobals();
  useWorkspaceStore.setState({ beginOperation });
  window.getSelection()?.removeAllRanges();
});

function selectPassage() {
  const field = screen.getByText("A passage that can be selected", { exact: true });
  const textNode = field.firstChild;
  if (!(textNode instanceof Text)) throw new Error("Expected passage text node");
  const range = document.createRange();
  range.setStart(textNode, 2);
  range.setEnd(textNode, 9);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent.mouseUp(field);
}

describe("QuestionCard workspace", () => {
  it("participates only with a record id, including when the prop changes", () => {
    const { rerender, unmount } = render(<QuestionCard question={question} />);
    expect(useWorkspaceStore.getState().surfaces).toEqual({});
    rerender(<QuestionCard question={question} recordId="record-1" />);
    expect(useWorkspaceStore.getState().surfaces["history.modification"]).toMatchObject({
      readiness: "ready", hasEditableState: false, hasReceivedResults: false,
    });
    rerender(<QuestionCard question={question} />);
    expect(useWorkspaceStore.getState().surfaces).toEqual({});
    unmount();
  });

  it("exports editable annotations and the received replacement from live state", async () => {
    const { unmount } = render(<QuestionCard question={question} recordId="record-1" />);
    selectPassage();
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix this wording" },
    });
    const surface = useWorkspaceStore.getState().surfaces["history.modification"];
    expect(surface?.hasEditableState).toBe(true);
    expect(importModificationWorkspace(surface?.exportWorkspace?.())).toMatchObject({
      route: "/", subject: "math", recordId: "record-1", questionId: "q1", replacement: null,
      eligibility: { status: "completed", verified: true, eligible: true },
      annotations: [{ segments: [{ field_path: "題目[0]", start: 2, end: 9, quoted_text: "passage" }], instruction: "Fix this wording" }],
    });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Submit modifications" })); });
    const replacement = {
      record_id: "record-2", question: { ...question, 題目: ["Updated question"] },
      ripple_report: [], verified: true, verification: null, failure_details: null,
    };
    act(() => { fetchEventSourceMock.mock.lastCall![1].onmessage?.({ id: "", event: "done", data: JSON.stringify(replacement) }); });
    const updated = useWorkspaceStore.getState().surfaces["history.modification"];
    expect(updated).toMatchObject({ hasEditableState: false, hasReceivedResults: true });
    expect(importModificationWorkspace(updated?.exportWorkspace?.())).toMatchObject({
      recordId: "record-2", questionId: "q1", annotations: [], replacement,
    });
    unmount();
    expect(useWorkspaceStore.getState().surfaces["history.modification"]).toBeUndefined();
  });

  it("restores multiple selections and instructions without replaying modification work", () => {
    const { rerender } = render(
      <QuestionCard
        question={question}
        recordId="record-1"
        recoveredModification={recoveredModification}
        modificationRestoreEligible
      />,
    );

    expect(screen.getByText("Updated passage")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Selections" })).toHaveTextContent("passage");
    expect(screen.getByRole("list", { name: "Selections" })).toHaveTextContent("that can");
    expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).toHaveValue("Fix the passage");
    expect(screen.getByRole("textbox", { name: "Modification instruction 2" })).toHaveValue("Clarify the wording");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(fetchEventSourceMock).not.toHaveBeenCalled();

    // The recovery notice may be acknowledged after hydration. The card's
    // restored workspace must not fall back to its ordinary initial state.
    rerender(<QuestionCard question={question} recordId="record-1" />);
    expect(screen.getByText("Updated passage")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).toHaveValue("Fix the passage");
  });

  it("keeps restored edits visible but disables them when the base check fails", () => {
    render(
      <QuestionCard
        question={question}
        recordId="record-1"
        recoveredModification={recoveredModification}
        modificationRestoreEligible={false}
      />,
    );

    expect(screen.getByText("Updated passage")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete selection 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit modifications" })).toBeDisabled();
  });

  it("keeps recovered edits blocked unless the caller explicitly authorizes the base", () => {
    render(
      <QuestionCard
        question={question}
        recordId="record-1"
        recoveredModification={recoveredModification}
      />,
    );

    expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit modifications" })).toBeDisabled();
  });

  it.each([
    [undefined, "generate.results", "JSON", "export_json"],
    ["record-1", "history.modification", "JSON", "export_json"],
    [undefined, "generate.results", "PNG", "export_image"],
    ["record-1", "history.modification", "PNG", "export_image"],
  ] as const)("observes %s / %s %s download", (recordId, surface, label, kind) => {
    render(<QuestionCard question={question} recordId={recordId} />);
    vi.mocked(URL.createObjectURL).mockImplementation(() => {
      expect(useWorkspaceStore.getState().operations).toEqual([expect.objectContaining({ kind, surface })]);
      return "blob:test";
    });
    fireEvent.click(screen.getByRole("button", { name: new RegExp(label) }));
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    expect(end).toHaveBeenCalledWith("completed");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
  });

  it.each([
    [undefined, "generate.results", true], ["record-1", "history.modification", true],
    ["record-1", "history.modification", false],
  ] as const)("observes %s / %s ODT success=%s", async (recordId, surface, success) => {
    let resolve!: (blob: Blob) => void;
    let reject!: (error: Error) => void;
    buildOdt.mockReturnValue(new Promise<Blob>((yes, no) => { resolve = yes; reject = no; }));
    render(<QuestionCard question={question} recordId={recordId} />);
    const before = document.body.textContent;
    fireEvent.click(screen.getByRole("button", { name: /ODT/ }));
    expect(useWorkspaceStore.getState().operations).toEqual([expect.objectContaining({ kind: "export_odt", surface })]);
    await act(async () => { if (success) resolve(new Blob(["odt"])); else reject(new Error("failed")); });
    expect(end).toHaveBeenCalledWith(success ? "completed" : "failed");
    expect(useWorkspaceStore.getState().operations).toEqual([]);
    expect(document.body.textContent).toBe(before);
  });
});
