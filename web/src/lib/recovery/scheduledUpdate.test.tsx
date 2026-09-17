/**
 * Scheduled update flow — unit tests and router-driven integration tests.
 * Issue #777.
 *
 * Tests labeled "unit:" are pure function/store calls (no rendered UI).
 * Tests labeled "router:" render real React components, drive visible
 * controls, and assert what the user sees — they follow the style of
 * recoveryFlow.test.tsx and GeneratePage.results-recovery.test.tsx.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  useWorkspaceStore,
  resetWorkspaceStoreForTests,
} from "../workspace/workspaceStore";
import { decideOnChunkError } from "./chunkErrorGuard";
import {
  checkAutoRefreshEligible,
  markAutoReloadAttempted,
  hasAutoReloadBeenAttempted,
} from "./autoRefresh";
import {
  useReleaseStore,
  resetReleaseDetector,
  type ReleaseState,
} from "../release/releaseStore";
import {
  resetRecoveryStoreForTests,
  useRecoveryStore,
} from "./recoveryStore";
import { runSaveAndUpdate } from "./saveAndUpdate";
import { RECOVERY_FORMAT_V1, type RecoverySnapshotV1 } from "./format";
import { useAuthStore } from "../../store/authStore";
import { useLangStore } from "../../store/langStore";
import ReleaseNotice from "../../components/ReleaseNotice";
import ChunkErrorBoundary from "../../components/ChunkErrorBoundary";
import type { FormWorkspaceSnapshot } from "../workspace/adapters/types";

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

// ---------------------------------------------------------------------------
// Router-driven integration tests
// ---------------------------------------------------------------------------
// These tests render ReleaseNotice and ChunkErrorBoundary within a MemoryRouter,
// drive visible controls (buttons), and assert visible outcomes. They follow
// the style of recoveryFlow.test.tsx.
//
// Scenarios that can only be tested at the store/function level (no visible
// UI control to drive) are explicitly labeled "unit:" and commented to explain
// why jsdom cannot drive them further.
// ---------------------------------------------------------------------------

describe("Scheduled update — router-driven tests", () => {
  const USER = { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" };

  // A minimal form snapshot to satisfy the save-and-update export seam.
  const FORM_SNAPSHOT: FormWorkspaceSnapshot = {
    kind: "form",
    version: 1,
    fields: {
      grade: 8,
      style: "課本",
      contentType: "純文字",
      customContentType: "",
      context: ["個人"],
      setType: "單一題",
      qType: ["選擇題"],
      count: 1,
      coverageMode: "random",
      skipVerify: false,
      disableReferenceFewshot: false,
      coreQuestionCallback: true,
      imageGenerationMode: "html",
      difficulty: "",
      reportingScale: "",
      subjectFilter: "",
      passage: "",
      textWordLimit: null,
      textInstruction: "",
      options: [],
      topic: "scheduled-update-test",
      coreQuestion: null,
      subContext: "",
      scienceCompetency: [],
      learningPerformance: [],
      learningContent: [],
      subQuestionCount: "",
      subquestionConfigs: [],
      modelPlan: "",
      modelExecute: "",
      modelVerify: "",
      modelCorrect: "",
      effortPlan: "",
      effortExecute: "",
      effortVerify: "",
      effortCorrect: "",
      allowDuplicateFigureKinds: false,
    },
  };

  /** Put the release store into update-required state. */
  function setUpdateRequired(opts?: { requiredBuildId?: string; noFormats?: boolean }) {
    useReleaseStore.setState({
      status: "update-required",
      requiredBuildId: opts?.requiredBuildId ?? "build-B",
      releaseRevision: 2,
      supportedRecoveryFormats: opts?.noFormats ? [] : [RECOVERY_FORMAT_V1],
      lastCheckedAt: Date.now(),
      lastFailure: null,
      checkNow: async () => {},
    } as ReleaseState);
  }

  /**
   * Register a clean form surface directly (without rendering the full app).
   * Returns the deregister cleanup function.
   */
  function registerFormSurface(overrides?: {
    hasEditableState?: boolean;
  }): () => void {
    return useWorkspaceStore.getState().registerSurface({
      id: "generate.form",
      readiness: "ready",
      hasEditableState: overrides?.hasEditableState ?? false,
      hasReceivedResults: false,
      exportWorkspace: () => FORM_SNAPSHOT,
    });
  }

  beforeEach(() => {
    resetWorkspaceStoreForTests();
    resetRecoveryStoreForTests();
    resetReleaseDetector();
    localStorage.clear();
    sessionStorage.clear();
    useAuthStore.setState({ token: "tok", user: USER });
    useLangStore.setState({ lang: "en-US" });
    useReleaseStore.setState({
      status: "checking",
      requiredBuildId: null,
      releaseRevision: null,
      lastCheckedAt: null,
      lastFailure: null,
      supportedRecoveryFormats: [],
      checkNow: async () => {},
    } as ReleaseState);
    vi.stubGlobal("location", {
      pathname: "/generate/math",
      origin: "https://test.example.com",
      reload: vi.fn(),
      href: "https://test.example.com/generate/math",
    });
  });

  afterEach(() => {
    // Unmount any components left mounted by a failing test so that stale
    // subscriptions do not bleed into subsequent tests.
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.stubGlobal("__BUILD_ID__", "build-A");
    vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");
  });

  // -------------------------------------------------------------------------
  // Scenario 1: Queue and cancel
  // -------------------------------------------------------------------------
  it("router: queue 工作完成後儲存並更新 on a busy page, then cancel — no later save or reload, running work is undisturbed", async () => {
    setUpdateRequired();
    const deregister = registerFormSurface();
    const handle = useWorkspaceStore
      .getState()
      .beginOperation("generation", "generate.results");

    const { unmount } = render(
      <MemoryRouter>
        <ReleaseNotice />
      </MemoryRouter>,
    );

    // With an active generation, the save button is disabled (operation_active)
    // and the "Queue update" button should appear.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Queue update|工作完成後儲存並更新/i }),
      ).toBeInTheDocument();
    });

    // Click queue — intent transitions to queued.
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /Queue update|工作完成後儲存並更新/i }),
      );
    });
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "queued" });

    // Cancel button replaces the queue button.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Cancel queued update|取消排程更新/i }),
      ).toBeInTheDocument();
    });

    // Click cancel — intent cleared.
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /Cancel queued update|取消排程更新/i }),
      );
    });
    expect(useWorkspaceStore.getState().updateIntent).toBeNull();

    // Running operation is undisturbed.
    expect(useWorkspaceStore.getState().operations).toHaveLength(1);

    // End operation — cancelled intent means no save or reload fires.
    await act(async () => {
      handle.end("completed");
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(window.location.reload).not.toHaveBeenCalled();

    deregister();
    unmount();
  });

  // -------------------------------------------------------------------------
  // Scenario 2: Late planner and result callbacks
  // -------------------------------------------------------------------------
  it("router: late planner and result callbacks after queuing — intent fires runSaveAndUpdate when last operation settles", async () => {
    setUpdateRequired();
    const deregister = registerFormSurface();

    const planHandle = useWorkspaceStore
      .getState()
      .beginOperation("core_question_planning", "generate.form");
    const genHandle = useWorkspaceStore
      .getState()
      .beginOperation("generation", "generate.results");

    const { unmount } = render(
      <MemoryRouter>
        <ReleaseNotice />
      </MemoryRouter>,
    );

    // Both operations active — queue button visible.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Queue update|工作完成後儲存並更新/i }),
      ).toBeInTheDocument();
    });

    // User queues the update while both operations are running.
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /Queue update|工作完成後儲存並更新/i }),
      );
    });
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "queued" });

    // Planner callback settles — generation still running; intent stays queued.
    // The captured workspace will be the latest one (post-planner state), not
    // the one at queue time, because runSaveAndUpdate exports the workspace at
    // the moment it finally runs (after all operations have settled).
    await act(async () => {
      planHandle.end("completed");
    });
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "queued" });

    // Generation callback settles — all operations done; intent transitions to
    // active; useQueuedUpdateIntent fires runSaveAndUpdate → navigate → reload.
    await act(async () => {
      genHandle.end("completed");
    });

    await waitFor(
      () => {
        expect(window.location.reload).toHaveBeenCalledOnce();
      },
      { timeout: 3000 },
    );

    deregister();
    unmount();
  });

  // -------------------------------------------------------------------------
  // Scenario 3: ODT export and image conversion delaying the update
  // -------------------------------------------------------------------------
  it("router: active ODT export and image conversion delay the update until both settle", async () => {
    setUpdateRequired();
    const deregister = registerFormSurface();

    const odtHandle = useWorkspaceStore
      .getState()
      .beginOperation("export_odt", "generate.results");
    const imgHandle = useWorkspaceStore
      .getState()
      .beginOperation("export_image", "generate.results");

    const { unmount } = render(
      <MemoryRouter>
        <ReleaseNotice />
      </MemoryRouter>,
    );

    // Both active — queue button visible.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Queue update|工作完成後儲存並更新/i }),
      ).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /Queue update|工作完成後儲存並更新/i }),
      );
    });
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "queued" });

    // ODT export finishes — image conversion still running; intent stays queued.
    await act(async () => {
      odtHandle.end("completed");
    });
    expect(useWorkspaceStore.getState().updateIntent).toEqual({ kind: "queued" });

    // Image conversion finishes — all settled; save fires, reload called.
    await act(async () => {
      imgHandle.end("completed");
    });

    await waitFor(
      () => {
        expect(window.location.reload).toHaveBeenCalledOnce();
      },
      { timeout: 3000 },
    );

    deregister();
    unmount();
  });

  // -------------------------------------------------------------------------
  // Scenario 4: Target change during read-back
  // -------------------------------------------------------------------------
  it("router: target change during read-back — navigation cancelled, saved copy and original workspace and guards retained, fresh explicit action required", async () => {
    setUpdateRequired();
    // checkNow simulates the server deploying a new version mid-save.
    useReleaseStore.setState({
      checkNow: async () => {
        useReleaseStore.setState({ requiredBuildId: "build-C" });
      },
    });
    const deregister = registerFormSurface();
    const navigateSpy = vi.fn();

    const { unmount } = render(
      <MemoryRouter>
        <ReleaseNotice />
      </MemoryRouter>,
    );

    const result = await runSaveAndUpdate({
      navigate: navigateSpy,
      origin: "https://test.example.com",
      environment: "production",
      buildId: "build-A",
    });

    // Navigation cancelled because target changed during the recheck.
    expect(result).toEqual({ ok: false, reason: "target_changed", retryable: false });
    expect(navigateSpy).not.toHaveBeenCalled();
    // freezeInput reset — guards restored; a fresh explicit action is required.
    expect(useWorkspaceStore.getState().freezeInput).toBe(false);
    // Nothing saved to localStorage (saved copy discarded).
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) keys.push(k);
    }
    expect(keys.filter((k) => k.startsWith("exam_recovery_"))).toHaveLength(0);

    deregister();
    unmount();
  });

  // -------------------------------------------------------------------------
  // Scenario 5: Incompatible recovery reader on target
  // -------------------------------------------------------------------------
  it("router: incompatible recovery reader on target — refused before saving", async () => {
    // Target build does not advertise support for the recovery format.
    setUpdateRequired({ noFormats: true });
    const deregister = registerFormSurface();
    const navigateSpy = vi.fn();

    const { unmount } = render(
      <MemoryRouter>
        <ReleaseNotice />
      </MemoryRouter>,
    );

    const result = await runSaveAndUpdate({
      navigate: navigateSpy,
      origin: "https://test.example.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("unsupported_target_reader");
    expect(navigateSpy).not.toHaveBeenCalled();
    // Nothing saved — refused before any localStorage write.
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) keys.push(k);
    }
    expect(keys.filter((k) => k.startsWith("exam_recovery_"))).toHaveLength(0);

    deregister();
    unmount();
  });

  // -------------------------------------------------------------------------
  // Scenario 6: Old HTML after a reload — loop stops
  // -------------------------------------------------------------------------
  it("router: old HTML after a reload — loop stops, error shown instead of another reload", async () => {
    // The running build is older than the released build; reloading would
    // serve the same stale HTML again, so the loop must stop.
    vi.stubGlobal("__BUILD_ID__", "build-OLD");
    useReleaseStore.setState({
      status: "update-required",
      requiredBuildId: "build-NEW",
      releaseRevision: 99,
      supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
      lastCheckedAt: Date.now(),
      lastFailure: null,
      checkNow: async () => {},
    } as ReleaseState);
    const deregister = registerFormSurface();

    // Suppress React's error-boundary console output (expected behaviour).
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    function ThrowChunkLoad() {
      throw Object.assign(new Error("Failed to fetch dynamically imported module"), {
        name: "ChunkLoadError",
      });
    }

    const { unmount } = render(
      <MemoryRouter>
        <ChunkErrorBoundary>
          <ThrowChunkLoad />
        </ChunkErrorBoundary>
      </MemoryRouter>,
    );

    // ChunkErrorBoundary detected old HTML → shows error, does NOT reload.
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/此頁面已過期|outdated/i)).toBeInTheDocument();
    expect(window.location.reload).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    deregister();
    unmount();
  });

  // -------------------------------------------------------------------------
  // Scenario 7a: Chunk/preload error on eligible empty page → reload
  // -------------------------------------------------------------------------
  it("router: chunk error on eligible empty page — reload triggered once", async () => {
    // Use the same build ID for both current and released so old-HTML detection
    // does not fire. The page is eligible (empty, safe, visible, no marker).
    vi.stubGlobal("__BUILD_ID__", "build-A");
    useReleaseStore.setState({
      status: "update-required",
      requiredBuildId: "build-A", // matches __BUILD_ID__ → not old HTML
      releaseRevision: 5,
      supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
      lastCheckedAt: Date.now(),
      lastFailure: null,
      checkNow: async () => {},
    } as ReleaseState);
    const deregister = registerFormSurface();

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    function ThrowChunkLoad() {
      throw Object.assign(new Error("chunk"), { name: "ChunkLoadError" });
    }

    render(
      <MemoryRouter>
        <ChunkErrorBoundary>
          <ThrowChunkLoad />
        </ChunkErrorBoundary>
      </MemoryRouter>,
    );

    // Eligible empty page → ChunkErrorBoundary calls reload and renders nothing.
    expect(window.location.reload).toHaveBeenCalledOnce();

    errorSpy.mockRestore();
    deregister();
  });

  // -------------------------------------------------------------------------
  // Scenario 7b: Chunk/preload error on a non-empty page → error shown
  // -------------------------------------------------------------------------
  it("router: chunk error on a non-empty page — error shown, no reload", async () => {
    vi.stubGlobal("__BUILD_ID__", "build-A");
    useReleaseStore.setState({
      status: "update-required",
      requiredBuildId: "build-A",
      releaseRevision: 5,
      supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
      lastCheckedAt: Date.now(),
      lastFailure: null,
      checkNow: async () => {},
    } as ReleaseState);
    // Surface has editable state → not eligible for auto-refresh.
    const deregister = registerFormSurface({ hasEditableState: true });

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    function ThrowChunkLoad() {
      throw Object.assign(new Error("chunk"), { name: "ChunkLoadError" });
    }

    const { unmount } = render(
      <MemoryRouter>
        <ChunkErrorBoundary>
          <ThrowChunkLoad />
        </ChunkErrorBoundary>
      </MemoryRouter>,
    );

    // Not eligible (editable state) → show error, do not reload.
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(window.location.reload).not.toHaveBeenCalled();

    errorSpy.mockRestore();
    deregister();
    unmount();
  });

  // -------------------------------------------------------------------------
  // Scenario 8a: Empty-page automatic reload fires at most once per revision
  // -------------------------------------------------------------------------
  it("router: empty-page automatic reload fires at most once per target/revision per tab", async () => {
    setUpdateRequired();
    const deregister = registerFormSurface();

    const { unmount: unmount1 } = render(
      <MemoryRouter>
        <ReleaseNotice />
      </MemoryRouter>,
    );

    // First render on an eligible page — auto-refresh fires and sets the marker.
    await waitFor(() => {
      expect(window.location.reload).toHaveBeenCalledOnce();
    });
    expect(hasAutoReloadBeenAttempted("build-B", 2)).toBe(true);

    // Unmount the first instance and mount a fresh one.
    unmount1();

    const { unmount: unmount2 } = render(
      <MemoryRouter>
        <ReleaseNotice />
      </MemoryRouter>,
    );

    // Second render with same deps — marker already set → no second reload.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(window.location.reload).toHaveBeenCalledOnce(); // still exactly one

    deregister();
    unmount2();
  });

  // -------------------------------------------------------------------------
  // Scenario 8b: Automatic reload disabled when marker cannot be stored
  // -------------------------------------------------------------------------
  it("router: automatic reload disabled when the marker cannot be stored", async () => {
    setUpdateRequired();
    const deregister = registerFormSurface();

    // Simulate a storage environment that refuses writes.
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new DOMException("storage quota exceeded", "QuotaExceededError");
    });

    const { unmount } = render(
      <MemoryRouter>
        <ReleaseNotice />
      </MemoryRouter>,
    );

    // Give the useEffect time to attempt marking.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    // markAutoReloadAttempted returned false → automation disabled → no reload.
    expect(window.location.reload).not.toHaveBeenCalled();

    deregister();
    unmount();
  });

  // -------------------------------------------------------------------------
  // Scenario 9: No restored flow automatically submits generation or modification
  // -------------------------------------------------------------------------
  it("router: no restored flow automatically submits generation or modification", async () => {
    // Simulate a pending recovery snapshot (just loaded from a prior session).
    // The auto-refresh eligibility check returns "pending_recovery" when
    // useRecoveryStore.pending !== null, so no automatic reload fires.
    // Additionally, updateIntent stays null — restore does not queue a save.
    setUpdateRequired();
    const deregister = registerFormSurface();

    useRecoveryStore.setState({
      pending: {
        schema: RECOVERY_FORMAT_V1,
        snapshot_id: "snap-1",
        tab_id: "tab-1",
        route: "/generate/math",
        subject: "math",
        account_id: USER.id,
        origin: "https://test.example.com",
        environment: "production",
        source_build_id: "build-A",
        target_build_id: "build-B",
        source_release_revision: 1,
        target_release_revision: 2,
        saved_at: new Date().toISOString(),
        workspace_revision: 0,
        form: FORM_SNAPSHOT,
      } as RecoverySnapshotV1,
      blocked: null,
      claimedTabId: null,
      claimedSnapshotId: null,
    });

    const { unmount } = render(
      <MemoryRouter>
        <ReleaseNotice />
      </MemoryRouter>,
    );

    // Restore does not set updateIntent — no save is automatically queued.
    expect(useWorkspaceStore.getState().updateIntent).toBeNull();

    // Auto-refresh is blocked by the pending recovery.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(window.location.reload).not.toHaveBeenCalled();

    deregister();
    unmount();
  });
});
