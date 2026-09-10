import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const recordFigureFallbackMock = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());

vi.mock("../utils/figureFallbackMetric", () => ({
  recordFigureFallback: recordFigureFallbackMock,
}));

vi.stubGlobal("fetch", fetchMock);

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import QuestionCard from "./QuestionCard";
import type { ExamQuestion, ReferenceExampleRecordShape } from "../hooks/useGenerate";

const question: ExamQuestion = {
  id: "q_ref_test",
  情境: ["Personal"],
  題型種類: "Single question",
  題型: "Multiple choice",
  數學思考: ["Reasoning"],
  學習內容: [{ 編碼: "N-7-1", 說明: "Numbers" }],
  題目: ["What is 2 + 2?"],
  正確解題分析: ["2 + 2 = 4."],
};

const _entry = (overrides = {}) => ({
  code: "reference_example" as const,
  kind: "example" as const,
  question_id: "q_ref_test",
  stage: "generator",
  slot: null,
  description: "Test few-shot example",
  source: "/some/path/few_shot.json",
  timestamp: "2026-09-10T00:00:00Z",
  ...overrides,
});

describe("QuestionCard 參考範例紀錄 integration", () => {
  it("draft with empty enabled record shows in-progress line", () => {
    const record: ReferenceExampleRecordShape = { disabled: false, entries: [] };
    render(
      <QuestionCard
        question={question}
        phase="draft"
        isFinal={false}
        referenceExampleRecord={record}
      />,
    );
    expect(
      screen.getByText("No reference example drawn yet (generation in progress)."),
    ).toBeInTheDocument();
  });

  it("re-render with two entries shows count and reveals entries on expand", () => {
    const record: ReferenceExampleRecordShape = {
      disabled: false,
      entries: [
        _entry({ description: "First example", timestamp: "2026-09-10T00:00:00Z" }),
        _entry({ description: "Second example", slot: 2, timestamp: "2026-09-10T00:01:00Z" }),
      ],
    };
    render(
      <QuestionCard
        question={question}
        phase="verified"
        isFinal={true}
        referenceExampleRecord={record}
      />,
    );
    // Collapsed by default — show toggle button with count "2"
    const toggleBtn = screen.getByRole("button", {
      name: "Show reference examples used during generation",
    });
    expect(toggleBtn).toBeInTheDocument();
    expect(toggleBtn.textContent).toBe("2");
    // Entries are not yet visible
    expect(screen.queryByText("First example")).not.toBeInTheDocument();

    // Click toggle to expand
    fireEvent.click(toggleBtn);

    expect(screen.getByText(/First example/)).toBeInTheDocument();
    expect(screen.getByText(/Second example/)).toBeInTheDocument();
  });

  it("final card with entries: section present and appears after figure policy trail", () => {
    const record: ReferenceExampleRecordShape = {
      disabled: false,
      entries: [_entry()],
    };
    const { container } = render(
      <QuestionCard
        question={question}
        phase="verified"
        isFinal={true}
        figurePolicyTrail={[]}
        referenceExampleRecord={record}
      />,
    );

    const refSection = container.querySelector('[aria-label="Reference examples"]');
    expect(refSection).toBeInTheDocument();
    // Collapsed by default — show count
    expect(refSection?.textContent).toMatch(/1/);
  });

  it("final + null record shows no-record line", () => {
    render(
      <QuestionCard
        question={question}
        phase="verified"
        isFinal={true}
        referenceExampleRecord={null}
      />,
    );
    expect(screen.getByText("No reference examples were recorded.")).toBeInTheDocument();
  });

  it("final + disabled record shows disabled line", () => {
    const record: ReferenceExampleRecordShape = { disabled: true, entries: [] };
    render(
      <QuestionCard
        question={question}
        phase="verified"
        isFinal={true}
        referenceExampleRecord={record}
      />,
    );
    expect(
      screen.getByText("Reference examples were turned off for this run."),
    ).toBeInTheDocument();
  });

  it("draft + disabled record shows disabled line (not in-progress)", () => {
    const record: ReferenceExampleRecordShape = { disabled: true, entries: [] };
    render(
      <QuestionCard
        question={question}
        phase="draft"
        isFinal={false}
        referenceExampleRecord={record}
      />,
    );
    expect(
      screen.getByText("Reference examples were turned off for this run."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No reference example drawn yet (generation in progress)."),
    ).not.toBeInTheDocument();
  });
});
