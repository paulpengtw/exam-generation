/**
 * Scheduled update flow — unit tests.
 * Issue #777.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  useWorkspaceStore,
  resetWorkspaceStoreForTests,
} from "../workspace/workspaceStore";
import { decideOnChunkError } from "./chunkErrorGuard";
import { checkAutoRefreshEligible, markAutoReloadAttempted, hasAutoReloadBeenAttempted } from "./autoRefresh";

vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

beforeEach(() => {
  resetWorkspaceStoreForTests();
  try { sessionStorage.clear(); } catch { /* ignore */ }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Scheduled update — chunk error routing", () => {
  it("unit: old HTML: decideOnChunkError returns show_error with kind=old_html", () => {
    const err = Object.assign(new Error("chunk"), { name: "ChunkLoadError" });
    const result = decideOnChunkError({
      error: err,
      currentBuildId: "build-OLD",
      releasedBuildId: "build-NEW",
      autoRefreshEligibility: { eligible: true },
    });
    expect(result.action).toBe("show_error");
    expect(result.kind).toBe("old_html");
  });

  it("unit: missing assets on eligible empty page: decideOnChunkError returns reload", () => {
    const err = Object.assign(new Error("chunk"), { name: "ChunkLoadError" });
    const result = decideOnChunkError({
      error: err,
      currentBuildId: "build-A",
      releasedBuildId: "build-A",
      autoRefreshEligibility: { eligible: true },
    });
    expect(result.action).toBe("reload");
  });
});

describe("Scheduled update — auto reload marker", () => {
  it("unit: empty-page auto-reload fires only once per target/revision per tab", () => {
    const marked1 = markAutoReloadAttempted("build-X", 42);
    expect(marked1).toBe(true);
    expect(hasAutoReloadBeenAttempted("build-X", 42)).toBe(true);

    const eligibility = checkAutoRefreshEligible({
      workspaceState: {
        surfaces: {
          "generate.form": {
            id: "generate.form",
            readiness: "ready",
            hasEditableState: false,
            hasReceivedResults: false,
          },
        },
        operations: [],
      },
      recoveryPending: false,
      pageVisible: true,
      targetBuildId: "build-X",
      releaseRevision: 42,
      releaseStatus: "update-required",
    });
    expect(eligibility.eligible).toBe(false);
    if (!eligibility.eligible) {
      expect(eligibility.reason).toBe("already_reloaded");
    }
  });
});

describe("Scheduled update — queued intent transitions", () => {
  it("unit: late result callback: queued intent captures latest workspace after callback settles", () => {
    const h1 = useWorkspaceStore.getState().beginOperation("generation", "generate.results");
    useWorkspaceStore.getState().queueUpdateIntent();
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "queued" });
    h1.end("completed");
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "active" });
  });
});
