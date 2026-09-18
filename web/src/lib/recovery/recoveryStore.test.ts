/**
 * Tests for the recovery store boot-time restore logic — issue #772.
 * Written BEFORE the implementation (red phase).
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  useRecoveryStore,
  resetRecoveryStoreForTests,
  initRecoveryStore,
} from "./recoveryStore";
import { useAuthStore } from "../../store/authStore";
import { persistTabPointer, saveSnapshotTransactionally } from "./storage";
import { RECOVERY_FORMAT_V1 } from "./format";
import type { RecoverySnapshotV1 } from "./format";

vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

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
  resetRecoveryStoreForTests();
  useAuthStore.setState({ token: null, user: null });
});

describe("initRecoveryStore", () => {
  it("sets pending when everything matches", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "user-1",
      snapshot_id: "snap-001",
      route: "/generate",
    });
    useAuthStore.setState({
      token: "tok",
      user: { id: "user-1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    });

    initRecoveryStore({
      currentRoute: "/generate",
      origin: "https://example.com",
      environment: "production",
    });

    const state = useRecoveryStore.getState();
    expect(state.pending).not.toBeNull();
    expect(state.pending?.snapshot_id).toBe("snap-001");
  });

  it("does nothing when no tab pointer", () => {
    initRecoveryStore({ currentRoute: "/generate", origin: "https://example.com", environment: "production" });
    const state = useRecoveryStore.getState();
    expect(state.pending).toBeNull();
    expect(state.blocked).toBeNull();
  });

  it("keeps pointer but does not hydrate when user is not signed in", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({ account_id: "user-1", snapshot_id: "snap-001", route: "/generate" });
    // user is null

    initRecoveryStore({ currentRoute: "/generate", origin: "https://example.com", environment: "production" });

    const state = useRecoveryStore.getState();
    expect(state.pending).toBeNull();
    // Should not crash; pointer is still in sessionStorage
  });

  it("sets blocked when account does not match", async () => {
    const snap = makeSnapshot({ account_id: "user-2" });
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({ account_id: "user-2", snapshot_id: "snap-001", route: "/generate" });
    useAuthStore.setState({
      token: "tok",
      user: { id: "user-1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    });

    initRecoveryStore({ currentRoute: "/generate", origin: "https://example.com", environment: "production" });

    const state = useRecoveryStore.getState();
    expect(state.pending).toBeNull();
    expect(state.blocked).toBe("wrong_account");
  });

  it("does not hydrate when route does not match", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({ account_id: "user-1", snapshot_id: "snap-001", route: "/generate" });
    useAuthStore.setState({
      token: "tok",
      user: { id: "user-1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    });

    initRecoveryStore({ currentRoute: "/other", origin: "https://example.com", environment: "production" });

    const state = useRecoveryStore.getState();
    expect(state.pending).toBeNull();
  });
});

describe("useRecoveryStore actions", () => {
  it("acknowledgeRecovery clears pending", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({ account_id: "user-1", snapshot_id: "snap-001", route: "/generate" });
    useAuthStore.setState({
      token: "tok",
      user: { id: "user-1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    });
    initRecoveryStore({ currentRoute: "/generate", origin: "https://example.com", environment: "production" });

    useRecoveryStore.getState().acknowledgeRecovery();
    expect(useRecoveryStore.getState().pending).toBeNull();
  });

  it("discardRecovery removes snapshot and clears pending", async () => {
    const snap = makeSnapshot();
    await saveSnapshotTransactionally(snap);
    await persistTabPointer({ account_id: "user-1", snapshot_id: "snap-001", route: "/generate" });
    useAuthStore.setState({
      token: "tok",
      user: { id: "user-1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    });
    initRecoveryStore({ currentRoute: "/generate", origin: "https://example.com", environment: "production" });

    useRecoveryStore.getState().discardRecovery();
    expect(useRecoveryStore.getState().pending).toBeNull();
    // Snapshot should also be gone from localStorage
    expect(localStorage.getItem("exam_recovery_user-1_snap-001")).toBeNull();
  });
});
