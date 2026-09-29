/**
 * Tests for build-admission gate wired into useGenerate (issue #771), on the
 * detached-run transport (issue #908): submit with POST /api/generate, then
 * poll GET /api/runs/{id}.
 *
 * Covers:
 * 1. Preflight rejects on "update-required" / "paused" / "unavailable" — no HTTP request sent
 * 2. X-Frontend-Build-ID header is sent when preflight passes
 * 3. 426 / 503 / 414 / 422 responses preserve existing results
 * 4. resultsCompletion / terminalEvidence survive a later rejection
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.stubGlobal("__BUILD_ID__", "test-build-abc");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "test");

vi.mock("@sentry/react", () => ({
  captureException: vi.fn(),
}));

vi.mock("../sentry", () => ({
  isSentryEnabled: vi.fn().mockReturnValue(false),
}));

import { useGenerate, type AdmissionOutcome } from "./useGenerate";
import { useReleaseStore, resetReleaseDetector } from "../lib/release/releaseStore";
import { useAuthStore } from "../store/authStore";
import { installFakeRunServer, type FakeRunServer } from "../test/fakeRunServer";
import { endedQuestion, examQuestion, runSnapshot } from "../test/runFixtures";

function setReleaseStatus(status: "current" | "update-required" | "paused" | "unavailable" | "checking") {
  useReleaseStore.setState({ status, lastCheckedAt: Date.now(), lastFailure: null });
}

let server: FakeRunServer;

/** Let a resolved fetch / Response.json() chain and any due timers run. */
async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  server = installFakeRunServer();
  resetReleaseDetector();
  // Use "checking" so generate() always calls checkNow() — the individual tests
  // spy on or directly set the final status.
  useReleaseStore.setState({
    status: "checking",
    requiredBuildId: null,
    releaseRevision: null,
    lastCheckedAt: null,
    lastFailure: null,
  });
});

afterEach(() => {
  server.restore();
  vi.useRealTimers();
  vi.restoreAllMocks();
  resetReleaseDetector();
});

/** Run one generation to its end so results and completion evidence exist. */
async function completeFirstRun(result: { current: ReturnType<typeof useGenerate> }) {
  const previousQuestion = examQuestion("q-1", "previous");
  server.setSnapshot("run-1", runSnapshot([endedQuestion("q-1", { question: previousQuestion })]));
  act(() => {
    void result.current.generate({ subject: "math", count: 1 });
  });
  await flush();
  await flush(3_000);
  return previousQuestion;
}

