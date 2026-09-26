/**
 * Tests for build-admission gate wired into useGenerate (issue #771).
 *
 * Covers:
 * 1. Preflight rejects on "update-required" — no HTTP fetch sent
 * 2. Preflight rejects on "paused"
 * 3. Preflight rejects on "unavailable"
 * 4. X-Frontend-Build-ID header is sent when preflight passes
 * 5. 426 response preserves existing results
 * 6. 503 response preserves existing results
 */
import type { FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.stubGlobal("__BUILD_ID__", "test-build-abc");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "test");

const fetchEventSourceMock = vi.hoisted(() =>
  vi
    .fn<(input: RequestInfo, init: FetchEventSourceInit) => Promise<void>>()
    .mockResolvedValue(undefined),
);

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));

vi.mock("@sentry/react", () => ({
  captureException: vi.fn(),
}));

vi.mock("../sentry", () => ({
  isSentryEnabled: vi.fn().mockReturnValue(false),
}));

import { useGenerate, type AdmissionOutcome } from "./useGenerate";
import { useReleaseStore, resetReleaseDetector } from "../lib/release/releaseStore";
import { useAuthStore } from "../store/authStore";

function setReleaseStatus(status: "current" | "update-required" | "paused" | "unavailable" | "checking") {
  useReleaseStore.setState({ status, lastCheckedAt: Date.now(), lastFailure: null });
}

function latestStreamOptions(): FetchEventSourceInit {
  const call = fetchEventSourceMock.mock.lastCall;
  if (!call) throw new Error("Expected an event-stream request");
  return call[1];
}

beforeEach(() => {
  fetchEventSourceMock.mockClear();
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
  vi.restoreAllMocks();
  resetReleaseDetector();
});

