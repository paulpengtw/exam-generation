/**
 * F4: GeneratePage v2 evidence rendering tests.
 * Verifies that when runEvidence is present, cards are rendered in manifest order,
 * placeholders shown for not-yet-filled questions, and filled content shown for done ones.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { applyV2Event, createRunEvidence, type RunEvidenceState } from "../lib/generationEvidence";
import type { ExamQuestion } from "../lib/generationEvidence";

// Build minimal RunEvidenceState with 2 questions, q_RUN_002 filled, q_RUN_001 waiting
function makeRunEvidence(overrides: Partial<RunEvidenceState> = {}): RunEvidenceState {
  const q1: RunEvidenceState["questions"][string] = {
    questionId: "q_RUN_001",
    index: 0,
    processing: "running",
    content: { receipt: "none", revision: null, question: null, phase: null },
    terminal: null,
    finalPending: false,
    finalMissing: false,
    review: { status: "unknown", revision: null },
    trail: [],
    figurePolicyTrail: [],
    referenceExampleRecord: undefined,
  };
  const sampleQ: ExamQuestion = {
    id: "q_RUN_002",
    情境: ["個人"],
    題型種類: "單一題",
    題型: "選擇題",
    題目: ["sample"],
    正確解題分析: ["answer"],
  };
  const q2: RunEvidenceState["questions"][string] = {
    questionId: "q_RUN_002",
    index: 1,
    processing: "ended",
    content: { receipt: "final", revision: 1, question: sampleQ, phase: "verified" },
    terminal: null,
    finalPending: false,
    finalMissing: false,
    review: { status: "passed", revision: 1 },
    trail: [],
    figurePolicyTrail: [],
    referenceExampleRecord: undefined,
  };
  return {
    runId: "RUN",
    total: 2,
    order: ["q_RUN_001", "q_RUN_002"],
    questions: { q_RUN_001: q1, q_RUN_002: q2 },
    closed: false,
    ...overrides,
  };
}

// Mock useGenerate to return runEvidence
const generateState = vi.hoisted(() => ({
  runEvidence: null as RunEvidenceState | null,
  displayResults: [] as unknown[],
}));

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: "generating" as const,
    progressLines: [],
    results: [],
    displayResults: generateState.displayResults,
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: Date.now(),
    finishedAt: null,
    subQuestionTotal: null,
    generate: vi.fn(),
    reset: vi.fn(),
    evidence: generateState.runEvidence,
  }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useLocation: () => ({ state: null }),
  useBlocker: () => ({ state: "unblocked", proceed: undefined, reset: undefined }),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: (selector: (s: { user: null; logout: () => void }) => unknown) =>
    selector({ user: null, logout: vi.fn() }),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../utils/odt", () => ({
  buildExamOdt: vi.fn(),
  formatTimestamp: vi.fn(() => "ts"),
}));

vi.mock("../components/ParamForm", () => ({
  default: () => <div data-testid="param-form" />,
}));

vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));
vi.mock("../components/GenerationStatusBar", () => ({
  default: () => <div data-testid="status-bar" />,
}));

import GeneratePage from "./GeneratePage";

describe("GeneratePage — v2 evidence rendering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    generateState.displayResults = [];
    generateState.runEvidence = null;
  });

  it("renders placeholder card for q_RUN_001 (waiting) and content card for q_RUN_002 (filled)", () => {
    generateState.runEvidence = makeRunEvidence();
    render(<GeneratePage subject="math" />);
    // Two cards total: one placeholder, one with content
    const placeholders = screen.getAllByTestId("question-card-placeholder");
    expect(placeholders).toHaveLength(1);
    const contents = screen.getAllByTestId("question-card-content");
    expect(contents).toHaveLength(1);
  });

  it("renders in manifest order: q_RUN_001 placeholder comes before q_RUN_002 content", () => {
    generateState.runEvidence = makeRunEvidence();
    const { container } = render(<GeneratePage subject="math" />);
    const allCards = container.querySelectorAll("[data-testid='question-card-placeholder'], [data-testid='question-card-content']");
    expect(allCards).toHaveLength(2);
    // First card is placeholder (q_RUN_001), second is content (q_RUN_002)
    expect(allCards[0].getAttribute("data-testid")).toBe("question-card-placeholder");
    expect(allCards[1].getAttribute("data-testid")).toBe("question-card-content");
  });

  it("shows 生成中 label for running placeholder", () => {
    generateState.runEvidence = makeRunEvidence();
    render(<GeneratePage subject="math" />);
    const placeholder = screen.getByTestId("question-card-placeholder");
    expect(placeholder).toHaveTextContent("card.generating");
  });

  it("keeps a partial grouped card in its manifest position with a fixed missing slot", () => {
    const base = makeRunEvidence();
    const partialQuestion = {
      ...base.questions.q_RUN_002.content.question,
      id: "q_RUN_002",
      核心問題: "group core",
      文本: "group passage",
      題目: [],
      正確解題分析: [],
      subquestions: [
        {
          id: "q_RUN_002-sq001", 序號: 1, 年級: 8, 科目: [], 核心素養: [],
          學習內容: [], 學習表現: [], 題型: "選擇題", 題目: "first",
        },
        {
          id: "q_RUN_002-sq003", 序號: 3, 年級: 8, 科目: [], 核心素養: [],
          學習內容: [], 學習表現: [], 題型: "選擇題", 題目: "third",
        },
      ],
    } as unknown as ExamQuestion;
    const q2 = base.questions.q_RUN_002;
    generateState.runEvidence = {
      ...base,
      questions: {
        ...base.questions,
        q_RUN_002: {
          ...q2,
          content: { receipt: "final", revision: 3, question: partialQuestion, phase: "verified" },
          terminal: {
            termination_reason: "normal",
            has_final: true,
            final_revision: 3,
            delivery_status: "partial",
            expected: [
              { kind: "subquestion", question_id: "q_RUN_002", subquestion_id: "q_RUN_002-sq001", subquestion_index: 0 },
              { kind: "subquestion", question_id: "q_RUN_002", subquestion_id: "q_RUN_002-sq002", subquestion_index: 1 },
              { kind: "subquestion", question_id: "q_RUN_002", subquestion_id: "q_RUN_002-sq003", subquestion_index: 2 },
            ],
            delivered: [
              { kind: "subquestion", question_id: "q_RUN_002", subquestion_id: "q_RUN_002-sq001", subquestion_index: 0 },
              { kind: "subquestion", question_id: "q_RUN_002", subquestion_id: "q_RUN_002-sq003", subquestion_index: 2 },
            ],
            missing: [
              { kind: "subquestion", question_id: "q_RUN_002", subquestion_id: "q_RUN_002-sq002", subquestion_index: 1, reason: "subquestion not delivered" },
            ],
            review: { status: "skipped", content_revision: 3 },
          },
          review: { status: "skipped", revision: 3 },
        },
      },
    };

    render(<GeneratePage subject="social_studies" />);

    expect(screen.getByTestId("question-card-placeholder")).toBeInTheDocument();
    expect(screen.getByTestId("missing-subquestion-2")).toBeInTheDocument();
    expect(screen.getByText("third")).toBeInTheDocument();
  });

  it("renders both fixed-position cards from the real social fixture replay", () => {
    const lines = readFileSync(
      resolve(__dirname, "../../../tests/fixtures/generation_v2/social_groups_interleaved.jsonl"),
      "utf-8",
    ).trim().split("\n").map((line) => JSON.parse(line) as {
      event: string;
      context: Record<string, unknown>;
      payload: Record<string, unknown>;
    });
    const started = lines[0];
    let state = createRunEvidence({
      runId: String(started.context.run_id),
      total: Number(started.payload.total),
      manifest: (started.payload.questions as Array<Record<string, unknown>>).map((question) => ({
        index: Number(question.index),
        questionId: String(question.question_id),
      })),
    });
    for (const line of lines.slice(1)) {
      state = applyV2Event(state, {
        kind: "v2",
        event: { name: line.event, context: line.context, payload: line.payload },
      });
    }
    generateState.runEvidence = state;

    render(<GeneratePage subject="social_studies" />);

    expect(screen.getAllByTestId("question-card-content")).toHaveLength(2);
    expect(screen.getByTestId("missing-subquestion-2")).toBeInTheDocument();
    expect(screen.getByText("文本 A")).toBeInTheDocument();
    expect(screen.getByText("文本 B")).toBeInTheDocument();
  });
});
