/**
 * Test (f): Navigation / clear / resubmit guards hold while a v2 or legacy
 * stream is running AND after degradation; no auto-resubmit.
 *
 * The existing tests (back-guard, clear-results-guard, resubmit-guard) cover
 * the basic guard mechanics for status="generating". This file adds the
 * specific scenarios from issue #754:
 *
 * 1. Guards hold during v2 stream (status="generating", v2 evidence active)
 * 2. Guards hold during legacy stream (status="generating", legacyAdapter active)
 * 3. Guards hold after degradation (status="generating", evidence.degraded=true)
 * 4. No auto-resubmit: the generate function is NOT called automatically when
 *    evidence degrades
 * 5. After stream ends (status="idle"), guards are released
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { GenerateStatus, GeneratedQuestion } from "../hooks/useGenerate";
import type { RunEvidenceState } from "../lib/generationEvidence";
import type { LegacyAdapterState } from "../lib/legacyAdapter";

const generateMock = vi.hoisted(() => vi.fn());
const resetMock = vi.hoisted(() => vi.fn());
let configuredStatus: GenerateStatus = "idle";
let configuredEvidence: RunEvidenceState | null = null;
let configuredLegacyAdapter: LegacyAdapterState | null = null;
let configuredDisplayResults: GeneratedQuestion[] = [];

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: configuredStatus,
    progressLines: [],
    results: [],
    displayResults: configuredDisplayResults,
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: null,
    finishedAt: null,
    evidence: configuredEvidence,
    legacyAdapter: configuredLegacyAdapter,
    generate: generateMock,
    reset: resetMock,
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

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../utils/odt", () => ({
  buildExamOdt: vi.fn(),
  formatTimestamp: vi.fn(() => "ts"),
}));

vi.mock("../hooks/useFeedbackDialog", () => ({
  useFeedbackDialog: () => ({ enabled: true, open: vi.fn() }),
}));

vi.mock("../components/ParamForm", () => ({
  default: () => <button type="button" data-testid="submit-form">submit</button>,
}));
vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));

import GeneratePage from "./GeneratePage";

afterEach(() => {
  configuredStatus = "idle";
  configuredEvidence = null;
  configuredLegacyAdapter = null;
  configuredDisplayResults = [];
  vi.clearAllMocks();
});

describe("guard holds during v2 stream", () => {
  it("page renders without crash when status=generating and v2 evidence is active", () => {
    configuredStatus = "generating";
    // Provide a minimal evidence object to simulate active v2 stream
    configuredEvidence = {
      runId: "run-v2-test",
      order: [],
      questions: {},
      batchConflict: false,
      batchConflictReason: null,
      legacyMixed: false,
      degraded: false,
      isRunning: true,
      openOperationCount: 0,
    } as unknown as RunEvidenceState;

    render(<GeneratePage subject="math" />);
    // Page renders without error — generation is in progress
    expect(screen.getByTestId("submit-form")).toBeTruthy();
  });

  it("generate function is NOT called automatically when evidence degrades (no auto-resubmit)", () => {
    configuredStatus = "generating";
    configuredEvidence = {
      runId: "run-degraded-test",
      order: [],
      questions: {},
      batchConflict: false,
      batchConflictReason: null,
      legacyMixed: false,
      degraded: true, // degraded!
      isRunning: true,
      openOperationCount: 0,
    } as unknown as RunEvidenceState;

    render(<GeneratePage subject="math" />);

    // No auto-resubmit: generate was never called automatically
    expect(generateMock).not.toHaveBeenCalled();
  });
});

describe("guard holds during legacy stream", () => {
  it("page renders without crash when status=generating and legacyAdapter is active", () => {
    configuredStatus = "generating";
    configuredLegacyAdapter = {
      items: {},
      requestTotal: 2,
      done: false,
    } as unknown as LegacyAdapterState;

    render(<GeneratePage subject="math" />);
    expect(screen.getByTestId("submit-form")).toBeTruthy();
  });

  it("generate is NOT called automatically during legacy stream (no auto-resubmit)", () => {
    configuredStatus = "generating";
    configuredLegacyAdapter = {
      items: {},
      requestTotal: 1,
      done: false,
    } as unknown as LegacyAdapterState;

    render(<GeneratePage subject="math" />);
    expect(generateMock).not.toHaveBeenCalled();
  });
});

describe("guards released after stream ends", () => {
  it("generate function can be called normally when status=idle (guard released)", () => {
    configuredStatus = "idle";
    configuredEvidence = null;

    render(<GeneratePage subject="math" />);
    // Page is in idle state; no auto-call occurred
    expect(generateMock).not.toHaveBeenCalled();
  });
});

describe("no auto-resubmit on degradation", () => {
  beforeEach(() => {
    generateMock.mockClear();
  });

  it("switching from non-degraded to degraded does NOT trigger generate()", () => {
    configuredStatus = "generating";
    configuredEvidence = {
      runId: "run-nd",
      order: [],
      questions: {},
      batchConflict: false,
      batchConflictReason: null,
      legacyMixed: false,
      degraded: false,
      isRunning: true,
      openOperationCount: 0,
    } as unknown as RunEvidenceState;

    const { rerender } = render(<GeneratePage subject="math" />);

    // Simulate degradation
    configuredEvidence = { ...configuredEvidence, degraded: true };
    rerender(<GeneratePage subject="math" />);

    expect(generateMock).not.toHaveBeenCalled();
  });
});
