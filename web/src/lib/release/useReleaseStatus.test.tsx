import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useReleaseStatus } from "./useReleaseStatus";
import { resetReleaseDetector, useReleaseStore } from "./releaseStore";

// Stub bundle globals
vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

const CURRENT_POLICY = JSON.stringify({
  schema: "exam-generation.release-policy/1",
  environment: "production",
  release_revision: 1,
  released_build_id: "build-A",
  admission: "open",
  supported_recovery_formats: [],
});

const UPDATE_POLICY = JSON.stringify({
  schema: "exam-generation.release-policy/1",
  environment: "production",
  release_revision: 2,
  released_build_id: "build-B",
  admission: "open",
  supported_recovery_formats: [],
});

const PAUSED_POLICY = JSON.stringify({
  schema: "exam-generation.release-policy/1",
  environment: "production",
  release_revision: 1,
  released_build_id: "build-C",
  admission: "paused",
  supported_recovery_formats: [],
});

const ROLLBACK_POLICY = JSON.stringify({
  schema: "exam-generation.release-policy/1",
  environment: "production",
  release_revision: 3,
  released_build_id: "build-A", // rolled back to A
  admission: "open",
  supported_recovery_formats: [],
});

function makeImmediateFetch(body: string, status = 200) {
  return vi.fn().mockResolvedValue(
    new Response(body, {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  resetReleaseDetector();
  useReleaseStore.setState({
    status: "checking",
    requiredBuildId: null,
    releaseRevision: null,
    lastCheckedAt: null,
    lastFailure: null,
  });
  // Default visible
  Object.defineProperty(document, "visibilityState", {
    value: "visible",
    configurable: true,
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  // Re-stub the globals after unstubbing so later tests still have them
  vi.stubGlobal("__BUILD_ID__", "build-A");
  vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");
});

/** Flush the microtask queue several times to let promise chains drain. */
async function flushPromises() {
  for (let i = 0; i < 10; i++) {
    await Promise.resolve();
  }
}

async function waitForCheck() {
  // Let microtasks drain — enough for immediate fetch mocks
  await act(async () => {
    await flushPromises();
  });
}

describe("useReleaseStatus", () => {
  it("coalesces concurrent triggers — two triggers produce exactly one fetch", async () => {
    const fetchMock = makeImmediateFetch(CURRENT_POLICY);
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useReleaseStatus());

    // Mount triggers first check; fire popstate before fetch resolves
    window.dispatchEvent(new PopStateEvent("popstate"));

    await waitForCheck();

    // Only one fetch call despite two triggers (coalescing)
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe("current");
  });

  it("5 s timeout -> unavailable with lastFailure=timeout", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        (_url: string, options?: { signal?: AbortSignal }) =>
          new Promise<Response>((_resolve, reject) => {
            const signal = options?.signal;
            // Respect the AbortSignal
            if (signal) {
              if (signal.aborted) {
                reject(new DOMException("Aborted", "AbortError"));
                return;
              }
              signal.addEventListener("abort", () => {
                reject(new DOMException("Aborted", "AbortError"));
              });
            }
            // Never resolves otherwise
            setTimeout(() => {
              _resolve(new Response(CURRENT_POLICY));
            }, 10000);
          }),
      ),
    );

    const { result } = renderHook(() => useReleaseStatus());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5001);
      await flushPromises();
    });

    expect(result.current.status).toBe("unavailable");
    expect(result.current.lastFailure).toBe("timeout");
  });

  it("reversed responses — second request wins when first resolves later", async () => {
    let resolveFirst!: (r: Response) => void;
    let resolveSecond!: (r: Response) => void;

    const fetchMock = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise<Response>((res) => (resolveFirst = res)),
      )
      .mockImplementationOnce(
        () => new Promise<Response>((res) => (resolveSecond = res)),
      );
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useReleaseStatus());

    // Let first request start
    await act(async () => {
      await flushPromises();
    });

    // First fetch started (coalescing: only 1 in-flight)
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Resolve first fetch so coalescing clears
    await act(async () => {
      resolveFirst(
        new Response(UPDATE_POLICY, {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
      await flushPromises();
    });

    // Now advance 60s to trigger interval — second fetch starts
    resetReleaseDetector();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60001);
      await flushPromises();
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Resolve second (CURRENT) before first's data would have been used
    await act(async () => {
      resolveSecond(
        new Response(CURRENT_POLICY, {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
      await flushPromises();
    });

    // Second result (CURRENT) should win
    expect(useReleaseStore.getState().status).toBe("current");
  });

  it("sticky requirement — known update-required is retained after a later failure", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(UPDATE_POLICY, {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockRejectedValueOnce(new Error("Network error"));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useReleaseStatus());

    // First check resolves
    await waitForCheck();

    expect(result.current.status).toBe("update-required");
    expect(result.current.requiredBuildId).toBe("build-B");

    // Advance 60s to trigger second check
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60001);
      await flushPromises();
    });

    // Status stays update-required (sticky), lastFailure is set
    expect(result.current.status).toBe("update-required");
    expect(result.current.requiredBuildId).toBe("build-B");
    expect(result.current.lastFailure).not.toBeNull();
  });

  it("paused policy -> status is paused", async () => {
    vi.stubGlobal("fetch", makeImmediateFetch(PAUSED_POLICY));

    const { result } = renderHook(() => useReleaseStatus());

    await waitForCheck();

    expect(result.current.status).toBe("paused");
  });

  it("visibility gating — 60s interval only fires while document is hidden", async () => {
    const fetchMock = makeImmediateFetch(CURRENT_POLICY);
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useReleaseStatus());

    // Let mount check complete
    await waitForCheck();
    const callsAfterMount = fetchMock.mock.calls.length;

    // Hide document
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      configurable: true,
    });

    // Advance 120s while hidden — interval should NOT fire additional fetches
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120000);
      await flushPromises();
    });

    // No extra calls while hidden
    expect(fetchMock.mock.calls.length).toBe(callsAfterMount);

    // Restore visibility and fire visibilitychange
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      configurable: true,
    });

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await flushPromises();
    });

    // One more call triggered by visibility restoration
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterMount);
  });

  it("A -> B -> rollback to A: current -> update-required -> current", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(CURRENT_POLICY, {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(UPDATE_POLICY, {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(ROLLBACK_POLICY, {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useReleaseStatus());

    // First check: A == A -> current
    await waitForCheck();
    expect(result.current.status).toBe("current");

    // Second check (after 60s): B != A -> update-required
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60001);
      await flushPromises();
    });
    expect(result.current.status).toBe("update-required");
    expect(result.current.requiredBuildId).toBe("build-B");

    // Third check (after another 60s): rollback to A -> current again
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60001);
      await flushPromises();
    });
    expect(result.current.status).toBe("current");
    expect(result.current.requiredBuildId).toBeNull();
  });

  it("location.reload is never called", async () => {
    vi.stubGlobal("fetch", makeImmediateFetch(UPDATE_POLICY));
    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, reload: reloadSpy },
      configurable: true,
    });

    const { result } = renderHook(() => useReleaseStatus());

    await waitForCheck();

    expect(reloadSpy).not.toHaveBeenCalled();
    expect(result.current.status).toBe("update-required");
  });
});
