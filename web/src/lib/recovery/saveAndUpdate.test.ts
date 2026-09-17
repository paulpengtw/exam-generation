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
import { loadSnapshot, loadTabPointer } from "./storage";
import { RECOVERY_FORMAT_V1 } from "./format";
import { evaluateSaveAndUpdate, type EvaluateInput } from "./saveAndUpdate";
import type { SurfaceParticipation } from "../workspace/workspaceStore";
import type { FormWorkspaceSnapshot } from "../workspace/adapters/types";
import type { ConfirmationWorkspaceSnapshot } from "../workspace/adapters/types";
import type { ResultsWorkspaceSnapshot } from "../workspace/adapters/types";
import type { ModificationWorkspaceSnapshot } from "../workspace/adapters/types";

function makeConfirmationSnapshot(
  overrides: Partial<ConfirmationWorkspaceSnapshot> = {},
): ConfirmationWorkspaceSnapshot {
  return {
    kind: "confirmation",
    version: 1,
    pendingParams: {
      subject: "math",
      grade: 8,
      context: ["生活情境"],
      set_type: "單一題",
      q_type: ["選擇題"],
      count: 1,
      skip_verify: false,
      image_generation_mode: "html",
      seed: 42,
      drawn: ["context"],
    } as never,
    pendingPerQuestionParams: null,
    clearedPaths: ["context"],
    redraws: { context: 1 },
    hasPendingConfirmationEdits: true,
    coreQuestionResolution: "generated",
    historyDraftChoice: "history",
    pendingPrefill: { topic: "confirmation-only topic" },
    ...overrides,
  };
}

function makeConfirmationSurface(
  overrides: Partial<SurfaceParticipation> = {},
): SurfaceParticipation {
  const exportWorkspace = (): ConfirmationWorkspaceSnapshot => makeConfirmationSnapshot();
  return {
    id: "generate.confirmation",
    readiness: "ready",
    hasEditableState: true,
    hasReceivedResults: false,
    exportWorkspace,
    ...overrides,
  };
}

function makeResultsSnapshot(): ResultsWorkspaceSnapshot {
  return {
    kind: "results",
    version: 1,
    results: [{ id: "q-1", 情境: [], 題型種類: "single", 題型: "multiple_choice", 題目: ["received"], 正確解題分析: ["analysis"] }],
    displayResults: [{
      index: 0,
      question: { id: "q-1", 情境: [], 題型種類: "single", 題型: "multiple_choice", 題目: ["received"], 正確解題分析: ["analysis"] },
      phase: "verified",
      isFinal: true,
    }],
    progressLines: ["received"],
    errorMessage: null,
    startedAt: 10,
    finishedAt: 20,
    subQuestionTotal: null,
    requestedTotal: 1,
    submittedSubQuestionCount: null,
    completion: "unknown",
    processing: "unknown",
    terminalEvidence: false,
    evidence: [{
      stableId: "q-1", index: 0, receipt: "final", processing: "unknown", contentRevision: null,
      terminal: "unknown", review: { status: "unknown", contentRevision: null },
    }],
  };
}

function makeResultsSurface(
  snapshot: ResultsWorkspaceSnapshot = makeResultsSnapshot(),
  overrides: Partial<SurfaceParticipation> = {},
): SurfaceParticipation {
  return {
    id: "generate.results",
    readiness: "ready",
    hasEditableState: false,
    hasReceivedResults: true,
    exportWorkspace: () => snapshot,
    ...overrides,
  };
}

function makeModificationSnapshot(
  overrides: Partial<ModificationWorkspaceSnapshot> = {},
): ModificationWorkspaceSnapshot {
  return {
    kind: "modification",
    version: 1,
    route: "/history/history-record",
    subject: "social_studies",
    recordId: "history-record",
    questionId: "history-question",
    contentIdentity: "canonical-history-question",
    contentRevision: null,
    eligibility: { status: "completed", verified: true, eligible: true },
    annotations: [{
      segments: [{ field_path: "文本", start: 0, end: 7, quoted_text: "passage" }],
      instruction: "Clarify this passage",
    }],
    replacement: null,
    ...overrides,
  };
}

