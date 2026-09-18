/**
 * Tests for recovery format parser — issue #772.
 * Written BEFORE the implementation (red phase).
 */
import { describe, it, expect } from "vitest";
import {
  parseRecoverySnapshot,
  RECOVERY_FORMAT_V1,
} from "./format";
import type { RecoverySnapshotV1 } from "./format";
import type { ConfirmationWorkspaceSnapshot } from "../workspace/adapters/types";
import type { ResultsWorkspaceSnapshot } from "../workspace/adapters/types";
import type { ModificationWorkspaceSnapshot } from "../workspace/adapters/types";

function makeValidSnapshot(): RecoverySnapshotV1 {
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
  };
}

function makeValidConfirmation(): ConfirmationWorkspaceSnapshot {
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
      seed: 17,
      drawn: ["context"],
    } as never,
    pendingPerQuestionParams: null,
    clearedPaths: [],
    redraws: {},
    hasPendingConfirmationEdits: false,
    coreQuestionResolution: "generated",
    historyDraftChoice: "history",
    pendingPrefill: {
      topic: "保留的歷史預填",
      model_execute: "gemini-3.1-pro-preview",
    },
  };
}

function makeValidResults(): ResultsWorkspaceSnapshot {
  return {
    kind: "results",
    version: 1,
    results: [{ id: "q-1", 情境: [], 題型種類: "single", 題型: "multiple_choice", 題目: ["q"], 正確解題分析: ["a"] }],
    displayResults: [{ index: 0, question: { id: "q-1", 情境: [], 題型種類: "single", 題型: "multiple_choice", 題目: ["q"], 正確解題分析: ["a"] }, phase: "verified", isFinal: true }],
    progressLines: ["done"],
    errorMessage: null,
    startedAt: 1,
    finishedAt: 2,
    subQuestionTotal: null,
    requestedTotal: 1,
    submittedSubQuestionCount: null,
    completion: "unknown",
    processing: "unknown",
    terminalEvidence: false,
    evidence: [{
      stableId: "q-1", index: 0, receipt: "final", processing: "unknown",
      contentRevision: null, terminal: "unknown",
      review: { status: "unknown", contentRevision: null },
    }],
  };
}

function makeValidModification(): ModificationWorkspaceSnapshot {
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
      segments: [{ field_path: "文本", start: 0, end: 4, quoted_text: "passage" }],
      instruction: "Clarify this passage",
    }],
    replacement: null,
  };
}

const OPTS = {
  expectedAccountId: "user-1",
  expectedOrigin: "https://example.com",
  expectedEnvironment: "production",
};

describe("parseRecoverySnapshot", () => {
  it("accepts a valid snapshot", () => {
    const result = parseRecoverySnapshot(makeValidSnapshot(), OPTS);
    expect(result.ok).toBe(true);
  });

  it("accepts an exact optional confirmation snapshot", () => {
    const confirmation = makeValidConfirmation();
    const result = parseRecoverySnapshot(
      { ...makeValidSnapshot(), confirmation },
      OPTS,
    );

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.snapshot.confirmation).toEqual(confirmation);
  });

  it("accepts an exact optional received-results snapshot", () => {
    const results = makeValidResults();
    const result = parseRecoverySnapshot({ ...makeValidSnapshot(), results }, OPTS);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.snapshot.results).toEqual(results);
  });

  it("accepts an exact optional modification snapshot", () => {
    const modification = makeValidModification();
    const result = parseRecoverySnapshot(
      { ...makeValidSnapshot(), modification },
      OPTS,
    );

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.snapshot.modification).toEqual(modification);
  });

  it("rejects a malformed optional received-results snapshot", () => {
    const result = parseRecoverySnapshot({
      ...makeValidSnapshot(),
      results: { kind: "results", version: 1 },
    }, OPTS);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid_form");
  });

  it("rejects a malformed optional confirmation snapshot", () => {
    const result = parseRecoverySnapshot(
      {
        ...makeValidSnapshot(),
        confirmation: { ...makeValidConfirmation(), pendingPrefill: [] },
      },
      OPTS,
    );

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid_form");
  });

  it("rejects a malformed optional modification snapshot", () => {
    const result = parseRecoverySnapshot({
      ...makeValidSnapshot(),
      modification: { ...makeValidModification(), eligibility: null },
    }, OPTS);

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid_form");
  });

  it("rejects null", () => {
    const result = parseRecoverySnapshot(null, OPTS);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("malformed");
  });

  it("rejects a non-object", () => {
    const result = parseRecoverySnapshot("string", OPTS);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("malformed");
  });

  it("rejects unknown schema", () => {
    const snap = { ...makeValidSnapshot(), schema: "exam-generation.recovery/99" };
    const result = parseRecoverySnapshot(snap, OPTS);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("unknown_schema");
  });

  it("rejects missing required fields", () => {
    const snap = { ...makeValidSnapshot() };
    delete (snap as Partial<RecoverySnapshotV1>).snapshot_id;
    const result = parseRecoverySnapshot(snap, OPTS);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("malformed");
  });

  it("rejects wrong account_id", () => {
    const snap = { ...makeValidSnapshot(), account_id: "other-user" };
    const result = parseRecoverySnapshot(snap, OPTS);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("wrong_account");
  });

  it("rejects wrong origin", () => {
    const snap = { ...makeValidSnapshot(), origin: "https://other.com" };
    const result = parseRecoverySnapshot(snap, OPTS);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("wrong_origin");
  });

  it("rejects environment mismatch", () => {
    const snap = { ...makeValidSnapshot(), environment: "staging" };
    const result = parseRecoverySnapshot(snap, OPTS);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("environment_mismatch");
  });

  it("rejects invalid form (wrong kind)", () => {
    const snap = {
      ...makeValidSnapshot(),
      form: { kind: "confirmation", version: 1 },
    };
    const result = parseRecoverySnapshot(snap, OPTS);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid_form");
  });

  it("rejects invalid form (wrong version)", () => {
    const snap = {
      ...makeValidSnapshot(),
      form: { kind: "form", version: 99 },
    };
    const result = parseRecoverySnapshot(snap, OPTS);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("invalid_form");
  });

  it("accepts null source_release_revision (first ever release)", () => {
    const snap = { ...makeValidSnapshot(), source_release_revision: null };
    const result = parseRecoverySnapshot(snap, OPTS);
    expect(result.ok).toBe(true);
  });
});
