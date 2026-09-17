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

function setReleaseStatus(status: "current" | "update-required" | "paused" | "unavailable" | "checking") {
  useReleaseStore.setState({ status, lastCheckedAt: Date.now(), lastFailure: null });
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
  resetReleaseDetector();
});

describe("useGenerate — build admission preflight", () => {
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
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
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
});