function makeModificationSurface(
  snapshot: ModificationWorkspaceSnapshot = makeModificationSnapshot(),
  overrides: Partial<SurfaceParticipation> = {},
): SurfaceParticipation {
  return {
    id: "history.modification",
    readiness: "ready",
    hasEditableState: Array.isArray(snapshot.annotations) && snapshot.annotations.length > 0,
    hasReceivedResults: snapshot.replacement !== null,
    exportWorkspace: () => snapshot,
    ...overrides,
  };
}

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

  it("allows received results when the result surface can export verified workspace state", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({
      surfaces: {
        "generate.form": makeFormSurface(),
        "generate.results": makeResultsSurface(),
      },
    }));

    expect(result).toEqual({ allowed: true });
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

  it("allows a settled generate.confirmation snapshot", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface(),
          "generate.confirmation": makeConfirmationSurface(),
        },
      }),
    );
    expect(result.allowed).toBe(true);
  });

  it("rejects an unsettled confirmation even when no operation is registered", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface(),
          "generate.confirmation": makeConfirmationSurface({
            exportWorkspace: () => ({
              ...makeConfirmationSurface().exportWorkspace!() as ConfirmationWorkspaceSnapshot,
              coreQuestionResolution: "loading",
            }),
          }),
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("confirmation_open");
  });

  it("allows a valid settled history modification workspace", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface(),
          "history.modification": makeModificationSurface(),
        },
      }),
    );
    expect(result).toEqual({ allowed: true });
  });

  it("rejects a malformed history modification workspace", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface(),
          "history.modification": makeModificationSurface({
            eligibility: null as never,
          }),
        },
      }),
    );
    expect(result).toEqual({ allowed: false, reason: "modification_draft" });
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

