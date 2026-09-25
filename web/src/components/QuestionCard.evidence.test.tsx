/**
 * F4: QuestionCard with QuestionEvidence prop tests.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import QuestionCard from "./QuestionCard";
import type { QuestionEvidence } from "../lib/generationEvidence";

function makeEvidence(overrides: Partial<QuestionEvidence> = {}): QuestionEvidence {
  return {
    questionId: "q_001",
    index: 0,
    processing: "waiting",
    content: { receipt: "none", revision: null, question: null, phase: null },
    terminal: null,
    finalPending: false,
    finalMissing: false,
    review: { status: "unknown", revision: null },
    trail: [],
    figurePolicyTrail: [],
    referenceExampleRecord: undefined,
    ...overrides,
  };
}

const sampleQuestion = {
  id: "q_001",
  情境: ["個人"],
  題型種類: "單一題",
  題型: "選擇題",
  題目: ["sample question"],
  正確解題分析: ["answer"],
};

describe("QuestionCard — placeholder (evidence, no content)", () => {
  it("renders a compact placeholder without a question", () => {
    render(<QuestionCard evidence={makeEvidence()} index={0} />);
    expect(screen.getByTestId("question-card-placeholder")).toBeInTheDocument();
  });

  it("shows 等待生成 for waiting processing", () => {
    render(<QuestionCard evidence={makeEvidence({ processing: "waiting" })} index={0} />);
    expect(screen.getByTestId("question-card-placeholder")).toHaveTextContent("等待生成");
  });

  it("shows 生成中 for running processing", () => {
    render(<QuestionCard evidence={makeEvidence({ processing: "running" })} index={0} />);
    expect(screen.getByTestId("question-card-placeholder")).toHaveTextContent("生成中");
  });

  it("shows 狀態未知 for unknown processing", () => {
    render(<QuestionCard evidence={makeEvidence({ processing: "unknown" })} index={0} />);
    expect(screen.getByTestId("question-card-placeholder")).toHaveTextContent("狀態未知");
  });

  it("does NOT render the full question card when evidence is placeholder", () => {
    render(<QuestionCard evidence={makeEvidence()} index={0} />);
    expect(screen.queryByTestId("question-card-content")).not.toBeInTheDocument();
  });

  it("summarizes active operation sets and expands details on demand", async () => {
    const activity = {
      operations: {
        O1: {
          operationId: "O1", step: "subquestions", status: "active" as const,
          agent: "sub_generator#1", subquestionIndex: 1, supersedesOperationId: null, callIds: [],
        },
        O2: {
          operationId: "O2", step: "subquestions", status: "active" as const,
          agent: "sub_generator#2", subquestionIndex: 2, supersedesOperationId: null, callIds: [],
        },
      },
      calls: {},
    };
    render(<QuestionCard evidence={makeEvidence({ processing: "running", activity })} index={0} />);

    expect(screen.getByTestId("question-card-activity-summary")).toHaveTextContent("Sub-questions");
    expect(screen.getByTestId("question-card-activity-summary")).toHaveTextContent("2");
    expect(screen.queryByTestId("question-card-activity-operation-O1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("question-card-activity-summary"));
    expect(screen.getByTestId("question-card-activity-operation-O1")).toBeInTheDocument();
    expect(screen.getByTestId("question-card-activity-operation-O2")).toBeInTheDocument();
  });
});

describe("QuestionCard — with content (evidence has question)", () => {
  const evidenceWithQuestion: QuestionEvidence = makeEvidence({
    processing: "ended",
    content: { receipt: "final", revision: 1, question: sampleQuestion, phase: "verified" },
    terminal: {
      termination_reason: "normal",
      has_final: true,
      final_revision: 1,
      delivery_status: "complete",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "passed", content_revision: 1 },
    },
    review: { status: "passed", revision: 1 },
  });

  it("renders the question content when evidence has a question", () => {
    render(<QuestionCard evidence={evidenceWithQuestion} question={sampleQuestion} index={0} />);
    expect(screen.getByTestId("question-card-content")).toBeInTheDocument();
  });

  it("shows 審題略過 for skipped review (not 通過)", () => {
    const ev = makeEvidence({
      processing: "ended",
      content: { receipt: "final", revision: 1, question: sampleQuestion, phase: "verified" },
      terminal: {
        termination_reason: "normal", has_final: true, final_revision: 1,
        delivery_status: "complete", expected: [], delivered: [], missing: [],
        review: { status: "skipped", content_revision: 1 },
      },
      review: { status: "skipped", revision: 1 },
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);
    expect(screen.getByTestId("evidence-review-status")).toHaveTextContent("審題略過");
    expect(screen.queryByText("審題通過")).not.toBeInTheDocument();
  });

  it("shows 結果待接收 when terminal has_final but final not received", () => {
    const ev = makeEvidence({
      processing: "ended",
      content: { receipt: "draft", revision: 1, question: sampleQuestion, phase: "draft" },
      terminal: {
        termination_reason: "normal", has_final: true, final_revision: 2,
        delivery_status: "complete", expected: [], delivered: [], missing: [],
        review: { status: "passed", content_revision: 2 },
      },
      review: { status: "passed", revision: 2 },
      finalPending: true,
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);
    expect(screen.getByTestId("evidence-receipt-status")).toHaveTextContent("結果待接收");
  });

  it("shows 狀態未知 processing and renders the question when closed without terminal", () => {
    const ev = makeEvidence({
      processing: "unknown",
      content: { receipt: "final", revision: 1, question: sampleQuestion, phase: "verified" },
      terminal: null,
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);
    expect(screen.getByTestId("evidence-processing-status")).toHaveTextContent("狀態未知");
    // Question should still be rendered
    expect(screen.getByTestId("question-card-content")).toBeInTheDocument();
  });
});
