import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const recordFigureFallbackMock = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());
const fetchEventSourceMock = vi.hoisted(() => vi.fn());

vi.mock("../utils/figureFallbackMetric", () => ({
  recordFigureFallback: recordFigureFallbackMock,
}));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../store/authStore", () => {
  const state = { token: null, user: null, logout: vi.fn() };
  const useAuthStore = Object.assign(
    (selector: (s: typeof state) => unknown) => selector(state),
    { getState: () => state },
  );
  return { useAuthStore };
});

vi.stubGlobal("fetch", fetchMock);

import QuestionCard from "./QuestionCard";
import type { ExamQuestion, SubQuestion } from "../hooks/useGenerate";

const subQuestion: SubQuestion = {
  id: "sq1",
  序號: 1,
  年級: 8,
  科目: ["地理"],
  核心素養: ["社-J-A2"],
  學習內容: [],
  學習表現: [],
  出題概念: "",
  題型: "選擇題",
  題目: "Question asks (A) x (B) y (C) z (D) w",
  答案: "B",
  答案解析: "…",
  評分規準: [],
  誘答分析: {},
};

const baseQuestion: ExamQuestion = {
  id: "ss1",
  情境: ["公共"],
  題型種類: "題組題",
  題型: "選擇題",
  核心問題: "core?",
  文本: "Shared passage",
  subquestions: [subQuestion],
  題目: ["passage", subQuestion.題目],
  正確解題分析: ["B"],
  verification: { passed: true },
};

const modifiedQuestion: ExamQuestion = {
  ...baseQuestion,
  文本: "Updated passage",
  題目: ["updated passage", subQuestion.題目],
  verification: { passed: true, details: "通過" },
};

function getSelectionField(fieldPath: string): HTMLElement {
  const field = document.querySelector<HTMLElement>(`[data-selection-field="${fieldPath}"]`);
  if (!field) throw new Error(`Missing selection field ${fieldPath}`);
  return field;
}

function getOnlyTextNode(element: HTMLElement): Text {
  const textNode = element.firstChild;
  if (!(textNode instanceof Text)) throw new Error("Expected a field to contain one text node");
  return textNode;
}

function selectRange(
  startElement: HTMLElement,
  startOffset: number,
  endOffset: number,
): void {
  const range = document.createRange();
  range.setStart(getOnlyTextNode(startElement), startOffset);
  range.setEnd(getOnlyTextNode(startElement), endOffset);

  const selection = window.getSelection();
  if (!selection) throw new Error("jsdom did not provide a Selection");
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent(document, new Event("selectionchange"));
  fireEvent.mouseUp(startElement);
}

function emit(
  init: { onmessage?: (event: { id: string; event: string; data: string }) => void },
  event: string,
  data: unknown,
): void {
  init.onmessage?.({ id: "", event, data: JSON.stringify(data) });
}

function stage(
  stageName: "modification" | "verify" | "correct",
  status: "start" | "end",
  retry?: number,
) {
  return {
    type: "stage",
    agent: stageName === "modification" || stageName === "correct" ? "corrector" : "verifier",
    stage: stageName,
    step: stageName === "modification" ? "修改" : stageName === "verify" ? "驗證" : "修正",
    status,
    ts: Date.now(),
    ...(retry === undefined ? {} : { retry }),
  };
}

function donePayload(
  question: ExamQuestion = modifiedQuestion,
  overrides: Record<string, unknown> = {},
) {
  return {
    record_id: "record-424-child",
    question,
    ripple_report: ["subquestions[0].答案"],
    verified: question.verification !== undefined
      && (question.verification as { passed?: boolean }).passed === true,
    verification: question.verification,
    failure_details: null,
    ...overrides,
  };
}