describe("useGenerate — build admission preflight", () => {
  it.each([
    ["update-required", "介面版本已更新"],
    ["paused", "暫停維護中"],
    ["unavailable", "無法確認介面版本"],
  ] as const)("rejects on %s without sending any request", async (releaseStatus, expectedText) => {
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus(releaseStatus);
    });

    const { result } = renderHook(() => useGenerate());
    let promise!: Promise<AdmissionOutcome>;
    await act(async () => {
      promise = result.current.generate({ subject: "math" });
    });

    const outcome = await promise;
    expect(outcome).toEqual(expect.objectContaining({ outcome: "rejected" }));
    expect(result.current.admission).toBe("rejected");
    expect(result.current.admissionError).toContain(expectedText);
    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toContain(expectedText);
    expect(server.requests).toHaveLength(0);
  });

  it("rechecks an unavailable release and submits when the policy becomes current", async () => {
    setReleaseStatus("unavailable");
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("current");
    });

    const { result } = renderHook(() => useGenerate());
    act(() => {
      void result.current.generate({ subject: "math" });
    });
    await flush();

    expect(server.submits()).toHaveLength(1);
    expect(server.submits()[0].headers["x-frontend-build-id"]).toBe("test-build-abc");
  });

  it("rejects an unavailable release again when rechecking still fails", async () => {
    setReleaseStatus("unavailable");
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("unavailable");
    });

    const { result } = renderHook(() => useGenerate());
    let promise!: Promise<AdmissionOutcome>;
    await act(async () => {
      promise = result.current.generate({ subject: "math" });
    });

    await expect(promise).resolves.toEqual(expect.objectContaining({ outcome: "rejected" }));
    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toContain("無法確認介面版本");
    expect(server.requests).toHaveLength(0);
  });

  it("accepts a retry after an admission rejection", async () => {
    setReleaseStatus("unavailable");
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("unavailable");
    });

    const { result } = renderHook(() => useGenerate());
    let rejected!: Promise<AdmissionOutcome>;
    await act(async () => {
      rejected = result.current.generate({ subject: "math" });
    });
    await expect(rejected).resolves.toEqual(expect.objectContaining({ outcome: "rejected" }));

    setReleaseStatus("current");
    act(() => {
      void result.current.generate({ subject: "math" });
    });
    expect(server.submits()).toHaveLength(1);
  });

  it("sends X-Frontend-Build-ID and stream_version 3 when preflight passes (current)", async () => {
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("current");
    });

    const { result } = renderHook(() => useGenerate());
    act(() => {
      void result.current.generate({ subject: "math" });
    });
    await flush();

    expect(server.submits()).toHaveLength(1);
    const [submit] = server.submits();
    expect(submit.headers["x-frontend-build-id"]).toBe("test-build-abc");
    expect((submit.body as { stream_version: number }).stream_version).toBe(3);
  });

  it("sends a long payload in the POST body with the build header", async () => {
    setReleaseStatus("current");
    const { result } = renderHook(() => useGenerate());
    act(() => {
      void result.current.generate({
        subject: "math",
        text_instruction: "x".repeat(12_000),
      });
    });
    await flush();

    const [submit] = server.submits();
    expect(submit.method).toBe("POST");
    expect(JSON.stringify(submit.body).length).toBeGreaterThan(12_000);
    expect(submit.headers["x-frontend-build-id"]).toBe("test-build-abc");
  });

  it("ignores a duplicate click while the first submission is still pending", async () => {
    setReleaseStatus("current");
    const { result } = renderHook(() => useGenerate());

    let first!: Promise<AdmissionOutcome>;
    let duplicate!: Promise<AdmissionOutcome>;
    act(() => {
      first = result.current.generate({ subject: "math" });
      duplicate = result.current.generate({ subject: "math" });
    });

    expect(server.submits()).toHaveLength(1);
    await expect(duplicate).resolves.toEqual(
      expect.objectContaining({ outcome: "rejected" }),
    );
    await flush();
    await expect(first).resolves.toEqual({ outcome: "admitted", runId: "run-1" });
  });

  it("keeps the existing signout behavior for a pre-acceptance 401", async () => {
    setReleaseStatus("current");
    const logout = vi.spyOn(useAuthStore.getState(), "logout");
    server.failSubmit(401, { detail: "Unauthorized" });

    const { result } = renderHook(() => useGenerate());
    let rejected!: Promise<AdmissionOutcome>;
    act(() => {
      rejected = result.current.generate({ subject: "math" });
    });
    await flush();

    await expect(rejected).resolves.toEqual(
      expect.objectContaining({ outcome: "rejected" }),
    );
    expect(logout).toHaveBeenCalledOnce();
    logout.mockRestore();
  });

  it.each([
    [414, {}],
    [422, { detail: "bad request" }],
    [426, { code: "CLIENT_UPDATE_REQUIRED", required_build_id: "new-build" }],
    [503, { code: "AUTHORITY_UNAVAILABLE" }],
  ])(
    "preserves prior results and completion on a pre-acceptance HTTP %s error",
    async (status, body) => {
      setReleaseStatus("current");
      const { result } = renderHook(() => useGenerate());
      const previousQuestion = await completeFirstRun(result);
      expect(result.current.results).toEqual([previousQuestion]);
      expect(result.current.resultsCompletion).toBe("settled");
      expect(result.current.terminalEvidence).toBe(true);

      server.failSubmit(status, body);
      let rejected!: Promise<AdmissionOutcome>;
      await act(async () => {
        rejected = result.current.generate({ subject: "math" });
        await Promise.resolve();
      });
      await flush();

      await expect(rejected).resolves.toEqual(expect.objectContaining({ outcome: "rejected" }));
      expect(result.current.status).toBe("error");
      expect(result.current.admission).toBe("rejected");
      expect(result.current.results).toEqual([previousQuestion]);
      expect(result.current.displayResults).toHaveLength(1);
      // Completion state travels with the preserved results (not clobbered).
      expect(result.current.resultsCompletion).toBe("settled");
      expect(result.current.terminalEvidence).toBe(true);
    },
  );

  it("keeps admission out of the admitted state when the update-required 426 arrives after preflight", async () => {
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockResolvedValue(undefined);
    setReleaseStatus("current");
    server.failSubmit(426, { code: "CLIENT_UPDATE_REQUIRED", required_build_id: "build-xyz" });

    const { result } = renderHook(() => useGenerate());
    act(() => {
      void result.current.generate({ subject: "math" });
    });
    await flush();

    expect(result.current.admission).not.toBe("admitted");
    expect(server.submits()).toHaveLength(1);
  });

  it("(b) a run the server reports failed sets resultsCompletion='error'", async () => {
    setReleaseStatus("current");
    const { result } = renderHook(() => useGenerate());
    server.setSnapshot("run-1", runSnapshot(
      [endedQuestion("q-1", { reason: "failed" })],
      { status: "failed", error: "Something went wrong" },
    ));

    act(() => {
      void result.current.generate({ subject: "math" });
    });
    await flush();
    await flush(3_000);

    expect(result.current.resultsCompletion).toBe("error");
    expect(result.current.errorMessage).toBe("Something went wrong");
  });
});