describe("useGenerate — build admission preflight", () => {
  const previousQuestion = {
    id: "previous-question",
    情境: ["個人"],
    題型種類: "單一題",
    題型: "選擇題",
    題目: ["previous"],
    正確解題分析: ["answer"],
  };

  it("rejects on update-required without sending HTTP fetch", async () => {
    // Mock checkNow to immediately set update-required
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("update-required");
    });

    const { result } = renderHook(() => useGenerate());
    let promise!: Promise<AdmissionOutcome>;
    await act(async () => {
      promise = result.current.generate({ subject: "math" });
    });

    const outcome = await promise;
    expect(outcome).toEqual(
      expect.objectContaining({ outcome: "rejected" })
    );
    expect(result.current.admission).toBe("rejected");
    expect(result.current.admissionError).toContain("介面版本已更新");
    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toContain("介面版本已更新");
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
  });

  it("rejects on paused without sending HTTP fetch", async () => {
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("paused");
    });

    const { result } = renderHook(() => useGenerate());
    let promise!: Promise<AdmissionOutcome>;
    await act(async () => {
      promise = result.current.generate({ subject: "math" });
    });

    const outcome = await promise;
    expect(outcome).toEqual(
      expect.objectContaining({ outcome: "rejected" })
    );
    expect(result.current.admissionError).toContain("暫停維護中");
    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toContain("暫停維護中");
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
  });

  it("rejects on unavailable without sending HTTP fetch", async () => {
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("unavailable");
    });

    const { result } = renderHook(() => useGenerate());
    let promise!: Promise<AdmissionOutcome>;
    await act(async () => {
      promise = result.current.generate({ subject: "math" });
    });

    const outcome = await promise;
    expect(outcome).toEqual(
      expect.objectContaining({ outcome: "rejected" })
    );
    expect(result.current.admissionError).toContain("無法確認介面版本");
    expect(result.current.status).toBe("error");
    expect(result.current.errorMessage).toContain("無法確認介面版本");
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
  });

  it("rechecks an unavailable release and submits when the policy becomes current", async () => {
    setReleaseStatus("unavailable");
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("current");
    });

    const { result } = renderHook(() => useGenerate());
    act(() => {
      result.current.generate({ subject: "math" });
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetchEventSourceMock).toHaveBeenCalledOnce();
    expect(latestStreamOptions().headers).toEqual(expect.objectContaining({
      "X-Frontend-Build-ID": "test-build-abc",
    }));
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
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
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
      result.current.generate({ subject: "math" });
    });
    expect(fetchEventSourceMock).toHaveBeenCalledOnce();
  });

  it("sends X-Frontend-Build-ID header when preflight passes (current)", async () => {
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("current");
    });

    const { result } = renderHook(() => useGenerate());
    // Start generate but don't await — the stream never settles without real events.
    act(() => {
      result.current.generate({ subject: "math" });
    });
    // Flush the async preflight (checkNow) microtasks so fetchEventSource is called.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetchEventSourceMock).toHaveBeenCalledOnce();
    const [, init] = fetchEventSourceMock.mock.lastCall!;
    const headers = (init.headers as Record<string, string>);
    expect(headers["X-Frontend-Build-ID"]).toBe("test-build-abc");
  });

  it("attaches the build header to the POST body transport for long payloads", async () => {
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("current");
    });

    const { result } = renderHook(() => useGenerate());
    act(() => {
      result.current.generate({
        subject: "math",
        text_instruction: "x".repeat(12_000),
      });
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetchEventSourceMock).toHaveBeenCalledOnce();
    const [, init] = fetchEventSourceMock.mock.lastCall!;
    expect(init.method).toBe("POST");
    expect(String(init.body).length).toBeGreaterThan(12_000);
    expect((init.headers as Record<string, string>)["X-Frontend-Build-ID"])
      .toBe("test-build-abc");
  });

  it("ignores a duplicate click while the first stream is still pending", async () => {
    setReleaseStatus("current");
    const { result } = renderHook(() => useGenerate());

    let first!: Promise<AdmissionOutcome>;
    let duplicate!: Promise<AdmissionOutcome>;
    act(() => {
      first = result.current.generate({ subject: "math" });
      duplicate = result.current.generate({ subject: "math" });
    });

    expect(fetchEventSourceMock).toHaveBeenCalledOnce();
    await expect(duplicate).resolves.toEqual(
      expect.objectContaining({ outcome: "rejected" }),
    );
    act(() => {
      latestStreamOptions().onmessage?.({ id: "", event: "started", data: "{}" });
    });
    await expect(first).resolves.toEqual({ outcome: "admitted" });
  });

  it("preserves prior results and does not retry when admission changes after preflight", async () => {
    setReleaseStatus("current");
    const { result } = renderHook(() => useGenerate());
    act(() => {
      result.current.generate({ subject: "math" });
    });
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "result",
        data: JSON.stringify(previousQuestion),
      });
      latestStreamOptions().onmessage?.({ id: "", event: "done", data: "" });
    });
    expect(result.current.results).toEqual([previousQuestion]);

    fetchEventSourceMock.mockClear();
    useReleaseStore.setState({ status: "checking" });
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("current");
    });
    fetchEventSourceMock.mockImplementationOnce(async (_url, init) => {
      await init.onopen?.(new Response(
        JSON.stringify({ code: "CLIENT_UPDATE_REQUIRED", required_build_id: "new-build" }),
        { status: 426 },
      ));
    });

    let rejected!: Promise<AdmissionOutcome>;
    await act(async () => {
      rejected = result.current.generate({ subject: "math" });
      await Promise.resolve();
    });

    expect(fetchEventSourceMock).toHaveBeenCalledOnce();
    await expect(rejected).resolves.toEqual(expect.objectContaining({ outcome: "rejected" }));
    expect(result.current.status).toBe("error");
    expect(result.current.results).toEqual([previousQuestion]);
    expect(result.current.displayResults).toHaveLength(1);
  });

  it("keeps the existing signout behavior for a pre-stream 401", async () => {
    setReleaseStatus("current");
    const logout = vi.spyOn(useAuthStore.getState(), "logout");
    fetchEventSourceMock.mockImplementationOnce(async (_url, init) => {
      await init.onopen?.(new Response(null, { status: 401 }));
    });

    const { result } = renderHook(() => useGenerate());
    let rejected!: Promise<AdmissionOutcome>;
    act(() => {
      rejected = result.current.generate({ subject: "math" });
    });

    await expect(rejected).resolves.toEqual(
      expect.objectContaining({ outcome: "rejected" }),
    );
    expect(logout).toHaveBeenCalledOnce();
    logout.mockRestore();
  });

  it.each([414, 422])(
    "preserves prior results on a pre-stream HTTP %s error",
    async (status) => {
      setReleaseStatus("current");
      const { result } = renderHook(() => useGenerate());
      act(() => {
        result.current.generate({ subject: "math" });
      });
      act(() => {
        latestStreamOptions().onmessage?.({
          id: "",
          event: "result",
          data: JSON.stringify(previousQuestion),
        });
        latestStreamOptions().onmessage?.({ id: "", event: "done", data: "" });
      });
      fetchEventSourceMock.mockClear();
      fetchEventSourceMock.mockImplementationOnce(async (_url, init) => {
        await init.onopen?.(new Response("", { status }));
      });

      let rejected!: Promise<AdmissionOutcome>;
      await act(async () => {
        rejected = result.current.generate({ subject: "math" });
        await Promise.resolve();
      });

      expect(fetchEventSourceMock).toHaveBeenCalledOnce();
      await expect(rejected).resolves.toEqual(expect.objectContaining({ outcome: "rejected" }));
      expect(result.current.status).toBe("error");
      expect(result.current.results).toEqual([previousQuestion]);
      expect(result.current.displayResults).toHaveLength(1);
    },
  );

  it("preserves existing results on 426 response", async () => {
    // Set up a pre-existing result to confirm it is preserved
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockResolvedValue(undefined);
    setReleaseStatus("current");

    const { result } = renderHook(() => useGenerate());

    // Simulate a 426 response from fetchEventSource via onopen
    fetchEventSourceMock.mockImplementationOnce(async (_url, init) => {
      await init.onopen?.(new Response(
        JSON.stringify({ code: "CLIENT_UPDATE_REQUIRED", required_build_id: "build-xyz" }),
        { status: 426 }
      ));
    });

    act(() => {
      result.current.generate({ subject: "math" });
    });

    // Admission should end up rejected
    await act(async () => {
      await Promise.resolve();
    });

    // Status should not be "generating" still; it ends in error or rejected
    expect(result.current.admission).not.toBe("admitted");
  });

  it("preserves existing results on 503 response", async () => {
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockResolvedValue(undefined);
    setReleaseStatus("current");

    const { result } = renderHook(() => useGenerate());

    fetchEventSourceMock.mockImplementationOnce(async (_url, init) => {
      await init.onopen?.(new Response(
        JSON.stringify({ code: "AUTHORITY_UNAVAILABLE" }),
        { status: 503 }
      ));
    });

    act(() => {
      result.current.generate({ subject: "math" });
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.admission).not.toBe("admitted");
  });

  // -------------------------------------------------------------------------
  // resultsCompletion / terminalEvidence interaction with 426 (#771 + #774)
  // -------------------------------------------------------------------------

  it("(a) settled run followed by 426 keeps resultsCompletion='settled' and terminalEvidence=true", async () => {
    setReleaseStatus("current");
    const { result } = renderHook(() => useGenerate());

    // --- First generate: completes with terminal evidence ---
    act(() => {
      result.current.generate({ subject: "math" });
    });
    act(() => {
      const opts = latestStreamOptions();
      opts.onmessage?.({ id: "", event: "started", data: "{}" });
      // question_terminal populates terminalQuestionKeysRef so done sets terminalEvidence=true
      opts.onmessage?.({
        id: "",
        event: "question_terminal",
        data: JSON.stringify({ question_id: "q1" }),
      });
      opts.onmessage?.({
        id: "",
        event: "result",
        data: JSON.stringify(previousQuestion),
      });
      opts.onmessage?.({ id: "", event: "done", data: "" });
    });

    expect(result.current.resultsCompletion).toBe("settled");
    expect(result.current.terminalEvidence).toBe(true);
    const preservedResults = result.current.results;

    // --- Second generate: rejected by 426 stale-build ---
    fetchEventSourceMock.mockClear();
    useReleaseStore.setState({ status: "checking" });
    vi.spyOn(useReleaseStore.getState(), "checkNow").mockImplementationOnce(async () => {
      setReleaseStatus("current");
    });
    fetchEventSourceMock.mockImplementationOnce(async (_url, init) => {
      await init.onopen?.(new Response(
        JSON.stringify({ code: "CLIENT_UPDATE_REQUIRED", required_build_id: "new-build" }),
        { status: 426 },
      ));
    });

    let rejected!: Promise<AdmissionOutcome>;
    await act(async () => {
      rejected = result.current.generate({ subject: "math" });
      await Promise.resolve();
    });
    await expect(rejected).resolves.toEqual(expect.objectContaining({ outcome: "rejected" }));

    // Results are preserved and completion state travels with them (not clobbered by 426)
    expect(result.current.results).toEqual(preservedResults);
    expect(result.current.resultsCompletion).toBe("settled");
    expect(result.current.terminalEvidence).toBe(true);
  });

  it("(b) started event received then stream error sets resultsCompletion='error'", async () => {
    setReleaseStatus("current");
    const { result } = renderHook(() => useGenerate());

    act(() => {
      result.current.generate({ subject: "math" });
    });
    act(() => {
      const opts = latestStreamOptions();
      opts.onmessage?.({ id: "", event: "started", data: "{}" });
      opts.onmessage?.({
        id: "",
        event: "error",
        data: JSON.stringify({ message: "Something went wrong" }),
      });
    });

    expect(result.current.resultsCompletion).toBe("error");
  });
});
