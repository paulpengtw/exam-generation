/**
 * Unit tests for historyBadge.ts (issue #913 fix(913)).
 *
 * Covers:
 * - computeBadge: Date.parse-based comparison (format-safe: +00:00 vs Z,
 *   microseconds vs milliseconds)
 * - initLastSeenAt: server-time semantics (no client clock dependency)
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
  computeBadge,
  getLastSeenAt,
  setLastSeenAt,
  initLastSeenAt,
} from "./historyBadge";
import type { RunListItem } from "../api/client";

function makeRun(completedAt: string | null, runId = "r1"): RunListItem {
  return {
    run_id: runId,
    status: completedAt ? "completed" : "running",
    subject: "math",
    started_at: null,
    completed_at: completedAt,
    queue_position: null,
    cancel_requested: false,
  };
}

// ---------------------------------------------------------------------------
// computeBadge — format-safe Date.parse comparison
// ---------------------------------------------------------------------------

describe("computeBadge – format-safe Date.parse comparison", () => {
  it("returns false when completed_at and lastSeenAt are the same moment in Z format", () => {
    const ts = "2026-10-01T12:00:00.000Z";
    expect(computeBadge([makeRun(ts)], ts)).toBe(false);
  });

  it("+00:00 and Z formats for the same moment: no false-positive badge", () => {
    // "2026-10-01T12:00:00.000Z" and "2026-10-01T12:00:00+00:00" are the
    // same instant. Raw string comparison gives a false positive because "." > "+"
    // in ASCII (46 > 43). Date.parse must be used to fix this.
    const lastSeen = "2026-10-01T12:00:00+00:00";
    const runs = [makeRun("2026-10-01T12:00:00.000Z")];
    expect(computeBadge(runs, lastSeen)).toBe(false);
  });

  it("microseconds in server response: still detected as newer than lastSeenAt", () => {
    // Server may return "2026-10-01T12:00:00.123456+00:00" (microseconds)
    const lastSeen = "2026-10-01T11:00:00.000Z";
    const runs = [makeRun("2026-10-01T12:00:00.123456+00:00")];
    expect(computeBadge(runs, lastSeen)).toBe(true);
  });

  it("returns true when run completed after lastSeenAt across Z and +00:00", () => {
    const lastSeen = "2026-10-01T11:00:00+00:00";
    const runs = [makeRun("2026-10-01T12:00:00.000Z")];
    expect(computeBadge(runs, lastSeen)).toBe(true);
  });

  it("returns false when lastSeenAt is null", () => {
    expect(computeBadge([makeRun("2026-10-01T12:00:00.000Z")], null)).toBe(false);
  });

  it("returns false when no runs have completed_at", () => {
    expect(computeBadge([makeRun(null)], "2026-10-01T00:00:00Z")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// initLastSeenAt — server-time semantics
// ---------------------------------------------------------------------------

describe("initLastSeenAt – server-time semantics", () => {
  const userId = "test-user-srv";
  const key = `exam_history_last_seen_${userId}`;

  beforeEach(() => localStorage.removeItem(key));
  afterEach(() => localStorage.removeItem(key));

  it("first visit: stores serverTimestamp as the marker", () => {
    const serverTs = "2026-10-01T10:00:00.000Z";
    const result = initLastSeenAt(userId, serverTs);
    expect(result).toBe(serverTs);
    expect(getLastSeenAt(userId)).toBe(serverTs);
  });

  it("first visit with null serverTimestamp: returns null, no marker stored", () => {
    const result = initLastSeenAt(userId, null);
    expect(result).toBeNull();
    expect(getLastSeenAt(userId)).toBeNull();
  });

  it("returns stored value when marker already set (ignores serverTimestamp)", () => {
    const existing = "2026-09-01T00:00:00.000Z";
    setLastSeenAt(userId, existing);
    const result = initLastSeenAt(userId, "2026-10-01T00:00:00.000Z");
    expect(result).toBe(existing);
  });

  it("first visit with historical ended runs does NOT light badge", () => {
    // The server's newest completed_at is used as the initial marker.
    // Historical runs (completed_at <= newestCompletedAt) must not badge.
    const newestCompletedAt = "2026-09-30T23:00:00.000Z";
    initLastSeenAt(userId, newestCompletedAt);
    const lastSeen = getLastSeenAt(userId);
    const historicalRuns = [
      makeRun("2026-09-30T20:00:00.000Z", "r1"),
      makeRun("2026-09-30T22:59:59.999Z", "r2"),
      makeRun(newestCompletedAt, "r3"),
    ];
    expect(computeBadge(historicalRuns, lastSeen)).toBe(false);
  });

  it("client clock 10 min ahead: badge still fires for run completing after server init marker", () => {
    // If we used client clock (which is 10 min ahead), the marker would be at
    // T+10 and a run completing at T+5 would NOT badge.
    // By using server time (newestCompletedAt = T+0), a run at T+5 DOES badge.
    const serverNewest = "2026-10-01T10:00:00.000Z"; // server time
    initLastSeenAt(userId, serverNewest);
    const lastSeen = getLastSeenAt(userId)!;

    // Run completes at T+5 (after marker, but before client clock T+10)
    const newRun = makeRun("2026-10-01T10:05:00.000Z");
    expect(computeBadge([newRun], lastSeen)).toBe(true);
  });
});
