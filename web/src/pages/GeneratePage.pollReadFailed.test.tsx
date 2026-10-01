/**
 * Tests for the pollReadFailed notice in GeneratePage (issue #909).
 *
 * When useGenerate returns pollReadFailed=true, GeneratePage renders a
 * role="status" element containing t("generate.run_read_unavailable"), and
 * questions with processing="unknown" show the card.unknown label.
 * When pollReadFailed=false the notice is absent.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { createRunEvidence, type RunEvidenceState } from "../lib/generationEvidence";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEvidenceWithUnknown(): RunEvidenceState {
  let state = createRunEvidence({
    runId: "RUN_PRF",
    total: 2,
    manifest: [
      { index: 0, questionId: "q_PRF_001" },
      { index: 1, questionId: "q_PRF_002" },
    ],
  });
  // Mark both questions as unknown (simulating applyPollReadFailed outcome)
  state = {
    ...state,
    questions: {
      ...state.questions,
      q_PRF_001: { ...state.questions.q_PRF_001, processing: "unknown" },
      q_PRF_002: { ...state.questions.q_PRF_002, processing: "unknown" },
    },
  };
  return state;
}

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const generateState = vi.hoisted(() => ({
  pollReadFailed: false,
  runEvidence: null as RunEvidenceState | null,
}));

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: "generating" as const,
    progressLines: [],
    results: [],
    displayResults: [],
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: Date.now(),
    finishedAt: null,
    subQuestionTotal: null,
    pollReadFailed: generateState.pollReadFailed,
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

describe("GeneratePage — pollReadFailed notice (issue #909)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    generateState.pollReadFailed = false;
    generateState.runEvidence = null;
  });

  it("shows run_read_unavailable notice when pollReadFailed=true", () => {
    generateState.pollReadFailed = true;
    generateState.runEvidence = makeEvidenceWithUnknown();
    render(<GeneratePage subject="math" />);
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("generate.run_read_unavailable");
  });

  it("does not show run_read_unavailable notice when pollReadFailed=false", () => {
    generateState.pollReadFailed = false;
    generateState.runEvidence = makeEvidenceWithUnknown();
    render(<GeneratePage subject="math" />);
    // The ReleaseNotice component also uses role="status" when checking/current/unavailable,
    // but since its store is not initialised here it will be absent. Verify no notice
    // with the specific run_read_unavailable message text is present.
    const allStatuses = screen.queryAllByRole("status");
    const hasUnreadableNotice = allStatuses.some((el) =>
      el.textContent?.includes("generate.run_read_unavailable"),
    );
    expect(hasUnreadableNotice).toBe(false);
  });

  it("shows card.unknown label for questions with processing=unknown when pollReadFailed=true", () => {
    generateState.pollReadFailed = true;
    generateState.runEvidence = makeEvidenceWithUnknown();
    render(<GeneratePage subject="math" />);
    // Both placeholder cards should render the "unknown" processing label
    const unknownLabels = screen.getAllByText("card.unknown");
    expect(unknownLabels.length).toBeGreaterThanOrEqual(2);
  });

  it("card.unknown absent for questions with processing=waiting when pollReadFailed=false", () => {
    // Without evidence or with normal waiting state, card.unknown label is not shown
    generateState.pollReadFailed = false;
    generateState.runEvidence = null;
    render(<GeneratePage subject="math" />);
    expect(screen.queryByText("card.unknown")).toBeNull();
  });
});
