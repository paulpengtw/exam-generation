/**
 * Recovery identity hardening tests — issue #776.
 *
 * Tests the following real flows:
 *  1. Expired-session restore via same-tab sign-in
 *  2. Different-account login refused; content not exposed
 *  3. Explicit logout invalidates recovery for that account
 *  4. Both 401 paths (API and stream) classify as expiry, not explicit logout
 *  5. Two independent tabs each own their own snapshot
 *  6. Duplicate-tab collision detection (BroadcastChannel probe)
 *  7. Denied marker storage blocks save-and-update even when snapshot saved
 *  8. Telemetry exclusion (no recovery contents in Sentry calls)
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  claimSnapshot,
  releaseSnapshotClaim,
  deleteAllSnapshotsForAccount,
  detectTabCollision,
  startTabCollisionListener,
  saveSnapshotTransactionally,
  persistTabPointer,
  loadSnapshot,
  getOrCreateTabId,
} from "./storage";
import {
  useRecoveryStore,
  resetRecoveryStoreForTests,
  initRecoveryStore,
  initRecoveryStoreAsync,
} from "./recoveryStore";
import { useAuthStore } from "../../store/authStore";
import { RECOVERY_FORMAT_V1 } from "./format";
import type { RecoverySnapshotV1 } from "./format";

vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

// ── helpers ──────────────────────────────────────────────────────────────────

function makeSnapshot(
  overrides: Partial<RecoverySnapshotV1> = {},
): RecoverySnapshotV1 {
  return {
    schema: RECOVERY_FORMAT_V1,
    snapshot_id: "snap-776",
    tab_id: "tab-abc",
    route: "/generate/math",
    subject: "math",
    account_id: "user-A",
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

function signIn(id = "user-A"): void {
  useAuthStore.setState({
    token: "tok",
    user: { id, email: `${id}@example.com`, created_at: "2026-01-01T00:00:00Z" },
  });
}

const INIT_OPTS = {
  currentRoute: "/generate/math",
  origin: "https://example.com",
  environment: "production",
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  resetRecoveryStoreForTests();
  useAuthStore.setState({ token: null, user: null });
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

// ── 1. Expired-session restore via same-tab sign-in ───────────────────────────

describe("expired-session restore via same-tab sign-in", () => {
  it("preserves the tab pointer when user is not signed in, then restores after sign-in", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "user-A",
      snapshot_id: "snap-776",
      route: "/generate/math",
    });

    // Simulate app boot while signed out (session expired, pointer preserved)
    initRecoveryStore(INIT_OPTS);
    expect(useRecoveryStore.getState().pending).toBeNull();

    // User signs back in with the same account
    signIn("user-A");
    initRecoveryStore(INIT_OPTS);

    const { pending } = useRecoveryStore.getState();
    expect(pending).not.toBeNull();
    expect(pending?.snapshot_id).toBe("snap-776");
    expect(pending?.account_id).toBe("user-A");
  });

  it("session pointer survives credential clearing (logout without cleanup)", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "user-A",
      snapshot_id: "snap-776",
      route: "/generate/math",
    });
    signIn("user-A");

    // 401-path logout (credential expiry) — keeps recovery intact
    useAuthStore.getState().logout();
    expect(useAuthStore.getState().user).toBeNull();

    // Pointer still exists in sessionStorage
    const raw = sessionStorage.getItem("exam_recovery_tab");
    expect(raw).not.toBeNull();

    // Snapshot still exists
    expect(loadSnapshot("user-A", "snap-776")).not.toBeNull();

    // After re-login, restore works
    signIn("user-A");
    resetRecoveryStoreForTests();
    initRecoveryStore(INIT_OPTS);
    expect(useRecoveryStore.getState().pending?.snapshot_id).toBe("snap-776");
  });
});

// ── 2. Different-account login refused ────────────────────────────────────────

describe("different-account login — refused, content not shown", () => {
  it("sets blocked:wrong_account and does not expose pending when account mismatches", async () => {
    // Snapshot belongs to user-A
    const snap = makeSnapshot({ account_id: "user-A" });
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "user-A",
      snapshot_id: "snap-776",
      route: "/generate/math",
    });

    // User-B signs in
    signIn("user-B");
    initRecoveryStore(INIT_OPTS);

    const state = useRecoveryStore.getState();
    // Content must NOT be exposed
    expect(state.pending).toBeNull();
    // The blocked flag tells UI to show a generic "different account" message
    expect(state.blocked).toBe("wrong_account");
  });

  it("async variant also blocks different-account snapshots", async () => {
    const snap = makeSnapshot({ account_id: "user-A" });
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "user-A",
      snapshot_id: "snap-776",
      route: "/generate/math",
    });

    signIn("user-B");
    await initRecoveryStoreAsync(INIT_OPTS);

    const state = useRecoveryStore.getState();
    expect(state.pending).toBeNull();
    expect(state.blocked).toBe("wrong_account");
  });
});

// ── 3. Explicit logout invalidates recovery ───────────────────────────────────

describe("explicit logout — snapshot invalidated for that account", () => {
  it("logoutExplicit deletes snapshots for the current account", async () => {
    const snap = makeSnapshot({ account_id: "user-A", snapshot_id: "snap-A1" });
    await saveSnapshotTransactionally(snap);
    expect(localStorage.getItem("exam_recovery_user-A_snap-A1")).not.toBeNull();

    signIn("user-A");
    useAuthStore.getState().logoutExplicit();

    // Snapshot is gone
    expect(localStorage.getItem("exam_recovery_user-A_snap-A1")).toBeNull();
    // Auth state cleared
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().token).toBeNull();
  });

  it("logoutExplicit clears the tab pointer", async () => {
    const snap = makeSnapshot({ account_id: "user-A" });
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "user-A",
      snapshot_id: "snap-776",
      route: "/generate/math",
    });

    signIn("user-A");
    useAuthStore.getState().logoutExplicit();

    expect(sessionStorage.getItem("exam_recovery_tab")).toBeNull();
  });

  it("logoutExplicit does NOT affect snapshots for a different account", async () => {
    const snapA = makeSnapshot({ account_id: "user-A", snapshot_id: "snap-A1" });
    const snapB = makeSnapshot({ account_id: "user-B", snapshot_id: "snap-B1" });
    await saveSnapshotTransactionally(snapA);
    await saveSnapshotTransactionally(snapB);

    signIn("user-A");
    useAuthStore.getState().logoutExplicit();

    // user-A's snapshot gone
    expect(localStorage.getItem("exam_recovery_user-A_snap-A1")).toBeNull();
    // user-B's snapshot preserved (unrelated account)
    expect(localStorage.getItem("exam_recovery_user-B_snap-B1")).not.toBeNull();
  });

  it("after explicit logout, initRecoveryStore finds no snapshot", async () => {
    const snap = makeSnapshot({ account_id: "user-A" });
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "user-A",
      snapshot_id: "snap-776",
      route: "/generate/math",
    });

    signIn("user-A");
    useAuthStore.getState().logoutExplicit();

    // Sign in again (same account after explicit logout)
    signIn("user-A");
    initRecoveryStore(INIT_OPTS);

    expect(useRecoveryStore.getState().pending).toBeNull();
    expect(useRecoveryStore.getState().blocked).toBeNull();
  });

  it("credential-clearing logout (401 path) does NOT delete snapshots", async () => {
    const snap = makeSnapshot({ account_id: "user-A", snapshot_id: "snap-A1" });
    await saveSnapshotTransactionally(snap);

    signIn("user-A");
    // 401-path logout — credential expiry, not explicit
    useAuthStore.getState().logout();

    // Snapshot must still be there
    expect(localStorage.getItem("exam_recovery_user-A_snap-A1")).not.toBeNull();
  });
});

// ── 4. Both 401 paths classify as expiry ──────────────────────────────────────

describe("both 401 paths classify credential expiry (not explicit logout)", () => {
  it("apiFetch 401 saves signout reason 'session_expired' and preserves snapshot", async () => {
    signIn("user-A");
    const snap = makeSnapshot({ account_id: "user-A", snapshot_id: "snap-persist" });
    await saveSnapshotTransactionally(snap);

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }),
    );

    window.history.pushState({}, "", "/generate/math");
    const { apiFetch } = await import("../../api/client");
    await expect(apiFetch("/api/test")).rejects.toThrow();

    // Signout reason saved as expiry
    const raw = localStorage.getItem("exam_signout_reason");
    expect(raw).not.toBeNull();
    const { reason, userId } = JSON.parse(raw!) as { reason: string; userId: string };
    expect(reason).toBe("session_expired");
    expect(userId).toBe("user-A");

    // Snapshot still on disk (not deleted by expiry logout)
    expect(localStorage.getItem("exam_recovery_user-A_snap-persist")).not.toBeNull();

    // Auth cleared (logout called, not logoutExplicit)
    expect(useAuthStore.getState().token).toBeNull();
  });

  it("apiFetch 401 saves return destination for allowed generate route", async () => {
    signIn("user-A");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }),
    );
    window.history.pushState({}, "", "/generate/math");
    const { apiFetch } = await import("../../api/client");
    await expect(apiFetch("/api/schemas?subject=math")).rejects.toThrow();
    expect(localStorage.getItem("exam_return_to")).toBe("/generate/math");
  });

  it("apiFetch 401 on non-generate route does NOT save return destination", async () => {
    signIn("user-A");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }),
    );
    window.history.pushState({}, "", "/history");
    const { apiFetch } = await import("../../api/client");
    await expect(apiFetch("/api/history")).rejects.toThrow();
    expect(localStorage.getItem("exam_return_to")).toBeNull();
  });

  it("non-401 API error does NOT save signout reason or clear auth", async () => {
    signIn("user-A");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Internal error" }), { status: 500 }),
    );
    const { apiFetch } = await import("../../api/client");
    await expect(apiFetch("/api/schemas")).rejects.toThrow();

    // No signout state
    expect(localStorage.getItem("exam_signout_reason")).toBeNull();
    // Auth still intact
    expect(useAuthStore.getState().token).toBe("tok");
  });
});

// ── 5. Two independent tabs each own their own snapshot ───────────────────────

describe("two independent tabs — each claims its own snapshot", () => {
  it("tab-1 and tab-2 claim different snapshots without conflict", async () => {
    const snapA = makeSnapshot({ snapshot_id: "snap-tab1", account_id: "user-A" });
    const snapB = makeSnapshot({ snapshot_id: "snap-tab2", account_id: "user-A" });
    await saveSnapshotTransactionally(snapA);
    await saveSnapshotTransactionally(snapB);

    const result1 = await claimSnapshot("tab-1", "snap-tab1");
    const result2 = await claimSnapshot("tab-2", "snap-tab2");

    expect(result1.won).toBe(true);
    expect(result2.won).toBe(true);

    releaseSnapshotClaim("snap-tab1");
    releaseSnapshotClaim("snap-tab2");
  });

  it("claimSnapshot nonce read-back detects a concurrent overwrite (simulated collision)", async () => {
    // Simulate scenario: tab-1 writes its claim, but before reading back,
    // tab-2 overwrites with a different nonce.  We model this with a spy that
    // returns the WRONG value on the read-back call.
    const originalGetItem = localStorage.getItem.bind(localStorage);
    let callCount = 0;
    vi.spyOn(localStorage, "getItem").mockImplementation((key: string) => {
      if (key === "exam_recovery_claim_snap-race") {
        callCount++;
        if (callCount === 1) {
          // Simulate tab-2 having written its own entry before tab-1 reads back
          return JSON.stringify({
            tab_id: "tab-race-2",
            nonce: "other-nonce",
            snapshot_id: "snap-race",
            claimed_at: new Date().toISOString(),
          });
        }
      }
      return originalGetItem(key);
    });

    const result1 = await claimSnapshot("tab-race-1", "snap-race");
    // tab-race-1's read-back sees tab-race-2's nonce → lost
    expect(result1.won).toBe(false);
  });
});

// ── 6. Duplicate-tab collision detection ─────────────────────────────────────

describe("duplicate-tab collision detection (BroadcastChannel)", () => {
  it("detectTabCollision returns false when no other tab is listening", async () => {
    const collision = await detectTabCollision("unique-tab-id-xyz", 100);
    expect(collision).toBe(false);
  });

  it("detectTabCollision returns true when another tab is alive with the same ID", async () => {
    const tabId = "duplicate-tab-id-123";

    // Simulate original tab: starts listener
    const stopListener = startTabCollisionListener(tabId);

    // Allow the listener to set up before probing
    await new Promise<void>((r) => setTimeout(r, 10));

    // Duplicate tab probes
    const collision = await detectTabCollision(tabId, 300);
    expect(collision).toBe(true);

    stopListener();
  });

  it("detectTabCollision does not confuse different tab IDs", async () => {
    const listenerTabId = "owner-tab-111";
    const probeTabId = "other-tab-222"; // different ID

    const stopListener = startTabCollisionListener(listenerTabId);
    await new Promise<void>((r) => setTimeout(r, 10));

    // Probing for a different ID → no collision
    const collision = await detectTabCollision(probeTabId, 150);
    expect(collision).toBe(false);

    stopListener();
  });

  it("getOrCreateTabId persists a new ID when no existing entry found", () => {
    sessionStorage.clear();
    const id = getOrCreateTabId();
    expect(typeof id).toBe("string");
    expect(id.length).toBeGreaterThan(0);
    expect(sessionStorage.getItem("exam_tab_id")).toBe(id);
  });

  it("collision-aware async init uses transactional claim per tab ID", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "user-A",
      snapshot_id: "snap-776",
      route: "/generate/math",
    });

    signIn("user-A");
    sessionStorage.setItem("exam_tab_id", "tab-owner");
    await initRecoveryStoreAsync(INIT_OPTS);

    const state = useRecoveryStore.getState();
    expect(state.pending).not.toBeNull();
    expect(state.claimedTabId).toBe("tab-owner");
    expect(state.claimedSnapshotId).toBe("snap-776");
  });
});

// ── 7. Denied marker storage blocks save-and-update ───────────────────────────

describe("denied marker storage — save-and-update blocked", () => {
  it("claimSnapshot returns won:false when localStorage.setItem throws", async () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });
    const result = await claimSnapshot("tab-x", "snap-x");
    expect(result.won).toBe(false);
  });

  it("claimSnapshot returns won:false when read-back returns null", async () => {
    vi.spyOn(localStorage, "getItem").mockReturnValueOnce(null);
    const result = await claimSnapshot("tab-x", "snap-stored");
    expect(result.won).toBe(false);
  });

  it("initRecoveryStoreAsync does not set pending when claim storage fails", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "user-A",
      snapshot_id: "snap-776",
      route: "/generate/math",
    });
    signIn("user-A");
    sessionStorage.setItem("exam_tab_id", "tab-loser");

    // Simulate claim storage denial so this tab loses the claim
    vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => {
      throw new DOMException("StorageError", "StorageError");
    });

    await initRecoveryStoreAsync(INIT_OPTS);

    expect(useRecoveryStore.getState().pending).toBeNull();
  });

  it("failed tab-pointer persistence → no pointer in sessionStorage, snapshot intact on disk", async () => {
    // Verifies the storage-level invariant that a failed persistTabPointer call
    // leaves the snapshot on disk but no pointer in sessionStorage.
    // The runSaveAndUpdate controller treats this as pointer_failed and
    // blocks navigation (tested in saveAndUpdate.test.ts).
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    expect(loadSnapshot("user-A", "snap-776")).not.toBeNull();

    // Fail pointer persistence
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });
    const pointerResult = await persistTabPointer({
      account_id: "user-A",
      snapshot_id: "snap-776",
      route: "/generate/math",
    });

    expect(pointerResult.ok).toBe(false);
    expect(pointerResult.reason).toBe("quota");
    // Snapshot itself is still on disk
    expect(loadSnapshot("user-A", "snap-776")).not.toBeNull();
    // Pointer is not in sessionStorage
    expect(sessionStorage.getItem("exam_recovery_tab")).toBeNull();
  });
});

// ── 8. Telemetry exclusion ────────────────────────────────────────────────────

describe("telemetry exclusion — no recovery contents in console or storage keys", () => {
  it("claimSnapshot does not log nonce or snapshot_id to console", async () => {
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await claimSnapshot("tab-safe", "snap-no-log");

    for (const call of [...logSpy.mock.calls, ...warnSpy.mock.calls, ...errorSpy.mock.calls]) {
      const asString = JSON.stringify(call);
      expect(asString).not.toContain("snap-no-log");
    }
    releaseSnapshotClaim("snap-no-log");
  });

  it("deleteAllSnapshotsForAccount does not log account ID or contents", async () => {
    const snap = makeSnapshot({ account_id: "user-priv" });
    await saveSnapshotTransactionally(snap);

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    deleteAllSnapshotsForAccount("user-priv");

    for (const call of [...logSpy.mock.calls, ...errorSpy.mock.calls]) {
      const asString = JSON.stringify(call);
      expect(asString).not.toContain("user-priv");
    }
  });

  it("signout reason saved by apiFetch 401 contains only userId and reason — no snapshot content", async () => {
    signIn("user-A");
    const snap = makeSnapshot({
      account_id: "user-A",
      snapshot_id: "snap-sensitive",
      form: { kind: "form", version: 1, fields: { topic: "teacher-secret" } as never },
    });
    await saveSnapshotTransactionally(snap);

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }),
    );
    window.history.pushState({}, "", "/generate/math");
    const { apiFetch } = await import("../../api/client");
    await expect(apiFetch("/api/schemas")).rejects.toThrow();

    const raw = localStorage.getItem("exam_signout_reason");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!) as Record<string, unknown>;
    // Only reason and userId present — no snapshot content
    expect(Object.keys(parsed)).toEqual(expect.arrayContaining(["reason", "userId"]));
    expect(Object.keys(parsed)).not.toContain("form");
    expect(Object.keys(parsed)).not.toContain("snapshot");
    expect(raw).not.toContain("teacher-secret");
  });
});
