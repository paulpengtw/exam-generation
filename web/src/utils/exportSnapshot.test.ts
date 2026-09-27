/**
 * TDD tests for exportSnapshot.ts (issue #751).
 *
 * Covers:
 * - captureFromEvidence: single question from v2 evidence
 * - captureFromGeneratedQuestion: single question from legacy item
 * - captureBatch: mixed draft/final/placeholder batch
 * - legacy (unknown order) batch
 * - captureFromHistory: history record
 * - stripExport: deep-equals captured original; live state unmodified
 * - filenames: draft / 含草稿 / final
 * - final without terminal → final+unknown (not called draft)
 * - new revision during export keeps captured version/time
 * - bodyless placeholders excluded
 */

import { describe, expect, it } from "vitest";
import type { ExamQuestion } from "../hooks/useGenerate";
import type { QuestionEvidence } from "../lib/generationEvidence";
import type { GeneratedQuestion } from "../hooks/useGenerate";
import type { HistoryDetail } from "../api/client";
import {
  captureFromEvidence,
  captureFromGeneratedQuestion,
  captureBatch,
  captureFromHistory,
  stripExport,
  singleQuestionFilename,
  batchFilename,
  type ExportedQuestion,
} from "./exportSnapshot";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeQuestion(id: string, extra: Partial<ExamQuestion> = {}): ExamQuestion {
  return {
    id,
    情境: ["個人"],
    題型種類: "single",
    題型: "選擇題",
    題目: ["題目"],
    正確解題分析: ["解析"],
    ...extra,
  };
}

function makeEvidence(
  questionId: string,
  overrides: Partial<QuestionEvidence> = {},
): QuestionEvidence {
  return {
    questionId,
    index: 0,
    processing: "ended",
    content: {
      receipt: "final",
      revision: 3,
      question: makeQuestion(questionId),
      phase: "verified",
    },
    terminal: {
      termination_reason: "normal",
      has_final: true,
      final_revision: 3,
      delivery_status: "complete",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "passed", content_revision: 3 },
    },
    terminalConflict: false,
    terminalConflictReason: undefined,
    reviewConflict: false,
    contentConflict: false,
    contentConflictReason: undefined,
    finalPending: false,
    finalMissing: false,
    review: { status: "passed", revision: 3 },
    trail: [],
    figurePolicyTrail: [],
    referenceExampleRecord: undefined,
    activity: { operations: {}, calls: {} },
    ...overrides,
  };
}

function makeGeneratedQuestion(
  id: string,
  isFinal: boolean,
  index: number,
  positionUnknown?: boolean,
): GeneratedQuestion {
  return {
    index,
    question: makeQuestion(id),
    phase: "verified",
    isFinal,
    stableId: id,
    contentRevision: 2,
    positionUnknown,
  };
}

// ---------------------------------------------------------------------------
// captureFromEvidence
// ---------------------------------------------------------------------------

