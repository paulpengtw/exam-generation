/**
 * Issue #910 — Cancel-flow integration tests.
 *
 * Renders the REAL GeneratePage + REAL useGenerate against installFakeRunServer()
 * (no MSW). Two scenarios:
 *
 * cf1: 3-question run (1 ended with result, 2 running) → click Cancel →
 *      取消中 visible immediately, server records exactly one cancel request,
 *      update snapshot (2 unfinished → cancelled, run status "cancelled") →
 *      next poll shows cancelled outcome for those two cards, ended question
 *      still shows its result, Cancel control is gone, submits count is 1.
 *
 * cf2: failCancel(500, …) → error alert shown and 取消中 reverted.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouteObject, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

vi.mock("@sentry/react", () => ({ captureException: vi.fn() }));
vi.mock("../sentry", () => ({ isSentryEnabled: () => false }));
vi.mock("../components/LanguageSwitcher", () => ({ default: () => null }));
vi.mock("../components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("../utils/odt", () => ({
  buildExamOdt: vi.fn(),
  buildOdtFromSnapshots: vi.fn(),
  formatTimestamp: () => "ts",
}));
// A deterministic submit button stands in for the real form.
vi.mock("../components/ParamForm", () => ({
  default: ({ onSubmit, disabled }: {
    onSubmit: (params: Record<string, unknown>) => Promise<unknown> | undefined;
    disabled?: boolean;
  }) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => {
        void onSubmit({
          grade: 7, count: 3, context: [], q_type: [], set_type: "單一題",
          image_generation_mode: "html", skip_verify: false,
        });
      }}
    >
      Start generation
    </button>
  ),
}));

vi.stubGlobal("__BUILD_ID__", "test-build");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "test");

import GeneratePage from "./GeneratePage";
import { useAuthStore } from "../store/authStore";
import { ReleaseState, useReleaseStore, resetReleaseDetector } from "../lib/release/releaseStore";
import { resetWorkspaceStoreForTests } from "../lib/workspace/workspaceStore";
import { resetRecoveryStoreForTests } from "../lib/recovery/recoveryStore";
import { installFakeRunServer, type FakeRunServer } from "../test/fakeRunServer";
import {
  acceptedRun,
  endedQuestion,
  examQuestion,
  runningQuestion,
  runSnapshot,
  terminalPayload,
  waitingQuestion,
} from "../test/runFixtures";

const USER = { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" };
const ROUTE = "/generate/math";

let server: FakeRunServer;

function renderPage(entry: string) {
  const routes: RouteObject[] = [
    { path: ROUTE, element: <GeneratePage subject="math" /> },
  ];
  const router = createMemoryRouter(routes, { initialEntries: [entry] });
  const rendered = render(<RouterProvider router={router} />);
  return { ...rendered, router };
}

/** A question snapshot row that ended with cancellation (no result delivered). */
function cancelledQuestion(id: string) {
  return {
    ...waitingQuestion(id),
    processing: "ended" as const,
    termination_reason: "cancelled",
    terminal: terminalPayload(null, "cancelled"),
    result: null,
  };
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  resetReleaseDetector();
  resetRecoveryStoreForTests();
  resetWorkspaceStoreForTests();
  useReleaseStore.setState({
    status: "current",
    requiredBuildId: null,
    releaseRevision: 1,
    supportedRecoveryFormats: [],
    lastCheckedAt: Date.now(),
    lastFailure: null,
    checkNow: async () => {},
  } as ReleaseState);
  useAuthStore.setState({ token: "token", user: USER });
  server = installFakeRunServer();
});

afterEach(() => {
  server.restore();
  vi.restoreAllMocks();
  resetReleaseDetector();
  resetRecoveryStoreForTests();
  resetWorkspaceStoreForTests();
});

describe("GeneratePage cancel-flow (issue #910)", () => {
  it("cf1: click Cancel shows 取消中 immediately, cancels exactly once, and the cancelled snapshot is rendered", async () => {
    // 3-question run: q-1 already ended with a result, q-2 and q-3 still running.
    server.setAcceptance(acceptedRun(3, "run-c1"));
    server.setSnapshot("run-c1", runSnapshot(
      [
        endedQuestion("q-1", { question: examQuestion("q-1", "q1 result") }),
        runningQuestion("q-2", "text"),
        runningQuestion("q-3", "verify"),
      ],
      { run_id: "run-c1" },
    ));

    renderPage(ROUTE);

    // Submit the form — the stub ParamForm uses count: 3.
    fireEvent.click(await screen.findByRole("button", { name: "Start generation" }));
    await waitFor(() => expect(server.submits()).toHaveLength(1));

    // Cancel button appears once the run is active.
    const cancelBtn = await screen.findByTestId("cancel-run-btn");
    expect(cancelBtn).toBeInTheDocument();
    expect(cancelBtn).not.toBeDisabled();

    // Click cancel → optimistic 取消中 visible immediately.
    fireEvent.click(cancelBtn);
    await waitFor(() => expect(cancelBtn).toBeDisabled());
    // The button label should reflect the pending/requested state.
    expect(cancelBtn).toHaveTextContent(/Cancelling|取消中/);

    // Exactly one cancel request was dispatched to the server.
    await waitFor(() => expect(server.cancels()).toHaveLength(1));
    expect(server.cancels()[0].url).toContain("run-c1");
    expect(server.cancels()[0].url).toContain("/cancel");

    // Now advance the server state: both unfinished questions are cancelled.
    server.setSnapshot("run-c1", runSnapshot(
      [
        endedQuestion("q-1", { question: examQuestion("q-1", "q1 result") }),
        cancelledQuestion("q-2"),
        cancelledQuestion("q-3"),
      ],
      { run_id: "run-c1", status: "cancelled" },
    ));

    // Wait for the next poll to apply the cancelled snapshot.
    await waitFor(
      () => expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("3/3"),
      { timeout: 8000 },
    );

    // Cancel control is gone once the run is terminal.
    expect(screen.queryByTestId("cancel-run-btn")).not.toBeInTheDocument();

    // The ended question still shows its result.
    expect(screen.getByText("q1 result")).toBeInTheDocument();

    // The two cancelled cards show the cancelled outcome as placeholder cards
    // with the 已取消 termination label.
    const placeholders = screen.getAllByTestId("question-card-placeholder");
    expect(placeholders).toHaveLength(2);
    const cancelledLabels = screen.getAllByText("已取消");
    expect(cancelledLabels).toHaveLength(2);

    // Only one generation request was ever submitted.
    expect(server.submits()).toHaveLength(1);
  }, 15_000);

  it("cf2: failCancel shows an error alert and reverts 取消中", async () => {
    server.setAcceptance(acceptedRun(3, "run-c2"));
    server.setSnapshot("run-c2", runSnapshot(
      [
        runningQuestion("q-1", "text"),
        runningQuestion("q-2", "text"),
        runningQuestion("q-3", "text"),
      ],
      { run_id: "run-c2" },
    ));
    // The next cancel request should fail with 500.
    server.failCancel(500, { detail: "internal server error" });

    renderPage(ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Start generation" }));
    await waitFor(() => expect(server.submits()).toHaveLength(1));

    // Wait for the cancel button and click it.
    const cancelBtn = await screen.findByTestId("cancel-run-btn");
    fireEvent.click(cancelBtn);

    // An error alert must appear (InlineFailureNotice or equivalent).
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    // The button must no longer be in the 取消中 / Cancelling state — it reverted.
    expect(cancelBtn).not.toHaveTextContent(/Cancelling|取消中/);
    expect(cancelBtn).not.toBeDisabled();
  }, 15_000);
});
