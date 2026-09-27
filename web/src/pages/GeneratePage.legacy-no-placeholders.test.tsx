/**
 * C1/S0 — GeneratePage must NOT render placeholder cards in legacy mode.
 *
 * When runEvidence is null (legacy stream, no v2 manifest), GeneratePage must
 * render only displayResults cards (selectLegacyItems output), never the
 * per-question placeholder cards that are driven by a RunEvidenceState manifest.
 *
 * This is the GeneratePage-level assertion for the compatibility matrix cell
 * C1 × S0: "no placeholder cards without a manifest".
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Minimal mock GeneratedQuestion items (what useGenerate returns in displayResults)
// ---------------------------------------------------------------------------

const LEGACY_GQ1 = {
  index: 0,
  isFinal: true,
  phase: "verified",
  question: {
    id: "legacy_001",
    情境: ["個人"],
    題型種類: "單一題",
    題型: "選擇題",
    題目: ["Legacy Q1 final"],
    正確解題分析: ["answer"],
  },
};

const LEGACY_GQ2 = {
  index: 1,
  isFinal: true,
  phase: "verified",
  question: {
    id: "legacy_002",
    情境: ["社會時事"],
    題型種類: "單一題",
    題型: "選擇題",
    題目: ["Legacy Q2 final"],
    正確解題分析: ["answer2"],
  },
};

// Raw question (used only where the v2 evidence shape needs a question object)
const LEGACY_Q2 = LEGACY_GQ2.question;

// ---------------------------------------------------------------------------
// Shared mock state (mutated per test)
// ---------------------------------------------------------------------------

const generateState = vi.hoisted(() => ({
  displayResults: [] as unknown[],
  runEvidence: null as null | Record<string, unknown>,
}));

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: "idle" as const,
    progressLines: [],
    results: generateState.displayResults,
    displayResults: generateState.displayResults,
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: null,
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GeneratePage — C1 × S0: no placeholder cards in legacy mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    generateState.displayResults = [];
    generateState.runEvidence = null;
  });

  it("renders zero placeholder cards when runEvidence is null and displayResults is empty", () => {
    generateState.runEvidence = null;
    generateState.displayResults = [];
    render(<GeneratePage subject="math" />);
    const placeholders = document.querySelectorAll("[data-testid='question-card-placeholder']");
    expect(placeholders).toHaveLength(0);
  });

  it("renders legacy result cards without placeholder cards when runEvidence is null", () => {
    generateState.runEvidence = null;
    generateState.displayResults = [LEGACY_GQ1, LEGACY_GQ2];
    render(<GeneratePage subject="math" />);

    // No placeholder cards — legacy mode never pre-allocates manifest slots
    const placeholders = document.querySelectorAll("[data-testid='question-card-placeholder']");
    expect(placeholders).toHaveLength(0);

    // The two legacy result cards must be rendered (content cards)
    const contentCards = document.querySelectorAll("[data-testid='question-card-content']");
    expect(contentCards).toHaveLength(2);
  });

  it("still renders zero placeholder cards with one legacy result and null evidence", () => {
    generateState.runEvidence = null;
    generateState.displayResults = [LEGACY_GQ1];
    render(<GeneratePage subject="math" />);

    const placeholders = document.querySelectorAll("[data-testid='question-card-placeholder']");
    expect(placeholders).toHaveLength(0);

    const contentCards = document.querySelectorAll("[data-testid='question-card-content']");
    expect(contentCards).toHaveLength(1);
  });

  it("placeholder cards only appear when runEvidence provides a manifest (v2 mode)", () => {
    // Contrast: with runEvidence (v2 mode), placeholders ARE expected.
    // This is an explicit cross-mode comparison to confirm the conditional is wired.
    // We set a minimal runEvidence with one waiting question and one filled question.
    generateState.runEvidence = {
      runId: "RUN",
      total: 2,
      order: ["q_RUN_001", "q_RUN_002"],
      questions: {
        q_RUN_001: {
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
        },
        q_RUN_002: {
          questionId: "q_RUN_002",
          index: 1,
          processing: "ended",
          content: {
            receipt: "final",
            revision: 1,
            question: LEGACY_Q2,
            phase: "verified",
          },
          terminal: null,
          finalPending: false,
          finalMissing: false,
          review: { status: "passed", revision: 1 },
          trail: [],
          figurePolicyTrail: [],
          referenceExampleRecord: undefined,
        },
      },
      closed: false,
      degraded: false,
      degradedReason: null,
      batchConflict: false,
      batchConflictReason: null,
      legacyMixed: false,
    } as unknown as never;
    generateState.displayResults = [];
    render(<GeneratePage subject="math" />);

    // v2 mode: placeholder expected for the waiting question
    const placeholders = document.querySelectorAll("[data-testid='question-card-placeholder']");
    expect(placeholders).toHaveLength(1);
  });
});