function setupValidModificationRunState(checkNowImpl?: () => Promise<void>) {
  useAuthStore.setState({
    token: "tok",
    user: { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
  });
  useWorkspaceStore.getState().registerSurface(makeModificationSurface());
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

  it("saves the exact settled confirmation independently from the form", async () => {
    setupValidRunState();
    const confirmation = makeConfirmationSnapshot({
      pendingParams: {
        ...makeConfirmationSnapshot().pendingParams,
        topic: "只存在於確認頁的題目",
        text_instruction: "確認頁專用的文本出題指示",
        per_question_params: JSON.stringify([
          { learning_content: ["Nf-IV-2"], question_type: "選擇題" },
          { learning_content: ["Na-IV-1"], question_type: "非選擇題" },
        ]),
      } as never,
      pendingPerQuestionParams: [
        { learning_content: ["Nf-IV-2"], question_type: "選擇題" },
        { learning_content: ["Na-IV-1"], question_type: "非選擇題" },
      ],
      clearedPaths: ["context", "per_question_params[1].learning_content"],
      redraws: { context: 2, "per_question_params[1].learning_content": 1 },
      pendingPrefill: {
        topic: "History carried topic",
        model_execute: "gemini-3.1-pro-preview",
        effort_execute: "high",
        image_generation_mode: "gpt_image",
      },
    });
    useWorkspaceStore.getState().registerSurface(makeConfirmationSurface({
      exportWorkspace: () => confirmation,
    }));
    vi.stubGlobal("location", { pathname: "/generate/natural_sciences", origin: "https://test.com", reload: vi.fn() });

    const result = await runSaveAndUpdate({
      navigate: vi.fn(),
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok");
    const saved = loadSnapshot("u1", result.snapshot_id);
    expect(saved?.confirmation).toEqual(confirmation);
    expect(saved?.form.fields).toEqual({});
  });

  it("saves received results and preserves unknown completion evidence", async () => {
    setupValidRunState();
    const results = makeResultsSnapshot();
    useWorkspaceStore.getState().registerSurface(makeResultsSurface(results));
    vi.stubGlobal("location", { pathname: "/generate/social_studies", origin: "https://test.com", reload: vi.fn() });

    const result = await runSaveAndUpdate({
      navigate: vi.fn(),
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok");
    const saved = loadSnapshot("u1", result.snapshot_id);
    expect(saved?.results).toEqual(results);
    expect(saved?.results?.completion).toBe("unknown");
    expect(saved?.results?.terminalEvidence).toBe(false);
  });

  it("saves a History-only modification draft with its route and base evidence", async () => {
    setupValidModificationRunState();
    vi.stubGlobal("location", {
      pathname: "/history/history-record",
      origin: "https://test.com",
      reload: vi.fn(),
    });
    const navigate = vi.fn();

    const result = await runSaveAndUpdate({
      navigate,
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok");
    const saved = loadSnapshot("u1", result.snapshot_id);
    expect(saved?.route).toBe("/history/history-record");
    expect(saved?.subject).toBe("social_studies");
    expect(saved?.form).toEqual({ kind: "form", version: 1, fields: {} });
    expect(saved?.modification).toEqual(makeModificationSnapshot());
    expect(navigate).toHaveBeenCalledOnce();
  });

  it("allows a settled replacement and persists the latest received result", async () => {
    setupValidModificationRunState();
    const replacement = {
      record_id: "history-child",
      question: { id: "history-child-question", 題目: ["replacement"] },
      ripple_report: ["題目[0]"],
      verified: true,
      verification: { passed: true },
      failure_details: null,
    };
    const snapshot = makeModificationSnapshot({
      recordId: "history-child",
      questionId: "history-child-question",
      contentIdentity: "canonical-replacement",
      replacement,
      annotations: [],
    });
    useWorkspaceStore.getState().updateSurface("history.modification", {
      hasEditableState: false,
      hasReceivedResults: true,
      exportWorkspace: () => snapshot,
    });
    vi.stubGlobal("location", {
      pathname: "/history/history-record",
      origin: "https://test.com",
      reload: vi.fn(),
    });

    const result = await runSaveAndUpdate({
      navigate: vi.fn(),
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok");
    expect(loadSnapshot("u1", result.snapshot_id)?.modification?.replacement).toEqual(replacement);
  });

  it("preserves a settled error/progress workspace even when no question body arrived", async () => {
    setupValidRunState();
    const errorResults = {
      ...makeResultsSnapshot(),
      results: [], displayResults: [], progressLines: ["started"], errorMessage: "provider unavailable",
    } satisfies ResultsWorkspaceSnapshot;
    useWorkspaceStore.getState().registerSurface(makeResultsSurface(errorResults, { hasReceivedResults: false }));
    vi.stubGlobal("location", { pathname: "/generate/natural_sciences", origin: "https://test.com", reload: vi.fn() });

    const result = await runSaveAndUpdate({
      navigate: vi.fn(), origin: "https://test.com", environment: "production", buildId: "build-A",
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok");
    expect(loadSnapshot("u1", result.snapshot_id)?.results).toMatchObject({
      results: [], displayResults: [], progressLines: ["started"], errorMessage: "provider unavailable",
    });
  });

  it("refuses when a late callback mutates the settled confirmation source", async () => {
    const confirmation = makeConfirmationSnapshot({
      pendingParams: {
        ...makeConfirmationSnapshot().pendingParams,
        topic: "before callback",
      } as never,
    });
    setupValidRunState(async () => {
      confirmation.pendingParams.topic = "late callback mutation";
    });
    useWorkspaceStore.getState().registerSurface(makeConfirmationSurface({
      exportWorkspace: () => confirmation,
    }));
    vi.stubGlobal("location", { pathname: "/generate/math", origin: "https://test.com", reload: vi.fn() });

    const result = await runSaveAndUpdate({
      navigate: vi.fn(),
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });

    expect(result).toEqual({ ok: false, reason: "workspace_changed", retryable: true });
    expect(Object.keys(localStorage).filter((key) => key.startsWith("exam_recovery_")))
      .toHaveLength(0);
  });

  it("continues refusing an active operation while confirmation is settled", async () => {
    setupValidRunState();
    useWorkspaceStore.getState().registerSurface(makeConfirmationSurface());
    const operation = useWorkspaceStore.getState().beginOperation(
      "prompt_preview",
      "generate.confirmation",
    );
    vi.stubGlobal("location", { pathname: "/generate/math", origin: "https://test.com", reload: vi.fn() });

    const result = await runSaveAndUpdate({
      navigate: vi.fn(),
      origin: "https://test.com",
      environment: "production",
      buildId: "build-A",
    });
    operation.end("completed");

    expect(result).toEqual({ ok: false, reason: "operation_active", retryable: false });
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
