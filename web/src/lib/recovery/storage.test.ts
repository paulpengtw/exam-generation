/**
 * Tests for recovery storage — issue #772.
 * Written BEFORE the implementation (red phase).
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  getOrCreateTabId,
  saveSnapshotTransactionally,
  persistTabPointer,
  loadTabPointer,
  loadSnapshot,
  deleteSnapshot,
  clearTabPointer,
} from "./storage";
import type { TabPointer } from "./storage";
import { RECOVERY_FORMAT_V1 } from "./format";
import type { RecoverySnapshotV1 } from "./format";

function makeSnapshot(overrides: Partial<RecoverySnapshotV1> = {}): RecoverySnapshotV1 {
  return {
    schema: RECOVERY_FORMAT_V1,
    snapshot_id: "snap-001",
    tab_id: "tab-abc",
    route: "/generate",
    subject: "math",
    account_id: "user-1",
    origin: "https://example.com",
    environment: "production",
    source_build_id: "build-A",
    target_build_id: "build-B",
    source_release_revision: 1,
    target_release_revision: 2,
    saved_at: new Date().toISOString(),
    workspace_revision: 0,
    form: { kind: "form", version: 1, fields: {} as never },
    ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("getOrCreateTabId", () => {
  it("creates a tab id and persists it in sessionStorage", () => {
    const id = getOrCreateTabId();
    expect(typeof id).toBe("string");
    expect(id.length).toBeGreaterThan(0);
    expect(sessionStorage.getItem("exam_tab_id")).toBe(id);
  });

  it("returns the same tab id on second call", () => {
    const first = getOrCreateTabId();
    const second = getOrCreateTabId();
    expect(first).toBe(second);
  });
});

describe("saveSnapshotTransactionally", () => {
  it("saves and reads back a snapshot", async () => {
    const snap = makeSnapshot();
    const result = await saveSnapshotTransactionally(snap);
    expect(result.ok).toBe(true);
    const loaded = loadSnapshot("user-1", "snap-001");
    expect(loaded).not.toBeNull();
    expect(loaded?.snapshot_id).toBe("snap-001");
  });

  it("uses the correct localStorage key", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    const key = "exam_recovery_user-1_snap-001";
    expect(localStorage.getItem(key)).not.toBeNull();
  });

  it("removes a partial write when the storage engine throws quota after writing", async () => {
    const nativeSetItem = localStorage.setItem.bind(localStorage);
    vi.spyOn(localStorage, "setItem").mockImplementationOnce((key, value) => {
      nativeSetItem(key, value);
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });

    const result = await saveSnapshotTransactionally(makeSnapshot());

    expect(result).toEqual({ ok: false, reason: "quota" });
    expect(localStorage.getItem("exam_recovery_user-1_snap-001")).toBeNull();
  });
});

describe("persistTabPointer + loadTabPointer", () => {
  it("round-trips a tab pointer", async () => {
    const pointer: TabPointer = {
      account_id: "user-1",
      snapshot_id: "snap-001",
      route: "/generate",
    };
    const result = await persistTabPointer(pointer);
    expect(result.ok).toBe(true);
    const loaded = loadTabPointer();
    expect(loaded).toEqual(pointer);
  });

  it("returns null when nothing stored", () => {
    expect(loadTabPointer()).toBeNull();
  });
});

describe("deleteSnapshot + clearTabPointer", () => {
  it("removes the snapshot from localStorage", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    deleteSnapshot("user-1", "snap-001");
    expect(loadSnapshot("user-1", "snap-001")).toBeNull();
  });

  it("clears the tab pointer from sessionStorage", async () => {
    const pointer: TabPointer = {
      account_id: "user-1",
      snapshot_id: "snap-001",
      route: "/generate",
    };
    await persistTabPointer(pointer);
    clearTabPointer();
    expect(loadTabPointer()).toBeNull();
  });
});