async function submitFirstSelection(): Promise<void> {
  selectRange(getSelectionField("文本"), 7, 14);
  fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
    target: { value: "Fix the passage" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
}

function mockAdmission(runId = "run-424") {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify({ run_id: runId, status: "started" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  fetchMock.mockReset();
  fetchEventSourceMock.mockReset();
});

describe("QuestionCard 人工審題修正 run lifecycle", () => {
  it("renders 修改 → 驗證 → 修正 → 驗證 in stream order", async () => {
    let releaseStream!: () => void;
    const streamGate = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });
    mockAdmission();
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "stage", stage("modification", "start"));
      emit(init, "stage", stage("modification", "end"));
      emit(init, "stage", stage("verify", "start"));
      emit(init, "stage", stage("verify", "end"));
      emit(init, "stage", stage("correct", "start", 1));
      emit(init, "stage", stage("correct", "end", 1));
      emit(init, "stage", stage("verify", "start", 1));
      await streamGate;
    });

    render(<QuestionCard question={baseQuestion} recordId="record-424" isFinal />);
    await submitFirstSelection();

    const breadcrumb = await screen.findByTestId("modification-step-breadcrumb");
    expect(breadcrumb).toHaveTextContent("Modify");
    expect(breadcrumb).toHaveTextContent("Verify");
    expect(breadcrumb).toHaveTextContent("Correct");
    const steps = screen.getAllByTestId(/modification-step-\d+/);
    expect(steps.map((stepElement) => stepElement.textContent)).toEqual([
      "Modify",
      "Verify",
      "Correct",
      "Verify",
    ]);

    await act(async () => {
      releaseStream();
    });
  });

  it("updates the card in place with the modified question and ripple report", async () => {
    mockAdmission();
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "done", donePayload());
    });

    render(<QuestionCard question={baseQuestion} recordId="record-424" isFinal />);
    await submitFirstSelection();

    await waitFor(() => expect(screen.getByText("Modified")).toBeInTheDocument());
    expect(screen.getByText("Updated passage")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Ripple report" })).toHaveTextContent(
      "subquestions[0].答案",
    );
  });

  it("renders the updated chart_spec from the modification result", async () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    const updatedQuestion: ExamQuestion = {
      ...modifiedQuestion,
      chart_spec: {
        render_mode: "html",
        description: "修正後圖表",
        data: { columns: ["時段"], rows: [["10:00"]] },
      },
    };
    mockAdmission();
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "done", donePayload(updatedQuestion));
    });

    render(<QuestionCard question={baseQuestion} recordId="record-424" isFinal />);
    await submitFirstSelection();

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByText("10:00")).toBeInTheDocument();
  });

  it("shows failure details beside the returned irreconcilable last attempt", async () => {
    const failedQuestion: ExamQuestion = {
      ...modifiedQuestion,
      文本: "Last attempted passage",
      verification: {
        passed: false,
        details: "Unable to satisfy the verification and modification instructions.",
      },
    };
    mockAdmission();
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "done", donePayload(failedQuestion, {
        verified: false,
        failure_details: "Unable to satisfy the verification and modification instructions.",
        verification: failedQuestion.verification,
      }));
    });

    render(<QuestionCard question={baseQuestion} recordId="record-424" isFinal />);
    await submitFirstSelection();

    const failure = await screen.findByRole("alert", { name: "Modification verification failed" });
    expect(failure).toHaveTextContent("Unable to satisfy the verification and modification instructions.");
    expect(screen.getByText("Last attempted passage")).toBeInTheDocument();
  });

  it("keeps submit disabled during the run and re-enables it for a new review round", async () => {
    let releaseStream!: () => void;
    const streamGate = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });
    mockAdmission();
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "stage", stage("modification", "start"));
      await streamGate;
      emit(init, "done", donePayload());
    });

    render(<QuestionCard question={baseQuestion} recordId="record-424" isFinal />);
    await submitFirstSelection();

    const inFlightSubmit = await screen.findByRole("button", { name: "Submitting…" });
    expect(inFlightSubmit).toBeDisabled();

    await act(async () => {
      releaseStream();
    });
    await waitFor(() => {
      expect(screen.getByText("Modified")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Submitting…" })).not.toBeInTheDocument();
    });

    selectRange(getSelectionField("文本"), 0, 7);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Review the updated passage" },
    });
    expect(screen.getByRole("button", { name: "Submit modifications" })).not.toBeDisabled();
  });

  it("accepts a new 圈選 against the updated question immediately", async () => {
    mockAdmission();
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "done", donePayload());
    });

    render(<QuestionCard question={baseQuestion} recordId="record-424" isFinal />);
    await submitFirstSelection();
    await screen.findByText("Updated passage");

    selectRange(getSelectionField("文本"), 0, 7);

    const selections = within(screen.getByRole("list", { name: "Selections" }));
    expect(selections.getAllByRole("listitem")).toHaveLength(1);
    expect(selections.getByRole("listitem")).toHaveAttribute("data-quoted-text", "Updated");
  });

  it("keeps the updated question as the base when the next review round starts", async () => {
    mockAdmission("run-424-first");
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "done", donePayload());
    });

    render(<QuestionCard question={baseQuestion} recordId="record-424" isFinal />);
    await submitFirstSelection();
    await screen.findByText("Updated passage");

    selectRange(getSelectionField("文本"), 0, 7);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Review the updated passage" },
    });

    let releaseStream!: () => void;
    const streamGate = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });
    mockAdmission("run-424-second");
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "stage", stage("modification", "start"));
      await streamGate;
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));

    await waitFor(() => expect(fetchEventSourceMock).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Updated passage")).toBeInTheDocument();

    await act(async () => {
      releaseStream();
    });
  });

  it("uses the persisted child record for the next review round", async () => {
    mockAdmission("run-424-first");
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "done", donePayload());
    });

    render(<QuestionCard question={baseQuestion} recordId="record-424" isFinal />);
    await submitFirstSelection();
    await screen.findByText("Updated passage");

    selectRange(getSelectionField("文本"), 0, 7);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Review the updated passage" },
    });

    mockAdmission("run-424-second");
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "done", donePayload());
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/generation-records/record-424-child/modifications",
    );
  });

  it("keeps an irreconcilable last attempt selectable for another review", async () => {
    const failedQuestion: ExamQuestion = {
      ...modifiedQuestion,
      文本: "Last attempted passage",
      verification: { passed: false, details: "Needs another review" },
    };
    mockAdmission();
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: { onmessage?: (event: { id: string; event: string; data: string }) => void }) => {
      emit(init, "done", donePayload(failedQuestion, {
        verified: false,
        failure_details: "Needs another review",
        verification: failedQuestion.verification,
      }));
    });

    render(<QuestionCard question={baseQuestion} recordId="record-424" isFinal />);
    await submitFirstSelection();
    await screen.findByText("Last attempted passage");

    selectRange(getSelectionField("文本"), 0, 4);
    expect(within(screen.getByRole("list", { name: "Selections" })).getByRole("listitem"))
      .toHaveAttribute("data-quoted-text", "Last");
  });
});
