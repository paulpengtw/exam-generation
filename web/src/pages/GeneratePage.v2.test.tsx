/**
 * F4: GeneratePage v2 evidence rendering tests.
 * Verifies that when runEvidence is present, cards are rendered in manifest order,
 * placeholders shown for not-yet-filled questions, and filled content shown for done ones.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { RunEvidenceState } from "../lib/generationEvidence";
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
});
