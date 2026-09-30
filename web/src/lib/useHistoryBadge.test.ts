/**
 * Tests for useHistoryBadge (issue #913).
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// Mock historyBadge module
const initLastSeenAtMock = vi.hoisted(() => vi.fn());
const computeBadgeMock = vi.hoisted(() => vi.fn());
vi.mock("./historyBadge", () => ({
  initLastSeenAt: initLastSeenAtMock,
  computeBadge: computeBadgeMock,
}));

// Mock listRuns from api/client
const listRunsMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  listRuns: listRunsMock,
}));

import { useHistoryBadge } from "./useHistoryBadge";

describe("useHistoryBadge", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    initLastSeenAtMock.mockReturnValue("2026-10-01T00:00:00Z");
    computeBadgeMock.mockReturnValue(false);
    listRunsMock.mockResolvedValue([]);
    // Default visibilityState
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("returns false when no completed_at is newer than lastSeenAt", async () => {
    computeBadgeMock.mockReturnValue(false);
    const { result } = renderHook(() => useHistoryBadge("user-1"));
    await act(() => Promise.resolve());
    expect(result.current).toBe(false);
  });

  it("returns true when computeBadge returns true", async () => {
    computeBadgeMock.mockReturnValue(true);
    const { result } = renderHook(() => useHistoryBadge("user-1"));
    // Flush all pending microtasks so the initial pollOnce() resolves and
    // calls setBadge(true) before we assert.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve(); // two rounds to allow .then() chains to settle
    });
    expect(result.current).toBe(true);
  });

  it("returns false when userId is undefined", async () => {
    const { result } = renderHook(() => useHistoryBadge(undefined));
    await act(() => Promise.resolve());
    expect(result.current).toBe(false);
    expect(listRunsMock).not.toHaveBeenCalled();
  });

  it("handles localStorage errors gracefully (storage throws)", async () => {
    initLastSeenAtMock.mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    // Should not throw — hook wraps initLastSeenAt in try/catch
    let caught: Error | null = null;
    try {
      const { result } = renderHook(() => useHistoryBadge("user-1"));
      await act(async () => { await Promise.resolve(); });
      // badge stays false when storage is unavailable
      expect(result.current).toBe(false);
    } catch (e) {
      caught = e as Error;
    }
    expect(caught).toBeNull();
  });

  it("calls listRuns again after poll interval", async () => {
    const { result } = renderHook(() => useHistoryBadge("user-1"));
    await act(() => Promise.resolve());
    const callsBefore = listRunsMock.mock.calls.length;

    // Advance time past the visible poll interval (30s)
    await act(async () => {
      vi.advanceTimersByTime(31_000);
      await Promise.resolve();
    });

    expect(listRunsMock.mock.calls.length).toBeGreaterThan(callsBefore);
    expect(result.current).toBe(false);
  });

  it("pauses polling when tab is hidden (uses longer interval)", async () => {
    // Switch to hidden
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });

    const { result } = renderHook(() => useHistoryBadge("user-1"));
    await act(() => Promise.resolve());
    const callsAfterMount = listRunsMock.mock.calls.length;

    // Advance 35s — less than hidden interval (60s), more than visible (30s)
    await act(async () => {
      vi.advanceTimersByTime(35_000);
      await Promise.resolve();
    });

    // Should NOT have polled again yet
    expect(listRunsMock.mock.calls.length).toBe(callsAfterMount);
    expect(result.current).toBe(false);
  });
});
