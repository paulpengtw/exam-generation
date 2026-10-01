/**
 * Issue #910: Cancel button component tests.
 *
 * Covers:
 * - Cancel button is shown while status === "generating"
 * - Button label shows 取消中... while cancelRequested is true
 * - Button calls cancelRun when clicked and shows pending state
 * - Error feedback shown when cancelRun rejects
 * - Button hidden when status !== "generating"
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../utils/odt", () => ({
  buildOdtFromSnapshots: vi.fn().mockResolvedValue(new Blob()),
  formatTimestamp: () => "ts",
}));

vi.mock("../hooks/useGenerate", () => ({
  useGenerate: useGenerateMock,
}));

vi.mock("../lib/generationStream", () => ({
  projectGenerationCardEvidence: () => ({}),
  projectGenerationEvidence: () => null,
}));

vi.mock("../components/ParamForm", () => ({
  default: () => <div data-testid="param-form" />,
}));
vi.mock("../components/ProgressLog", () => ({ default: () => null }));
vi.mock("../components/QuestionCard", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../components/GenerationStatusBar", () => ({ default: () => null }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));
vi.mock("../hooks/useFeedbackDialog", () => ({
  useFeedbackDialog: () => ({ enabled: false, open: vi.fn() }),
}));
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));
vi.mock("../store/authStore", () => ({
  useAuthStore: (
    selector: (state: { user: null; logoutExplicit: () => void }) => unknown,
  ) => selector({ user: null, logoutExplicit: vi.fn() }),
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useLocation: () => ({ pathname: "/generate/math", state: null }),
    useBlocker: () => ({
      state: "unblocked",
      proceed: undefined,
      reset: undefined,
    }),
  };
});

import GeneratePage from "./GeneratePage";

/** Minimal UseGenerateReturn stub for "generating" state. */
function generatingReturn(overrides: Record<string, unknown> = {}) {
  return {
    status: "generating",
    progressLines: [],
    results: [],
    displayResults: [],
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: Date.now(),
    finishedAt: null,
    generationLogId: "run-abc",
    runId: "run-abc",
    subQuestionTotal: null,
    resultsCompletion: "pending",
    terminalEvidence: false,
    evidence: null,
    pollReadFailed: false,
    cancelRequested: false,
    cancelRun: vi.fn().mockResolvedValue(true),
    generate: vi.fn(),
    restoreResults: vi.fn(),
    reset: vi.fn(),
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/generate/math"]}>
      <Routes>
        <Route path="/generate/math" element={<GeneratePage subject="math" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.clearAllMocks();
});

describe("GeneratePage cancel button (issue #910)", () => {
  it("c1: shows the cancel button while status is generating", () => {
    useGenerateMock.mockReturnValue(generatingReturn());
    renderPage();
    expect(screen.getByTestId("cancel-run-btn")).toBeInTheDocument();
    expect(screen.getByTestId("cancel-run-btn")).toHaveTextContent("Cancel");
  });

  it("c2: does NOT show the cancel button when status is done", () => {
    useGenerateMock.mockReturnValue({
      ...generatingReturn(),
      status: "done",
      finishedAt: Date.now(),
      resultsCompletion: "complete",
    });
    renderPage();
    expect(screen.queryByTestId("cancel-run-btn")).not.toBeInTheDocument();
  });

  it("c3: shows 取消中... label when cancelRequested is true", () => {
    useGenerateMock.mockReturnValue(
      generatingReturn({ cancelRequested: true }),
    );
    renderPage();
    const btn = screen.getByTestId("cancel-run-btn");
    // The button should be disabled (server-side cancel pending)
    expect(btn).toBeDisabled();
    // Label shows the pending variant (en-US messages key: generate.btn_cancel_pending)
    expect(btn).toHaveTextContent(/Cancelling/i);
  });

  it("c4: clicking cancel calls cancelRun, shows pending label, then clears", async () => {
    let resolveCancel!: (v: boolean) => void;
    const cancelPromise = new Promise<boolean>((r) => { resolveCancel = r; });
    const cancelRun = vi.fn().mockReturnValue(cancelPromise);
    useGenerateMock.mockReturnValue(generatingReturn({ cancelRun }));

    renderPage();
    const btn = screen.getByTestId("cancel-run-btn");
    fireEvent.click(btn);

    // While the promise is pending the button should be disabled
    await waitFor(() => expect(btn).toBeDisabled());

    // Resolve the cancel; button should re-enable (no error)
    resolveCancel(true);
    await waitFor(() => expect(btn).not.toBeDisabled());
    expect(cancelRun).toHaveBeenCalledOnce();
  });

  it("c5: shows error notice when cancelRun rejects", async () => {
    const cancelRun = vi.fn().mockRejectedValue(new Error("server error"));
    useGenerateMock.mockReturnValue(generatingReturn({ cancelRun }));

    renderPage();
    fireEvent.click(screen.getByTestId("cancel-run-btn"));

    // An alert with error text should appear
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });

  it("c6: shows error when cancelRun returns false (run not found)", async () => {
    const cancelRun = vi.fn().mockResolvedValue(false);
    useGenerateMock.mockReturnValue(generatingReturn({ cancelRun }));

    renderPage();
    fireEvent.click(screen.getByTestId("cancel-run-btn"));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });
});
