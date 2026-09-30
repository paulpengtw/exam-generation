/**
 * Issue #912 — GeneratePage real-hook integration tests for admission features.
 *
 * Renders the REAL GeneratePage + REAL useGenerate against installFakeRunServer()
 * (no MSW).  Two scenarios:
 *
 * q1: snapshot {status:"queued", queue_position:2} → shows queue text with 2;
 *     next poll queue_position:0 → text shows 0; then status:"running" (no
 *     queue_position) → queue-position-notice disappears.
 *
 * q2: 429 submit with {code:"queue_limit_reached"} → localized limit message
 *     appears, submit button re-enabled (form is usable, status="error").
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
      data-testid="param-form-submit"
      onClick={() => {
        void onSubmit({
          grade: 7, count: 1, context: [], q_type: [], set_type: "單一題",
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
  runSnapshot,
  waitingQuestion,
  runningQuestion,
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

describe("GeneratePage queue features (issue #912)", () => {
  it("q1: queue-position-notice shows position, updates, and disappears when running", async () => {
    // Initial snapshot: queued with 2 ahead.
    server.setAcceptance(acceptedRun(1, "run-q1"));
    server.setSnapshot("run-q1", runSnapshot(
      [waitingQuestion("q-1")],
      { run_id: "run-q1", status: "queued", queue_position: 2 },
    ));

    renderPage(ROUTE);

    // Submit the form.
    fireEvent.click(await screen.findByRole("button", { name: "Start generation" }));
    await waitFor(() => expect(server.submits()).toHaveLength(1));

    // Wait for queue-position-notice to appear with position 2.
    const notice = await screen.findByTestId("queue-position-notice", {}, { timeout: 8000 });
    expect(notice).toHaveTextContent("2");

    // Update snapshot to queue_position 0.
    server.setSnapshot("run-q1", runSnapshot(
      [waitingQuestion("q-1")],
      { run_id: "run-q1", status: "queued", queue_position: 0 },
    ));

    await waitFor(
      () => expect(screen.getByTestId("queue-position-notice")).toHaveTextContent("0"),
      { timeout: 8000 },
    );

    // Update snapshot to "running" (no queue_position).
    server.setSnapshot("run-q1", runSnapshot(
      [runningQuestion("q-1", "text")],
      { run_id: "run-q1" },
    ));

    // Once the run is running the notice must disappear.
    await waitFor(
      () => expect(screen.queryByTestId("queue-position-notice")).not.toBeInTheDocument(),
      { timeout: 8000 },
    );
  }, 25_000);

  it("q2: 429 submit shows limit message and re-enables the form", async () => {
    server.failSubmit(429, {
      code: "queue_limit_reached",
      detail: "You already have the maximum number of queued generation runs.",
    });

    renderPage(ROUTE);

    const submitBtn = await screen.findByRole("button", { name: "Start generation" });

    // Click submit — the fake server will reply with 429.
    fireEvent.click(submitBtn);
    await waitFor(() => expect(server.submits()).toHaveLength(1));

    // A readable error message must appear.
    await waitFor(
      () => expect(
        screen.getByText(/maximum number of queued|最多數量的排隊/i)
      ).toBeInTheDocument(),
      { timeout: 8000 },
    );

    // The form submit button must be re-enabled (status is "error", not "generating").
    await waitFor(
      () => expect(screen.getByTestId("param-form-submit")).not.toBeDisabled(),
      { timeout: 5000 },
    );
  }, 20_000);
});
