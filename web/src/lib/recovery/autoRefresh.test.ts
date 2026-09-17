/**
 * Auto-refresh eligibility — unit tests.
 * Issue #777.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  checkAutoRefreshEligible,
  markAutoReloadAttempted,
} from "./autoRefresh";
import type { WorkspaceState } from "../workspace/workspaceStore";

/** A hydrated form surface with no editable data — the "empty page" scenario. */
function emptyWorkspace(): Pick<WorkspaceState, "surfaces" | "operations"> {
  return {
    surfaces: {
      "generate.form": {
        id: "generate.form",
        readiness: "ready",
        hasEditableState: false,
        hasReceivedResults: false,
      },
    },
    operations: [],
  };
}

function editableSurface(): Pick<WorkspaceState, "surfaces" | "operations"> {
  return {
    surfaces: {
      "generate.form": {
        id: "generate.form",
        readiness: "ready",
        hasEditableState: true,
        hasReceivedResults: false,
      },
    },
    operations: [],
  };
}

const BASE_PARAMS = {
  workspaceState: emptyWorkspace(),
  recoveryPending: false,
  pageVisible: true,
  targetBuildId: "build-X",
  releaseRevision: 42,
  releaseStatus: "update-required" as const,
};

beforeEach(() => {
  try { sessionStorage.clear(); } catch { /* ignore */ }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("checkAutoRefreshEligible", () => {
  it("unit: eligible on empty visible page with update-required status", () => {
    const result = checkAutoRefreshEligible(BASE_PARAMS);
    expect(result.eligible).toBe(true);
  });

  it("unit: ineligible when release status is not update-required", () => {
    const result = checkAutoRefreshEligible({ ...BASE_PARAMS, releaseStatus: "current" });
    expect(result).toEqual({ eligible: false, reason: "no_update" });
  });

  it("unit: ineligible when page not visible", () => {
    const result = checkAutoRefreshEligible({ ...BASE_PARAMS, pageVisible: false });
    expect(result).toEqual({ eligible: false, reason: "not_visible" });
  });

  it("unit: ineligible when workspace has editable state", () => {
    const result = checkAutoRefreshEligible({
      ...BASE_PARAMS,
      workspaceState: editableSurface(),
    });
    expect(result.eligible).toBe(false);
    expect((result as { eligible: false; reason: string }).reason).toBe("not_safe");
  });

  it("unit: ineligible when recovery is pending", () => {
    const result = checkAutoRefreshEligible({ ...BASE_PARAMS, recoveryPending: true });
    expect(result).toEqual({ eligible: false, reason: "pending_recovery" });
  });

  it("unit: ineligible when already attempted for same target/revision", () => {
    markAutoReloadAttempted("build-X", 42);
    const result = checkAutoRefreshEligible(BASE_PARAMS);
    expect(result).toEqual({ eligible: false, reason: "already_reloaded" });
  });

  it("unit: eligible for different revision even if one was already attempted", () => {
    markAutoReloadAttempted("build-X", 41);
    const result = checkAutoRefreshEligible({ ...BASE_PARAMS, releaseRevision: 42 });
    expect(result.eligible).toBe(true);
  });

  it("unit: ineligible when marker storage denied — disables automation", () => {
    vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    const marked = markAutoReloadAttempted("build-X", 42);
    expect(marked).toBe(false);
  });
});
