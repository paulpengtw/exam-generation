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

  it("does not show a newer terminal verdict on an older draft", () => {
    const ev = makeEvidence({
      processing: "ended",
      content: { receipt: "draft", revision: 1, question: sampleQuestion, phase: "image" },
      terminal: {
        termination_reason: "normal", has_final: true, final_revision: 2,
        delivery_status: "complete", expected: [], delivered: [], missing: [],
        review: { status: "passed", content_revision: 2 },
      },
      review: {
        status: "unknown",
        revision: 2,
        pending: true,
        reason: "waiting for matching final content",
      },
      finalPending: true,
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);
    expect(screen.getByTestId("evidence-review-status")).toHaveTextContent(
      /審題結果待對應內容版本|Review pending matching content version/,
    );
    expect(screen.getByTestId("evidence-review-status")).not.toHaveTextContent("審題通過");
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

  it("keeps a failed terminal's no-result conclusion separate from a received draft", () => {
    const ev = makeEvidence({
      processing: "ended",
      content: { receipt: "draft", revision: 1, question: sampleQuestion, phase: "draft" },
      terminal: {
        termination_reason: "failed", has_final: false, final_revision: null,
        delivery_status: "none", expected: [], delivered: [], missing: [],
        review: { status: "unknown", reason: "no final content" },
      },
      review: { status: "unknown", revision: null },
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);

    expect(screen.getByTestId("question-card-content")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-receipt-status")).toHaveTextContent(/草稿|draft/i);
    expect(screen.getByTestId("evidence-delivery-status")).toHaveTextContent(/無結果|none/i);
  });

  it("shows conflicted termination evidence as unknown while retaining content", () => {
    const ev = makeEvidence({
      processing: "unknown",
      content: { receipt: "final", revision: 1, question: sampleQuestion, phase: "verified" },
      terminalConflict: true,
      terminalConflictReason: "terminal_contradiction",
      review: { status: "unknown", revision: 1 },
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);

    expect(screen.getByTestId("evidence-processing-status")).toHaveTextContent(/狀態未知|unknown/i);
    expect(screen.getByTestId("evidence-terminal-conflict")).toBeInTheDocument();
    expect(screen.getByTestId("question-card-content")).toBeInTheDocument();
  });

  it("keeps an undisputed terminal ended when only review evidence conflicts", () => {
    const ev = makeEvidence({
      processing: "ended",
      content: { receipt: "final", revision: 1, question: sampleQuestion, phase: "verified" },
      terminal: {
        termination_reason: "normal", has_final: true, final_revision: 1,
        delivery_status: "complete", expected: [], delivered: [], missing: [],
        review: { status: "passed", content_revision: 1 },
      },
      reviewConflict: true,
      review: { status: "unknown", revision: 1, reason: "review_contradiction" },
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);

    expect(screen.getByTestId("evidence-processing-status")).toHaveTextContent(/已結束|ended/i);
    expect(screen.getByTestId("evidence-review-conflict")).toBeInTheDocument();
    expect(screen.getByTestId("evidence-review-status")).toHaveTextContent(/審題未知|unknown/i);
  });
});

// ---------------------------------------------------------------------------
// Gap 2: specific conflict reason codes rendered on card (#749)
// ---------------------------------------------------------------------------

describe("QuestionCard — specific conflict reason codes (Gap 2)", () => {
  it("shows localized reason for content conflict with same_revision_different_content code", () => {
    const ev = makeEvidence({
      content: { receipt: "draft", revision: 1, question: sampleQuestion, phase: null },
      contentConflict: true,
      contentConflictReason: "same_revision_different_content",
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);

    const conflictEl = screen.getByTestId("evidence-content-conflict");
    expect(conflictEl).toBeInTheDocument();
    // Reason sub-element is present and shows localized text
    const reasonEl = screen.getByTestId("evidence-content-conflict-reason");
    expect(reasonEl).toBeInTheDocument();
    expect(reasonEl).toHaveTextContent(/same revision|Same revision/i);
  });

  it("shows localized reason for content conflict with identity_mismatch code", () => {
    const ev = makeEvidence({
      content: { receipt: "none", revision: null, question: null, phase: null },
      contentConflict: true,
      contentConflictReason: "identity_mismatch",
    });
    render(<QuestionCard evidence={ev} index={0} />);

    const reasonEl = screen.getByTestId("evidence-content-conflict-reason");
    expect(reasonEl).toHaveTextContent(/identity|mismatch/i);
  });

  it("shows localized reason for terminal conflict with terminal_contradiction code", () => {
    const ev = makeEvidence({
      processing: "unknown",
      content: { receipt: "final", revision: 1, question: sampleQuestion, phase: "verified" },
      terminalConflict: true,
      terminalConflictReason: "terminal_contradiction",
      review: { status: "unknown", revision: 1 },
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);

    const conflictEl = screen.getByTestId("evidence-terminal-conflict");
    expect(conflictEl).toHaveAttribute("role", "status");
    const reasonEl = screen.getByTestId("evidence-terminal-conflict-reason");
    expect(reasonEl).toHaveTextContent(/contradictory terminal|Contradictory/i);
  });

  it("shows localized reason for terminal_invalid code", () => {
    const ev = makeEvidence({
      processing: "unknown",
      terminalConflict: true,
      terminalConflictReason: "terminal_invalid",
      review: { status: "unknown", revision: null, reason: "terminal_invalid" },
    });
    render(<QuestionCard evidence={ev} index={0} />);

    const reasonEl = screen.getByTestId("evidence-terminal-conflict-reason");
    expect(reasonEl).toHaveTextContent(/invalid terminal|Invalid/i);
  });

  it("shows localized reason for review_contradiction on review conflict", () => {
    const ev = makeEvidence({
      processing: "ended",
      content: { receipt: "final", revision: 1, question: sampleQuestion, phase: "verified" },
      terminal: {
        termination_reason: "normal", has_final: true, final_revision: 1,
        delivery_status: "complete", expected: [], delivered: [], missing: [],
        review: { status: "passed", content_revision: 1 },
      },
      reviewConflict: true,
      review: { status: "unknown", revision: 1, reason: "review_contradiction" },
    });
    render(<QuestionCard evidence={ev} question={sampleQuestion} index={0} />);

    const conflictEl = screen.getByTestId("evidence-review-conflict");
    expect(conflictEl).toHaveAttribute("role", "status");
    const reasonEl = screen.getByTestId("evidence-review-conflict-reason");
    expect(reasonEl).toHaveTextContent(/contradictory review|Contradictory/i);
  });

  it("conflict elements have role=status for accessibility", () => {
    const ev = makeEvidence({
      contentConflict: true,
      contentConflictReason: "seq_data",
    });
    render(<QuestionCard evidence={ev} index={0} />);
    const el = screen.getByTestId("evidence-content-conflict");
    expect(el).toHaveAttribute("role", "status");
  });
});