describe("captureFromEvidence", () => {
  it("captures final question with correct _export fields", () => {
    const q = makeQuestion("qA");
    const ev = makeEvidence("qA");
    const exportedAt = "2026-09-27T10:00:00.000Z";
    const snapshot = captureFromEvidence(q, ev, "run-123", exportedAt);

    expect(snapshot).not.toBeNull();
    expect(snapshot!.isDraft).toBe(false);
    expect(snapshot!.exported._export.format_version).toBe(1);
    expect(snapshot!.exported._export.exported_at).toBe(exportedAt);
    expect(snapshot!.exported._export.is_draft).toBe(false);
    expect(snapshot!.exported._export.run_id).toBe("run-123");
    expect(snapshot!.exported._export.index).toBe(0);
    expect(snapshot!.exported._export.content_revision).toBe(3);
    expect(snapshot!.exported._export.processing).toBe("ended");
    expect(snapshot!.exported._export.termination_reason).toBe("normal");
    expect(snapshot!.exported._export.delivery_status).toBe("complete");
    expect(snapshot!.exported._export.review.status).toBe("passed");
  });

  it("returns null for bodyless placeholder (receipt === 'none')", () => {
    const q = makeQuestion("qB");
    const ev = makeEvidence("qB", {
      content: { receipt: "none", revision: null, question: null, phase: null },
    });
    const snapshot = captureFromEvidence(q, ev, null, "2026-09-27T10:00:00.000Z");
    expect(snapshot).toBeNull();
  });

  it("captures draft question with is_draft = true", () => {
    const q = makeQuestion("qC");
    const ev = makeEvidence("qC", {
      processing: "running",
      content: { receipt: "draft", revision: 1, question: q, phase: "draft" },
      terminal: null,
      review: { status: "unknown", revision: null },
    });
    const snapshot = captureFromEvidence(q, ev, null, "2026-09-27T10:00:00.000Z");

    expect(snapshot).not.toBeNull();
    expect(snapshot!.isDraft).toBe(true);
    expect(snapshot!.exported._export.is_draft).toBe(true);
    expect(snapshot!.exported._export.termination_reason).toBeNull();
    expect(snapshot!.exported._export.delivery_status).toBeNull();
  });

  it("final without terminal → processing unknown, not draft", () => {
    const q = makeQuestion("qD");
    const ev = makeEvidence("qD", {
      processing: "unknown",
      terminal: null,
      review: { status: "unknown", revision: null },
    });
    const snapshot = captureFromEvidence(q, ev, null, "2026-09-27T10:00:00.000Z");

    expect(snapshot).not.toBeNull();
    expect(snapshot!.isDraft).toBe(false); // receipt === "final" → not a draft
    expect(snapshot!.exported._export.is_draft).toBe(false);
    expect(snapshot!.exported._export.processing).toBe("unknown");
    expect(snapshot!.exported._export.termination_reason).toBeNull();
  });

  it("new revision pushed during export keeps captured version/time", () => {
    const q = makeQuestion("qE");
    const ev = makeEvidence("qE", {
      content: { receipt: "final", revision: 3, question: q, phase: "verified" },
    });
    const exportedAt = "2026-09-27T10:00:00.000Z";
    const snapshot = captureFromEvidence(q, ev, null, exportedAt);

    // Simulate new revision arriving – mutate the evidence AFTER capture
    (ev.content as { revision: number }).revision = 4;

    // Snapshot must still hold revision 3
    expect(snapshot!.exported._export.content_revision).toBe(3);
    expect(snapshot!.exported._export.exported_at).toBe(exportedAt);
  });

  it("review revision mismatch → review.status unknown", () => {
    const q = makeQuestion("qF");
    const ev = makeEvidence("qF", {
      content: { receipt: "final", revision: 3, question: q, phase: "verified" },
      review: { status: "passed", revision: 2 }, // mismatched revision
    });
    const snapshot = captureFromEvidence(q, ev, null, "2026-09-27T10:00:00.000Z");

    expect(snapshot!.exported._export.review.status).toBe("unknown");
    expect(snapshot!.exported._export.review.unknown_reason).toBe("review_revision_mismatch");
  });

  it("null run_id produces null run_id in _export", () => {
    const q = makeQuestion("qG");
    const ev = makeEvidence("qG");
    const snapshot = captureFromEvidence(q, ev, null, "2026-09-27T10:00:00.000Z");
    expect(snapshot!.exported._export.run_id).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// captureFromGeneratedQuestion
// ---------------------------------------------------------------------------

describe("captureFromGeneratedQuestion", () => {
  it("captures legacy final item", () => {
    const item = makeGeneratedQuestion("qH", true, 0);
    const snapshot = captureFromGeneratedQuestion(item, null, "2026-09-27T10:00:00.000Z");

    expect(snapshot).not.toBeNull();
    expect(snapshot!.isDraft).toBe(false);
    expect(snapshot!.exported._export.is_draft).toBe(false);
    expect(snapshot!.exported._export.processing).toBe("unknown");
    expect(snapshot!.exported._export.termination_reason).toBeNull();
  });

  it("captures legacy draft item", () => {
    const item = makeGeneratedQuestion("qI", false, 1);
    const snapshot = captureFromGeneratedQuestion(item, null, "2026-09-27T10:00:00.000Z");

    expect(snapshot).not.toBeNull();
    expect(snapshot!.isDraft).toBe(true);
    expect(snapshot!.exported._export.is_draft).toBe(true);
  });

  it("unknown position → index null in _export", () => {
    const item = makeGeneratedQuestion("qJ", true, 0, true);
    const snapshot = captureFromGeneratedQuestion(item, null, "2026-09-27T10:00:00.000Z");
    expect(snapshot!.exported._export.index).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// captureBatch
// ---------------------------------------------------------------------------

describe("captureBatch — mixed draft/final/placeholder", () => {
  it("omits bodyless placeholders, keeps draft and final", () => {
    const evA = makeEvidence("qA", { index: 0 });
    const evB = makeEvidence("qB", {
      index: 1,
      processing: "running",
      content: {
        receipt: "draft",
        revision: 1,
        question: makeQuestion("qB"),
        phase: "draft",
      },
      terminal: null,
      review: { status: "unknown", revision: null },
    });
    const evC = makeEvidence("qC", {
      index: 2,
      content: { receipt: "none", revision: null, question: null, phase: null },
    });

    const displayResults: GeneratedQuestion[] = [
      { index: 0, question: makeQuestion("qA"), phase: "verified", isFinal: true, stableId: "qA", contentRevision: 3 },
      { index: 1, question: makeQuestion("qB"), phase: "draft", isFinal: false, stableId: "qB", contentRevision: 1 },
      // qC has no question
    ];

    const batch = captureBatch({
      displayResults,
      evidenceByQuestionId: { qA: evA, qB: evB, qC: evC },
      runId: "run-1",
      exportedAt: "2026-09-27T10:00:00.000Z",
    });

    expect(batch.exported).toHaveLength(2);
    expect(batch.hasDraft).toBe(true);
    expect(batch.exported[0]._export.index).toBe(0);
    expect(batch.exported[1]._export.is_draft).toBe(true);
  });

  it("orders by known index; unknown-index legacy items go last", () => {
    const displayResults: GeneratedQuestion[] = [
      { index: 2, question: makeQuestion("qC"), phase: "verified", isFinal: true, stableId: "qC", contentRevision: 1 },
      { index: 0, question: makeQuestion("qA"), phase: "verified", isFinal: true, stableId: "qA", contentRevision: 1 },
      { index: 10001, question: makeQuestion("qUnk"), phase: "verified", isFinal: false, stableId: "qUnk", contentRevision: 1, positionUnknown: true },
    ];

    const batch = captureBatch({
      displayResults,
      evidenceByQuestionId: {},
      runId: null,
      exportedAt: "2026-09-27T10:00:00.000Z",
    });

    expect(batch.exported).toHaveLength(3);
    // Should be sorted: qA (0), qC (2), qUnk (Infinity)
    expect(batch.exported[0].id).toBe("qA");
    expect(batch.exported[1].id).toBe("qC");
    expect(batch.exported[2].id).toBe("qUnk");
    expect(batch.exported[2]._export.index).toBeNull(); // positionUnknown → null
  });

  it("all final, no draft → hasDraft false", () => {
    const displayResults: GeneratedQuestion[] = [
      { index: 0, question: makeQuestion("qA"), phase: "verified", isFinal: true, stableId: "qA", contentRevision: 1 },
      { index: 1, question: makeQuestion("qB"), phase: "verified", isFinal: true, stableId: "qB", contentRevision: 1 },
    ];

    const batch = captureBatch({
      displayResults,
      evidenceByQuestionId: {},
      runId: null,
      exportedAt: "2026-09-27T10:00:00.000Z",
    });

    expect(batch.hasDraft).toBe(false);
  });

  it("shared exportedAt is identical across all items", () => {
    const exportedAt = "2026-09-27T10:00:00.000Z";
    const displayResults: GeneratedQuestion[] = [
      { index: 0, question: makeQuestion("qA"), phase: "verified", isFinal: true, stableId: "qA", contentRevision: 1 },
      { index: 1, question: makeQuestion("qB"), phase: "verified", isFinal: false, stableId: "qB", contentRevision: 1 },
    ];

    const batch = captureBatch({
      displayResults,
      evidenceByQuestionId: {},
      runId: null,
      exportedAt,
    });

    for (const item of batch.exported) {
      expect(item._export.exported_at).toBe(exportedAt);
    }
  });
});

// ---------------------------------------------------------------------------
// captureFromHistory
// ---------------------------------------------------------------------------

describe("captureFromHistory", () => {
  const makeHistoryDetail = (overrides: Partial<HistoryDetail> = {}): HistoryDetail => ({
    id: "hist-1",
    subject: "math",
    question_id: "q-legacy-1",
    created_at: "2026-01-01T00:00:00Z",
    status: "completed",
    error: null,
    generation_log_id: "log-abc",
    params_json: {},
    question_json: makeQuestion("q-legacy-1") as unknown as Record<string, unknown>,
    verification_trail: null,
    figure_policy_trail: null,
    reference_example_record: null,
    ...overrides,
  });

  it("returns null when question_json is null", () => {
    const detail = makeHistoryDetail({ question_json: null });
    const result = captureFromHistory(detail, "2026-09-27T10:00:00.000Z");
    expect(result).toBeNull();
  });

  it("adds _export with run_id from generation_log_id", () => {
    const detail = makeHistoryDetail();
    const result = captureFromHistory(detail, "2026-09-27T10:00:00.000Z");

    expect(result).not.toBeNull();
    expect(result!._export.format_version).toBe(1);
    expect(result!._export.run_id).toBe("log-abc");
    expect(result!._export.is_draft).toBe(false);
    expect(result!._export.processing).toBe("ended");
    expect(result!._export.termination_reason).toBe("normal");
    expect(result!._export.delivery_status).toBe("complete");
    expect(result!._export.index).toBeNull();
    expect(result!._export.content_revision).toBeNull();
  });

  it("old data without evidence → null/unknown fields", () => {
    const detail = makeHistoryDetail({ generation_log_id: null });
    const result = captureFromHistory(detail, "2026-09-27T10:00:00.000Z");

    expect(result!._export.run_id).toBeNull();
    expect(result!._export.review.status).toBe("unknown");
    expect(result!._export.review.content_revision).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// stripExport
// ---------------------------------------------------------------------------

describe("stripExport", () => {
  it("deep-equals captured original after stripping", () => {
    const q = makeQuestion("qZ", { 出題概念: "some concept" });
    const ev = makeEvidence("qZ", {
      content: { receipt: "final", revision: 2, question: q, phase: "verified" },
      review: { status: "passed", revision: 2 },
    });
    const snapshot = captureFromEvidence(q, ev, "run-42", "2026-09-27T10:00:00.000Z");
    expect(snapshot).not.toBeNull();

    const stripped = stripExport(snapshot!.exported);
    expect(stripped).toEqual(snapshot!.captured);
    // The original question must be unmodified
    expect((q as unknown as { _export?: unknown })._export).toBeUndefined();
  });

  it("live question object is not mutated after batch capture", () => {
    const originalQ = makeQuestion("qLive");
    const originalCopy = JSON.parse(JSON.stringify(originalQ)) as ExamQuestion;
    const item: GeneratedQuestion = {
      index: 0, question: originalQ, phase: "verified", isFinal: true,
      stableId: "qLive", contentRevision: 1,
    };

    captureBatch({
      displayResults: [item],
      evidenceByQuestionId: {},
      runId: null,
      exportedAt: "2026-09-27T10:00:00.000Z",
    });

    // The original question must NOT have been modified
    expect(originalQ).toEqual(originalCopy);
    expect((originalQ as unknown as { _export?: unknown })._export).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Filename helpers
// ---------------------------------------------------------------------------

describe("singleQuestionFilename", () => {
  it("draft includes 草稿 prefix", () => {
    expect(singleQuestionFilename("q123", true)).toBe("草稿_q123.json");
  });

  it("final has plain id filename", () => {
    expect(singleQuestionFilename("q123", false)).toBe("q123.json");
  });

  it("empty id uses fallback", () => {
    expect(singleQuestionFilename("", false)).toBe("question.json");
  });
});

describe("batchFilename", () => {
  it("contains 含草稿 prefix when hasDraft", () => {
    const name = batchFilename(true);
    expect(name).toMatch(/^含草稿_batch_/);
    expect(name).toMatch(/\.json$/);
  });

  it("no prefix when all final", () => {
    const name = batchFilename(false);
    expect(name).toMatch(/^batch_/);
    expect(name).not.toMatch(/草稿/);
  });
});

// ---------------------------------------------------------------------------
// JSON read-back shape verification
// ---------------------------------------------------------------------------

describe("JSON read-back", () => {
  it("single question exports as an object (not array), batch as array", () => {
    const q = makeQuestion("qSingle");
    const ev = makeEvidence("qSingle");
    const exportedAt = "2026-09-27T10:00:00.000Z";
    const snapshot = captureFromEvidence(q, ev, null, exportedAt);

    const singleJson = JSON.stringify(snapshot!.exported);
    const parsed = JSON.parse(singleJson) as ExportedQuestion;
    expect(Array.isArray(parsed)).toBe(false);
    expect(parsed._export.format_version).toBe(1);
    expect(parsed.id).toBe("qSingle");

    // Batch
    const displayResults: GeneratedQuestion[] = [
      { index: 0, question: makeQuestion("qA"), phase: "verified", isFinal: true, stableId: "qA", contentRevision: 1 },
      { index: 1, question: makeQuestion("qB"), phase: "draft", isFinal: false, stableId: "qB", contentRevision: 1 },
    ];
    const batch = captureBatch({ displayResults, evidenceByQuestionId: {}, runId: null, exportedAt });
    const batchJson = JSON.stringify(batch.exported);
    const parsedBatch = JSON.parse(batchJson) as ExportedQuestion[];
    expect(Array.isArray(parsedBatch)).toBe(true);
    expect(parsedBatch).toHaveLength(2);
  });

  it("all items in batch share the same exported_at", () => {
    const exportedAt = "2026-09-27T12:34:56.000Z";
    const displayResults: GeneratedQuestion[] = [
      { index: 0, question: makeQuestion("q1"), phase: "verified", isFinal: true, stableId: "q1", contentRevision: 1 },
      { index: 1, question: makeQuestion("q2"), phase: "draft", isFinal: false, stableId: "q2", contentRevision: 1 },
    ];
    const batch = captureBatch({ displayResults, evidenceByQuestionId: {}, runId: null, exportedAt });

    for (const item of batch.exported) {
      expect(item._export.exported_at).toBe(exportedAt);
    }
  });

  it("original id is preserved in exported question", () => {
    const q = makeQuestion("my-custom-id-123");
    const ev = makeEvidence("my-custom-id-123");
    const snapshot = captureFromEvidence(q, ev, null, "2026-09-27T10:00:00.000Z");
    expect(snapshot!.exported.id).toBe("my-custom-id-123");
  });
});
