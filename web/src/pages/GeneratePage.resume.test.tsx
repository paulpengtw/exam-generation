/**
 * Detached runs on the real page (issue #908): submitting keeps `?run=<id>` in
 * the URL, and opening/reloading a URL that carries it resumes watching that
 * run — progress first, then results — without ever cancelling anything.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouteObject, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
          grade: 7, count: 2, context: [], q_type: [], set_type: "單一題",
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

function search(router: ReturnType<typeof createMemoryRouter>): string {
  return router.state.location.search;
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

describe("GeneratePage — detached run in the URL", () => {
  it("keeps ?run=<id> in the URL once the run is accepted", async () => {
    server.setAcceptance(acceptedRun(2, "run-7"));
    server.setSnapshot("run-7", runSnapshot(
      [waitingQuestion("q-1"), waitingQuestion("q-2")],
      { run_id: "run-7" },
    ));
    const { router } = renderPage(ROUTE);
    expect(search(router)).toBe("");

    fireEvent.click(await screen.findByRole("button", { name: "Start generation" }));

    await waitFor(() => expect(search(router)).toBe("?run=run-7"));
    expect(server.submits()).toHaveLength(1);
    // The URL param does not trigger a second acceptance or a resume fetch.
    expect(server.submits()).toHaveLength(1);
    expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("0/2");
  });

  it("resumes a reopened run: shows it progressing, then its results", async () => {
    server.setSnapshot("run-1", runSnapshot([
      endedQuestion("q-1", { question: examQuestion("q-1", "already finished") }),
      runningQuestion("q-2", "verify"),
    ]));
    const { router } = renderPage(`${ROUTE}?run=run-1`);

    // Progress from the persisted state: one ended, one still running.
    await waitFor(() => expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("1/2"));
    expect(screen.getByTestId("statusbar-v2-final")).toHaveTextContent("1");
    expect(screen.getByText("already finished")).toBeInTheDocument();
    expect(server.submits()).toHaveLength(0);
    expect(search(router)).toBe("?run=run-1");
    expect(screen.getByRole("button", { name: "Start generation" })).toBeDisabled();

    // The run finishes while the page is open: results appear on the next poll.
    server.setSnapshot("run-1", runSnapshot([
      endedQuestion("q-1", { question: examQuestion("q-1", "already finished") }),
      endedQuestion("q-2", { question: examQuestion("q-2", "arrived after reopen") }),
    ]));
    await waitFor(
      () => expect(screen.getByText("arrived after reopen")).toBeInTheDocument(),
      { timeout: 8000 },
    );
    expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("2/2");
    expect(screen.getByRole("button", { name: "Start generation" })).not.toBeDisabled();
    // Only reads happened: nothing was cancelled or restarted.
    expect(server.requests.every((r) => r.method === "GET")).toBe(true);
  }, 15_000);

  it("shows the results at once when the reopened run had already ended", async () => {
    server.setSnapshot("run-1", runSnapshot([
      endedQuestion("q-1", { question: examQuestion("q-1", "done long ago") }),
    ]));
    renderPage(`${ROUTE}?run=run-1`);

    expect(await screen.findByText("done long ago")).toBeInTheDocument();
    expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("1/1");
  });

  it("closing the page mid-run sends nothing; reopening resumes the same run", async () => {
    server.setSnapshot("run-1", runSnapshot([runningQuestion("q-1", "text")]));
    const first = renderPage(`${ROUTE}?run=run-1`);
    await waitFor(() => expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("0/1"));
    const requestsBeforeClose = server.requests.length;

    first.unmount();
    expect(server.requests).toHaveLength(requestsBeforeClose);

    server.setSnapshot("run-1", runSnapshot([
      endedQuestion("q-1", { question: examQuestion("q-1", "finished while closed") }),
    ]));
    renderPage(`${ROUTE}?run=run-1`);
    expect(await screen.findByText("finished while closed")).toBeInTheDocument();
    expect(server.requests.every((r) => r.method === "GET")).toBe(true);
  });

  it("tells the user an unknown run was not found and clears the URL param", async () => {
    server.hideRun("nope");
    const { router } = renderPage(`${ROUTE}?run=nope`);

    const notice = await screen.findByTestId("run-not-found");
    expect(notice).toHaveTextContent(/could not be found|找不到/);
    await waitFor(() => expect(search(router)).toBe(""));
    expect(screen.getByRole("button", { name: "Start generation" })).not.toBeDisabled();
    // No polling continues for a run that does not exist.
    expect(server.polls()).toHaveLength(1);
  });

  it("clearing the results drops the param and stops watching, without cancelling the run", async () => {
    server.setSnapshot("run-1", runSnapshot([
      endedQuestion("q-1", { question: examQuestion("q-1", "to be cleared") }),
    ]));
    const { router } = renderPage(`${ROUTE}?run=run-1`);
    await screen.findByText("to be cleared");

    fireEvent.click(screen.getByRole("button", { name: "Clear results" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Clear" }));

    await waitFor(() => expect(search(router)).toBe(""));
    expect(screen.queryByText("to be cleared")).not.toBeInTheDocument();
    expect(server.requests.every((r) => r.method === "GET")).toBe(true);
  });
});
