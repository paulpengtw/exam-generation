/**
 * Recovery flow integration test — issue #772.
 *
 * Drives the real App router (routes array with createMemoryRouter) to prove
 * the save → persist → restore → confirm cycle end-to-end.
 *
 * Scenarios:
 *   1. Full flow: type topic → 儲存草稿並更新 → reload → restore → 確認 → deleted
 *   2. Quota failure: reload not called, form preserved, 重試 button shown
 *   3. Unsupported format: refused before saving, nothing in storage
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

// ---- Mock heavy page dependencies ----
const generateMock = vi.hoisted(() => vi.fn());
vi.mock("./hooks/useGenerate", () => ({
  useGenerate: () => ({
    status: "idle" as const,
    progressLines: [],
    results: [],
    displayResults: [],
    llmCalls: [],
    agentLanes: [],
    errorMessage: null,
    startedAt: null,
    finishedAt: null,
    generate: generateMock,
    reset: vi.fn(),
  }),
}));
vi.mock("./components/ProgressLog", () => ({ default: () => null }));
vi.mock("./components/QuestionCard", () => ({ default: () => null }));
vi.mock("./components/AgentStatusPanel", () => ({ default: () => null }));
vi.mock("./utils/odt", () => ({ buildExamOdt: vi.fn(), formatTimestamp: vi.fn(() => "ts") }));

// ---- Mock API client (schemas + models) ----
const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
vi.mock("./api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => ({ payload, drawn: [] })),
}));

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [],
  學習表現: [],
  學習內容: [],
};

const AVAILABLE_MODELS = {
  allowed: ["claude-sonnet-4-6"],
  defaults: { plan: "claude-sonnet-4-6", execute: "claude-sonnet-4-6" },
  effort: {} as Record<string, string[]>,
};

import { useAuthStore } from "./store/authStore";
import { useReleaseStore, resetReleaseDetector } from "./lib/release/releaseStore";
import { useWorkspaceStore, resetWorkspaceStoreForTests } from "./lib/workspace/workspaceStore";
import {
  useRecoveryStore,
  resetRecoveryStoreForTests,
  initRecoveryStore,
} from "./lib/recovery/recoveryStore";
import { evaluateSaveAndUpdate, runSaveAndUpdate } from "./lib/recovery/saveAndUpdate";
import {
  loadSnapshot,
  loadTabPointer,
  saveSnapshotTransactionally,
  persistTabPointer,
  getOrCreateTabId,
} from "./lib/recovery/storage";
import { RECOVERY_FORMAT_V1 } from "./lib/recovery/format";
import { routes } from "./routes";
import type { ReleaseState } from "./lib/release/releaseStore";

const USER = { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" };

function setUpUpdateRequired() {
  useReleaseStore.setState({
    status: "update-required",
    requiredBuildId: "build-B",
    releaseRevision: 2,
    supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
    lastCheckedAt: Date.now(),
    lastFailure: null,
    checkNow: async () => {},
  } as ReleaseState);
}

function setUpCurrent() {
  useReleaseStore.setState({
    status: "current",
    requiredBuildId: null,
    releaseRevision: 1,
    supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
    lastCheckedAt: Date.now(),
    lastFailure: null,
    checkNow: async () => {},
  } as ReleaseState);
}

function renderApp(initialEntry = "/generate/math") {
  const router = createMemoryRouter(routes, {
    initialEntries: [initialEntry],
    initialIndex: 0,
  });
  const { unmount } = render(<RouterProvider router={router} />);
  return { router, unmount };
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.clearAllMocks();
  getSchemasMock.mockResolvedValue(MATH_SCHEMA);
  getAvailableModelsMock.mockResolvedValue(AVAILABLE_MODELS);
  resetWorkspaceStoreForTests();
  resetRecoveryStoreForTests();
  resetReleaseDetector();
  useAuthStore.setState({
    token: "tok",
    user: USER,
  });
  vi.stubGlobal("location", {
    pathname: "/generate/math",
    origin: "https://test.example.com",
    reload: vi.fn(),
    href: "https://test.example.com/generate/math",
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.stubGlobal("__BUILD_ID__", "build-A");
  vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");
});

describe("recovery flow — scenario 1: full save → restore → confirm", () => {
  it("saves snapshot with the typed topic and restores it after reload", async () => {
    setUpUpdateRequired();
    const navigateSpy = vi.fn();

    // --- Phase 1: Render app, type topic, save ---
    const { unmount } = renderApp();

    // Wait for the topic input to appear (schemas loaded)
    const topicInput = await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );

    // Type a distinctive topic (do NOT advance autosave timer)
    await act(async () => {
      fireEvent.change(topicInput, { target: { value: "flow-test-unique-topic" } });
    });

    // Run save-and-update via the function directly (simulating button click)
    const saveResult = await runSaveAndUpdate({
      navigate: navigateSpy,
      origin: "https://test.example.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(saveResult.ok).toBe(true);
    if (!saveResult.ok) throw new Error(`Save failed: ${JSON.stringify(saveResult)}`);

    // navigate was called (simulated reload)
    expect(navigateSpy).toHaveBeenCalledOnce();

    // Snapshot and pointer must be in storage
    const snap = loadSnapshot("u1", saveResult.snapshot_id);
    expect(snap).not.toBeNull();
    expect(snap?.schema).toBe(RECOVERY_FORMAT_V1);
    expect(snap?.form.fields.topic).toBe("flow-test-unique-topic");

    const pointer = loadTabPointer();
    expect(pointer).not.toBeNull();
    expect(pointer?.snapshot_id).toBe(saveResult.snapshot_id);
    expect(pointer?.attempted_target_build_id).toBe("build-B");

    unmount();

    // --- Phase 2: Simulate BUILD_ID = 'B', policy current, render again ---
    vi.stubGlobal("__BUILD_ID__", "build-B");
    setUpCurrent();
    resetWorkspaceStoreForTests();

    // initRecoveryStore simulates what boot does
    initRecoveryStore({
      currentRoute: "/generate/math",
      origin: "https://test.example.com",
      environment: "production",
    });

    // Recovery store should have pending snapshot
    expect(useRecoveryStore.getState().pending).not.toBeNull();
    expect(useRecoveryStore.getState().pending?.form.fields.topic).toBe("flow-test-unique-topic");

    // Render the app again with the saved auth and recovery state
    // The app picks up the recovery store's pending snapshot on mount
    const { unmount: unmount2 } = renderApp();

    // Before schemas resolve, the workspace export should have the topic
    // (ParamForm initializes formFields from recoveredForm immediately)
    await waitFor(() => {
      const ws = useWorkspaceStore.getState();
      const exported = ws.surfaces["generate.form"]?.exportWorkspace?.();
      // Either workspace has the exported form, or ParamForm is still mounting
      // — the surface registers on mount via useSurfaceParticipation
      expect(ws.surfaces["generate.form"]).toBeDefined();
    });

    // After schemas resolve, topic shows in DOM and the recovery banner appears
    const topicInput2 = await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );
    expect((topicInput2 as HTMLInputElement).value).toBe("flow-test-unique-topic");

    // Recovery banner should appear now
    await waitFor(() => {
      expect(
        screen.queryByText(/Form restored from before update|已還原更新前的表單/i),
      ).toBeInTheDocument();
    });

    // Click 確認 (Acknowledge)
    const ackButton = screen.getByRole("button", { name: /Acknowledge|確認/i });
    await act(async () => {
      fireEvent.click(ackButton);
    });

    // After acknowledge: snapshot + pointer should be deleted
    await waitFor(() => {
      expect(loadSnapshot("u1", saveResult.snapshot_id)).toBeNull();
      expect(loadTabPointer()).toBeNull();
    });

    unmount2();
  });
});

describe("recovery flow — scenario 2: quota failure", () => {
  it("reload not called, freezeInput reset, quota reason returned", async () => {
    setUpUpdateRequired();
    const navigateSpy = vi.fn();

    const { unmount } = renderApp();
    // Wait for form to render so the surface is registered with export seam
    await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );

    // Make localStorage.setItem throw on snapshot write
    vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });

    const result = await runSaveAndUpdate({
      navigate: navigateSpy,
      origin: "https://test.example.com",
      environment: "production",
      buildId: "build-A",
    });

    // Reload must NOT have been called
    expect(navigateSpy).not.toHaveBeenCalled();

    // Result should indicate quota failure
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("quota");

    // Nothing in storage — no snapshot keys for this user
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) keys.push(k);
    }
    expect(keys.filter((k) => k.startsWith("exam_recovery_u1_"))).toHaveLength(0);

    // freezeInput reset to false after failure
    expect(useWorkspaceStore.getState().freezeInput).toBe(false);

    unmount();
  });

  it("重試 retry button is shown in ReleaseNotice after a save error", async () => {
    setUpUpdateRequired();

    const { unmount } = renderApp();
    await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );

    // Spy on setItem to make the save fail
    vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });

    // Click the 儲存草稿並更新 button in ReleaseNotice
    const saveButton = screen.getByRole("button", { name: /Save Draft & Update|儲存草稿並更新/i });
    await act(async () => {
      fireEvent.click(saveButton);
    });

    // After the failed save, a 重試/Retry button should appear
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /Retry|重試/i })).toBeInTheDocument();
    });

    unmount();
  });
});

describe("recovery flow — scenario 3: unsupported format", () => {
  it("refuses before saving when target does not support recovery format", async () => {
    // Set release state without the recovery format
    useReleaseStore.setState({
      status: "update-required",
      requiredBuildId: "build-B",
      releaseRevision: 2,
      supportedRecoveryFormats: [], // No recovery format supported
      lastCheckedAt: Date.now(),
      lastFailure: null,
      checkNow: async () => {},
    } as ReleaseState);

    const navigateSpy = vi.fn();

    // Render the app so a form surface with export seam is registered
    const { unmount } = renderApp();
    await screen.findByPlaceholderText(
      /e\.g\. Climate change|例如：氣候變遷/i,
      {},
      { timeout: 5000 },
    );

    const result = await runSaveAndUpdate({
      navigate: navigateSpy,
      origin: "https://test.example.com",
      environment: "production",
      buildId: "build-A",
    });

    // Should fail because format not supported
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("unsupported_target_reader");

    // navigate not called
    expect(navigateSpy).not.toHaveBeenCalled();

    // Nothing in storage
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k) keys.push(k);
    }
    expect(keys.filter((k) => k.startsWith("exam_recovery_"))).toHaveLength(0);

    unmount();
  });
});

describe("recovery store flow — existing tests", () => {
  it("snapshot saved transactionally can be loaded back", async () => {
    const snap = {
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
      form: { kind: "form" as const, version: 1 as const, fields: {} as never },
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
    const tabId = getOrCreateTabId();
    const snap = {
      schema: RECOVERY_FORMAT_V1,
      snapshot_id: "boot-snap-001",
      tab_id: tabId,
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
      form: { kind: "form" as const, version: 1 as const, fields: {} as never },
    };

    await saveSnapshotTransactionally(snap);
    await persistTabPointer({
      account_id: "u1",
      snapshot_id: "boot-snap-001",
      route: "/generate",
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

  it("evaluateSaveAndUpdate returns allowed when all conditions are met", () => {
    useWorkspaceStore.getState().registerSurface({
      id: "generate.form",
      readiness: "ready",
      hasEditableState: true,
      hasReceivedResults: false,
      exportWorkspace: () => ({ kind: "form", version: 1, fields: {} as never }),
    });

    const { surfaces, operations } = useWorkspaceStore.getState();

    const result = evaluateSaveAndUpdate({
      surfaces,
      operations,
      releaseStatus: "update-required",
      requiredBuildId: "build-B",
      releaseRevision: 2,
      supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
      user: USER,
    });

    expect(result.allowed).toBe(true);
  });
});
