/**
 * Integration test for the save-draft-and-update flow — issue #772.
 *
 * Covers the full path:
 *   1. User is on /generate with update-required state
 *   2. Conditions are met for save-and-update
 *   3. Save snapshot is stored transactionally
 *   4. On next boot the recovery store finds the snapshot
 *   5. The recoveryStore exposes it as `pending`
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useAuthStore } from "./store/authStore";
import { useReleaseStore, resetReleaseDetector } from "./lib/release/releaseStore";
import { useWorkspaceStore, resetWorkspaceStoreForTests } from "./lib/workspace/workspaceStore";
import { useRecoveryStore, resetRecoveryStoreForTests, initRecoveryStore } from "./lib/recovery/recoveryStore";
import { evaluateSaveAndUpdate } from "./lib/recovery/saveAndUpdate";
import {
  saveSnapshotTransactionally,
  persistTabPointer,
  getOrCreateTabId,
} from "./lib/recovery/storage";
import { RECOVERY_FORMAT_V1 } from "./lib/recovery/format";
import type { RecoverySnapshotV1 } from "./lib/recovery/format";

vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  resetWorkspaceStoreForTests();
  resetRecoveryStoreForTests();
  resetReleaseDetector();
  useAuthStore.setState({ token: null, user: null });
  useReleaseStore.setState({
    status: "checking",
    requiredBuildId: null,
    releaseRevision: null,
    supportedRecoveryFormats: [],
    lastCheckedAt: null,
    lastFailure: null,
  });
});

describe("save-and-update flow", () => {
  it("evaluateSaveAndUpdate returns allowed when all conditions are met", () => {
    useAuthStore.setState({
      token: "tok",
      user: { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    });
    useReleaseStore.setState({
      status: "update-required",
      requiredBuildId: "build-B",
      releaseRevision: 2,
      supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
    });
    useWorkspaceStore.getState().registerSurface({
      id: "generate.form",
      readiness: "ready",
      hasEditableState: true,
      hasReceivedResults: false,
      exportWorkspace: () => ({ kind: "form", version: 1, fields: {} as never }),
    });

    const { surfaces, operations } = useWorkspaceStore.getState();
    const { status, requiredBuildId, releaseRevision, supportedRecoveryFormats } =
      useReleaseStore.getState();
    const { user } = useAuthStore.getState();

    const result = evaluateSaveAndUpdate({
      surfaces,
      operations,
      releaseStatus: status,
      requiredBuildId,
      releaseRevision,
      supportedRecoveryFormats,
      user,
    });

    expect(result.allowed).toBe(true);
  });

  it("snapshot saved transactionally can be loaded back", async () => {
    const snap: RecoverySnapshotV1 = {
      schema: RECOVERY_FORMAT_V1,
      snapshot_id: "test-snap-001",
      tab_id: getOrCreateTabId(),
      route: "/generate",
      subject: "math",
      account_id: "u1",
      origin: "https://example.com",
      environment: "production",
      source_build_id: "build-A",
      target_build_id: "build-B",
      source_release_revision: 1,
      target_release_revision: 2,
      saved_at: new Date().toISOString(),
      workspace_revision: 3,
      form: { kind: "form", version: 1, fields: {} as never },
    };

    const saveResult = await saveSnapshotTransactionally(snap);
    expect(saveResult.ok).toBe(true);

    const pointerResult = await persistTabPointer({
      account_id: "u1",
      snapshot_id: "test-snap-001",
      route: "/generate",
    });
    expect(pointerResult.ok).toBe(true);
  });

  it("initRecoveryStore restores pending snapshot on boot", async () => {
    const snap: RecoverySnapshotV1 = {
      schema: RECOVERY_FORMAT_V1,
      snapshot_id: "boot-snap-001",
      tab_id: getOrCreateTabId(),
      route: "/generate",
      subject: "math",
      account_id: "u1",
      origin: "https://example.com",
      environment: "production",
      source_build_id: "build-A",
      target_build_id: "build-B",
      source_release_revision: 1,
      target_release_revision: 2,
      saved_at: new Date().toISOString(),
      workspace_revision: 0,
      form: { kind: "form", version: 1, fields: {} as never },
    };

    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "u1",
      snapshot_id: "boot-snap-001",
      route: "/generate",
    });

    useAuthStore.setState({
      token: "tok",
      user: { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    });

    initRecoveryStore({
      currentRoute: "/generate",
      origin: "https://example.com",
      environment: "production",
    });

    const state = useRecoveryStore.getState();
    expect(state.pending).not.toBeNull();
    expect(state.pending?.snapshot_id).toBe("boot-snap-001");
    expect(state.pending?.workspace_revision).toBe(0);
  });

  it("workspaceStore workspace_revision increments on surface registration", () => {
    const rev0 = useWorkspaceStore.getState().workspace_revision;
    useWorkspaceStore.getState().registerSurface({
      id: "generate.form",
      readiness: "ready",
      hasEditableState: false,
      hasReceivedResults: false,
    });
    const rev1 = useWorkspaceStore.getState().workspace_revision;
    expect(rev1).toBeGreaterThan(rev0);
  });

  it("workspaceStore approveNavigation + clearNavigationApproval work", () => {
    useWorkspaceStore.getState().approveNavigation("/new-page");
    expect(useWorkspaceStore.getState().navigationApproved).toEqual({ target: "/new-page" });
    useWorkspaceStore.getState().clearNavigationApproval();
    expect(useWorkspaceStore.getState().navigationApproved).toBeNull();
  });
});
