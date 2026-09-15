/**
 * Tests for save-and-update eligibility — issue #772.
 * Written BEFORE the implementation (red phase).
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  useWorkspaceStore,
  resetWorkspaceStoreForTests,
} from "../workspace/workspaceStore";
import { useAuthStore } from "../../store/authStore";
import { useReleaseStore, resetReleaseDetector } from "../release/releaseStore";
import type { ReleaseState } from "../release/releaseStore";
import { runSaveAndUpdate } from "./saveAndUpdate";
import { loadSnapshot, loadTabPointer, getOrCreateTabId } from "./storage";
import { RECOVERY_FORMAT_V1 } from "./format";
import { evaluateSaveAndUpdate, type EvaluateInput } from "./saveAndUpdate";
import type { SurfaceParticipation } from "../workspace/workspaceStore";
import type { FormWorkspaceSnapshot } from "../workspace/adapters/types";

function makeFormSurface(
  overrides: Partial<SurfaceParticipation> = {},
): SurfaceParticipation {
  const exportWorkspace = (): FormWorkspaceSnapshot => ({
    kind: "form",
    version: 1,
    fields: {} as never,
  });
  return {
    id: "generate.form",
    readiness: "ready",
    hasEditableState: true,
    hasReceivedResults: false,
    exportWorkspace,
    ...overrides,
  };
}

function makeValidInput(overrides: Partial<EvaluateInput> = {}): EvaluateInput {
  return {
    surfaces: {
      "generate.form": makeFormSurface(),
    },
    operations: [],
    releaseStatus: "update-required",
    requiredBuildId: "build-B",
    releaseRevision: 2,
    supportedRecoveryFormats: ["exam-generation.recovery/1"],
    user: { id: "user-1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    ...overrides,
  };
}

vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  resetWorkspaceStoreForTests();
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

describe("evaluateSaveAndUpdate", () => {
  it("returns allowed:true for a valid state", () => {
    const result = evaluateSaveAndUpdate(makeValidInput());
    expect(result.allowed).toBe(true);
  });

  it("rejects when no surfaces registered", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ surfaces: {} }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("no_surface");
  });

  it("rejects when a surface is hydrating", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface({ readiness: "hydrating" }),
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("hydrating");
  });

  it("rejects when a surface is restoring", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface({ readiness: "restoring" }),
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("restoring");
  });

  it("rejects when an operation is active", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        operations: [
          { id: 1, kind: "generation", surface: "generate.form", startedAt: Date.now() },
        ],
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("operation_active");
  });

  it("rejects when a surface has received results", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface({ hasReceivedResults: true }),
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("results_present");
  });

  it("rejects when generate.confirmation is registered", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface(),
          "generate.confirmation": {
            id: "generate.confirmation",
            readiness: "ready",
            hasEditableState: true,
            hasReceivedResults: false,
          },
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("confirmation_open");
  });

  it("rejects when history.modification is registered", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface(),
          "history.modification": {
            id: "history.modification",
            readiness: "ready",
            hasEditableState: true,
            hasReceivedResults: false,
          },
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("modification_draft");
  });

  it("rejects when user is not signed in", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ user: null }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("not_signed_in");
  });

  it("rejects when release status is not update-required", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ releaseStatus: "current" }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("no_update");
  });

  it("rejects when requiredBuildId is null", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ requiredBuildId: null }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("no_update");
  });

  it("rejects when releaseRevision is null", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ releaseRevision: null }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("no_update");
  });

  it("rejects when recovery format is not supported", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({ supportedRecoveryFormats: ["other-format/1"] }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("unsupported_target_reader");
  });

  it("rejects when form surface has no exportWorkspace seam", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface({ exportWorkspace: undefined }),
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("unsupported_target_reader");
  });
});

// ---------------------------------------------------------------------------
// runSaveAndUpdate tests — T1 (red phase, fails until implementation lands)
// ---------------------------------------------------------------------------

function setupValidRunState(checkNowImpl?: () => Promise<void>) {
  useAuthStore.setState({
    token: "tok",
    user: { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
  });
  useWorkspaceStore.getState().registerSurface({
    id: "generate.form",
    readiness: "ready",
    hasEditableState: true,
    hasReceivedResults: false,
    exportWorkspace: () => ({ kind: "form", version: 1, fields: {} as never }),
  });
  const defaultCheckNow = async () => {
    // no-op: state already set correctly
  };
  useReleaseStore.setState({
    status: "update-required",
    requiredBuildId: "build-B",
    releaseRevision: 2,
    supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
    lastCheckedAt: null,
    lastFailure: null,
    checkNow: checkNowImpl ?? defaultCheckNow,
  } as ReleaseState);
}

describe("runSaveAndUpdate", () => {
  it("success path — snapshot readable and valid, pointer readable, navigate called once, freezeInput true", async () => {
    setupValidRunState();
    vi.stubGlobal("location", { pathname: "/generate/math", origin: "https://test.com", reload: vi.fn() });
    const navigate = vi.fn();

    const result = await runSaveAndUpdate({
      navigate,
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok");
    expect(navigate).toHaveBeenCalledOnce();

    // Snapshot must be readable and valid
    const snap = loadSnapshot("u1", result.snapshot_id);
    expect(snap).not.toBeNull();
    expect(snap?.schema).toBe(RECOVERY_FORMAT_V1);
    expect(snap?.account_id).toBe("u1");
    expect(snap?.source_build_id).toBe("build-A");
    expect(snap?.target_build_id).toBe("build-B");
    expect(snap?.form.kind).toBe("form");
    expect(snap?.form.version).toBe(1);

    // Pointer must be readable
    const pointer = loadTabPointer();
    expect(pointer).not.toBeNull();
    expect(pointer?.account_id).toBe("u1");
    expect(pointer?.snapshot_id).toBe(result.snapshot_id);
    expect(pointer?.attempted_target_build_id).toBe("build-B");

    // freezeInput stays true after success (page is navigating)
    expect(useWorkspaceStore.getState().freezeInput).toBe(true);
  });

  it("quota failure → no navigate, freezeInput false, navigationApproved false, reason quota", async () => {
    setupValidRunState();
    vi.stubGlobal("location", { pathname: "/generate/math", origin: "https://test.com", reload: vi.fn() });
    const navigate = vi.fn();

    vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });

    const result = await runSaveAndUpdate({
      navigate,
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("quota");
    expect(navigate).not.toHaveBeenCalled();
    expect(useWorkspaceStore.getState().freezeInput).toBe(false);
    expect(useWorkspaceStore.getState().navigationApproved).toBeNull();
  });

  it("pointer persistence failure → no navigate, snapshot still on disk, reason pointer_failed", async () => {
    setupValidRunState();
    vi.stubGlobal("location", { pathname: "/generate/math", origin: "https://test.com", reload: vi.fn() });
    const navigate = vi.fn();

    // Pre-seed tab ID so getOrCreateTabId() reads it without writing
    sessionStorage.setItem("exam_tab_id", "pre-seeded-tab");
    // Now mock sessionStorage.setItem to fail (pointer write)
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });

    const result = await runSaveAndUpdate({
      navigate,
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("pointer_failed");
    expect(navigate).not.toHaveBeenCalled();

    // Snapshot should still be on disk
    const snapId = (result as { ok: false; reason: string; snapshot_id?: string }).snapshot_id;
    // We can check that SOME recovery key exists in localStorage
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) keys.push(k);
    }
    const recoveryKeys = keys.filter((k) => k.startsWith("exam_recovery_u1_"));
    expect(recoveryKeys.length).toBeGreaterThan(0);
    expect(useWorkspaceStore.getState().freezeInput).toBe(false);
  });

  it("target changed on recheck → no navigate, no snapshot written", async () => {
    setupValidRunState(async () => {
      useReleaseStore.setState({ requiredBuildId: "build-C" });
    });
    vi.stubGlobal("location", { pathname: "/generate/math", origin: "https://test.com", reload: vi.fn() });
    const navigate = vi.fn();

    const result = await runSaveAndUpdate({
      navigate,
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("target_changed");
    expect(navigate).not.toHaveBeenCalled();
    // No snapshot written
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) keys.push(k);
    }
    expect(keys.filter((k) => k.startsWith("exam_recovery_"))).toHaveLength(0);
    expect(useWorkspaceStore.getState().freezeInput).toBe(false);
  });

  it("unsupported reader → refused, nothing written", async () => {
    setupValidRunState(async () => {
      useReleaseStore.setState({ supportedRecoveryFormats: ["other-format/1"] });
    });
    vi.stubGlobal("location", { pathname: "/generate/math", origin: "https://test.com", reload: vi.fn() });
    const navigate = vi.fn();

    const result = await runSaveAndUpdate({
      navigate,
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("unsupported_target_reader");
    expect(navigate).not.toHaveBeenCalled();
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) keys.push(k);
    }
    expect(keys.filter((k) => k.startsWith("exam_recovery_"))).toHaveLength(0);
  });

  it("account changed during recheck → refused", async () => {
    setupValidRunState(async () => {
      useAuthStore.setState({
        token: "tok",
        user: { id: "u2", email: "other@test.com", created_at: "2024-01-01T00:00:00Z" },
      });
    });
    vi.stubGlobal("location", { pathname: "/generate/math", origin: "https://test.com", reload: vi.fn() });
    const navigate = vi.fn();

    const result = await runSaveAndUpdate({
      navigate,
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("account_changed");
    expect(navigate).not.toHaveBeenCalled();
    expect(useWorkspaceStore.getState().freezeInput).toBe(false);
  });

  it("denied by evaluateSaveAndUpdate (no_update) → not_implemented returns error", async () => {
    // No release state set — evaluateSaveAndUpdate should deny
    useAuthStore.setState({
      token: "tok",
      user: { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    });
    useWorkspaceStore.getState().registerSurface({
      id: "generate.form",
      readiness: "ready",
      hasEditableState: false,
      hasReceivedResults: false,
      exportWorkspace: () => ({ kind: "form", version: 1, fields: {} as never }),
    });
    // release store stays 'checking' — evaluateSaveAndUpdate will deny with no_update
    const navigate = vi.fn();

    const result = await runSaveAndUpdate({ navigate, origin: "https://test.com", environment: "production", buildId: "build-A" });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("no_update");
    expect(navigate).not.toHaveBeenCalled();
  });
});
