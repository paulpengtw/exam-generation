/**
 * Atomic snapshot capture for single-question, batch, and history JSON exports.
 *
 * One click → one snapshot frozen at that instant. Later generation events,
 * new revisions, or live-state mutations do NOT alter an in-progress export.
 * `_export` is additive only to the downloaded copy; live/stored question
 * objects are never modified.
 *
 * Format version: 1  (exam-generation.question-snapshot-export/1)
 *
 * Schema decisions from issue #732 resolution and issue #751:
 * - Single download → question object (not array).
 * - Batch download → question array, ordered by known original index; legacy
 *   unknown-order items are marked and kept stable.
 * - Bodyless placeholder cards (receipt === "none") are excluded.
 * - `_export.is_draft` = true when receipt is "draft".
 * - final with no terminal stays "final+unknown"; NOT relabeled as draft.
 * - Old data without evidence → null / "unknown" placeholders, never fabricated.
 * - Stripping `_export` from the downloaded copy restores the original question.
 */

import type { ExamQuestion } from "../hooks/useGenerate";
import type {
  QuestionEvidence,
  GenerationSlotReference,
  QuestionTerminalPayload,
} from "../lib/generationEvidence";
import type { GeneratedQuestion } from "../hooks/useGenerate";
import type { HistoryDetail } from "../api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Kind of visible image source captured at click time. */
export type ImageSourceKind = "png_base64" | "chart_spec_preview" | "known_missing";

/**
 * A single captured image source for one question/subquestion slot.
 * Bound to the content revision at the time of capture.
 * Consumed by ODT export (#752) and rasterization (#753).
 */
export interface CapturedImageSource {
  kind: ImageSourceKind;
  /** Only for kind === "png_base64": the embedded PNG image data (base64 string). */
  pngBase64?: string;
  /** Only for kind === "chart_spec_preview": the chart/image spec for FigureRenderer. */
  chartSpec?: Record<string, unknown>;
  /**
   * Only for kind === "chart_spec_preview": HTML markup captured from the live
   * FigureRenderer DOM at click time (same-source capture for #753).
   * When present, the rasterizer uses this instead of re-rendering offscreen.
   */
  previewMarkup?: string;
  /** The content revision this source was captured at; null for legacy/unknown. */
  contentRevision: number | null;
}

/**
 * Frozen visible image sources per position, keyed by slot:
 * - `"stem"` → top-level question image
 * - `"sq{序號}"` → per-subquestion image (1-based 序號)
 *
 * Only slots that have an image, chart spec, or are known missing are included.
 * This lives on QuestionSnapshot only; it does NOT appear in the downloaded JSON body.
 */
export type CapturedImageSources = Record<string, CapturedImageSource>;

export interface SnapshotReview {
  status: "passed" | "failed" | "skipped" | "unknown";
  content_revision: number | null;
  unknown_reason?: string;
}

export interface ExportMeta {
  format_version: 1;
  exported_at: string; // ISO 8601 UTC
  is_draft: boolean;
  run_id: string | null;
  /** 0-based original index in the batch; null when unknown (legacy) */
  index: number | null;
  /** null when unknown / legacy */
  content_revision: number | null;
  processing: "waiting" | "running" | "ended" | "unknown";
  termination_reason: "normal" | "failed" | "cancelled" | null;
  delivery_status: "complete" | "partial" | "none" | "unknown" | null;
  missing: GenerationSlotReference[];
  review: SnapshotReview;
}

export type ExportedQuestion = ExamQuestion & { _export: ExportMeta };

export interface QuestionSnapshot {
  /** The frozen question object with _export metadata appended */
  exported: ExportedQuestion;
  /** The immutable question object exactly as captured (no _export) */
  captured: ExamQuestion;
  isDraft: boolean;
  /** 0-based original index; null = position unknown */
  index: number | null;
  /**
   * Frozen visible image sources per position at click time.
   * Consumed by #752 (ODT) and #753 (rasterization); NOT in the downloaded JSON body.
   */
  imageSources: CapturedImageSources;
}

export interface BatchSnapshot {
  exported: ExportedQuestion[];
  /** Whether any question in the batch is a draft */
  hasDraft: boolean;
  /** Shared export time (ISO 8601 UTC) */
  exportedAt: string;
}

// ---------------------------------------------------------------------------
// Shared slot-reference conversion
// ---------------------------------------------------------------------------

/**
 * Resolves a GenerationSlotReference to a 1-based subquestion 序號.
 *
 * The server stores slot positions as 0-based `subquestion_index` (validated
 * `>= 0` in `event_protocol.py`).  Subquestion objects always carry a 1-based
 * `序號` field (= slot_index + 1).  **Never compare a raw `subquestion_index`
 * value directly to a `序號`** — use this helper instead.
 *
 * Resolution priority:
 *  1. `subquestion_id` present AND a matching subquestion found in `subquestions`
 *     → return that subquestion's `序號`.
 *  2. `subquestion_index` is a non-negative integer
 *     → return `subquestion_index + 1`.
 *  3. Neither present / matching → return `null` (stem-level or unresolvable slot).
 *
 * Used by both `captureImageSources` and `odt.ts` so the 0-based→1-based
 * conversion is never duplicated or done ad-hoc.
 */
export function slotRefSeqno(
  slot: GenerationSlotReference,
  subquestions?: ReadonlyArray<{ id?: string; 序號: number }>,
): number | null {
  if (slot.subquestion_id && subquestions) {
    const match = subquestions.find((sq) => sq.id === slot.subquestion_id);
    if (match !== undefined) return match.序號;
  }
  if (typeof slot.subquestion_index === "number" && slot.subquestion_index >= 0) {
    return slot.subquestion_index + 1;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Deep copy a plain question object, excluding any existing `_export` field. */
function captureQuestion(question: ExamQuestion): ExamQuestion {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { _export: _removed, ...rest } = question as ExamQuestion & { _export?: unknown };
  return JSON.parse(JSON.stringify(rest)) as ExamQuestion;
}

function buildExportMeta(
  params: {
    exportedAt: string;
    isDraft: boolean;
    runId: string | null;
    index: number | null;
    contentRevision: number | null;
    processing: ExportMeta["processing"];
    terminationReason: ExportMeta["termination_reason"];
    deliveryStatus: ExportMeta["delivery_status"];
    missing: GenerationSlotReference[];
    review: SnapshotReview;
  },
): ExportMeta {
  return {
    format_version: 1,
    exported_at: params.exportedAt,
    is_draft: params.isDraft,
    run_id: params.runId,
    index: params.index,
    content_revision: params.contentRevision,
    processing: params.processing,
    termination_reason: params.terminationReason,
    delivery_status: params.deliveryStatus,
    missing: params.missing,
    review: params.review,
  };
}

// ---------------------------------------------------------------------------
// Image source capture
// ---------------------------------------------------------------------------

/**
 * Capture visible image sources from a (deep-copied) question at a given revision.
 *
 * Priority per slot:
 *   1. image_base64 present → "png_base64"
 *   2. chart_spec present (no image_base64) → "chart_spec_preview"
 *   3. slot in terminal.missing for kind="image" → "known_missing"
 *   4. none → slot omitted from result
 *
 * IMPORTANT: call this AFTER captureQuestion() so the question is already an
 * immutable deep copy. Any later mutations to the source question do not affect
 * the returned sources.
 *
 * The `contentRevision` stored on each source binds it to the snapshot revision.
 * A later image arriving at a different revision is never silently substituted.
 */
function captureImageSources(
  question: ExamQuestion,
  contentRevision: number | null,
  terminal: QuestionTerminalPayload | null,
): CapturedImageSources {
  const sources: CapturedImageSources = {};

  // Build lookup for missing image slots from terminal.missing
  // Stem: subquestion_id is absent/null and subquestion_index is absent/null
  const missingStemImage =
    terminal?.missing.some(
      (s) => s.kind === "image" && !s.subquestion_id && s.subquestion_index == null,
    ) ?? false;
  // Per-subquestion missing images: resolve to 1-based 序號 via slotRefSeqno
  // so 0-based server slot indices are never directly compared to 1-based 序號.
  // subquestion_id is preferred when present; subquestion_index+1 is the fallback.
  const subqs = question.subquestions;
  const missingSubqSeqnos = new Set<number>(
    (terminal?.missing ?? [])
      .filter((s) => s.kind === "image" && (s.subquestion_id != null || s.subquestion_index != null))
      .flatMap((s) => {
        const seqno = slotRefSeqno(s, subqs);
        return seqno !== null ? [seqno] : [];
      }),
  );

  // --- Stem image ---
  if (question.image_base64) {
    sources["stem"] = {
      kind: "png_base64",
      pngBase64: question.image_base64,
      contentRevision,
    };
  } else if (question.chart_spec) {
    sources["stem"] = {
      kind: "chart_spec_preview",
      chartSpec: question.chart_spec as Record<string, unknown>,
      contentRevision,
    };
  } else if (missingStemImage) {
    sources["stem"] = { kind: "known_missing", contentRevision };
  }

  // --- Per-subquestion images ---
  for (const sq of question.subquestions ?? []) {
    const key = `sq${sq.序號}`;
    if (sq.image_base64) {
      sources[key] = {
        kind: "png_base64",
        pngBase64: sq.image_base64,
        contentRevision,
      };
    } else if (sq.chart_spec) {
      sources[key] = {
        kind: "chart_spec_preview",
        chartSpec: sq.chart_spec as Record<string, unknown>,
        contentRevision,
      };
    } else if (missingSubqSeqnos.has(sq.序號)) {
      sources[key] = { kind: "known_missing", contentRevision };
    }
  }

  return sources;
}

// ---------------------------------------------------------------------------
// Single-question snapshot (from live evidence)
// ---------------------------------------------------------------------------

/**
 * Capture a single question from live generation evidence.
 * Returns null if the question has no body (receipt === "none").
 */
export function captureFromEvidence(
  question: ExamQuestion,
  evidence: QuestionEvidence,
  runId: string | null,
  exportedAt: string,
): QuestionSnapshot | null {
  // Bodyless placeholders are not exported
  if (evidence.content.receipt === "none") return null;
  if (!question) return null;

  const isDraft = evidence.content.receipt === "draft";
  const captured = captureQuestion(question);
  const index = typeof evidence.index === "number" ? evidence.index : null;
  const contentRevision =
    typeof evidence.content.revision === "number" && evidence.content.revision > 0
      ? evidence.content.revision
      : null;

  // Issue #749: when the terminal is disputed (terminalConflict=true), treat it
  // as absent for _export purposes — processing stays "unknown" and no terminal
  // values (termination_reason / delivery_status / missing) are exported.
  const effectiveTerminal = evidence.terminalConflict ? null : evidence.terminal;
  const processing: ExportMeta["processing"] = effectiveTerminal
    ? "ended"
    : evidence.processing === "ended"
    ? "ended"
    : evidence.processing;

  const terminationReason: ExportMeta["termination_reason"] =
    effectiveTerminal?.termination_reason ?? null;

  const deliveryStatus: ExportMeta["delivery_status"] =
    effectiveTerminal?.delivery_status ?? null;

  const missing: GenerationSlotReference[] = effectiveTerminal?.missing ?? [];

  // Review must match current content_revision
  let review: SnapshotReview;
  const rev = evidence.review;
  const matchesRevision =
    contentRevision !== null && rev.revision !== null && rev.revision === contentRevision;
  if (rev.status !== "unknown" && matchesRevision) {
    review = {
      status: rev.status,
      content_revision: rev.revision ?? null,
      unknown_reason: rev.reason,
    };
  } else {
    review = {
      status: "unknown",
      content_revision: null,
      unknown_reason:
        rev.status !== "unknown" ? "review_revision_mismatch" : (rev.reason ?? undefined),
    };
  }

  const exportMeta = buildExportMeta({
    exportedAt,
    isDraft,
    runId,
    index,
    contentRevision,
    processing,
    terminationReason,
    deliveryStatus,
    missing,
    review,
  });

  const exported: ExportedQuestion = { ...captured, _export: exportMeta };
  // Image sources are captured from the actual terminal (if any), regardless of
  // whether the terminal is disputed — the dispute only affects _export metadata.
  const imageSources = captureImageSources(captured, contentRevision, evidence.terminal);
  return { exported, captured, isDraft, index, imageSources };
}

// ---------------------------------------------------------------------------
// Single-question snapshot (from GeneratedQuestion / legacy path)
// ---------------------------------------------------------------------------

/**
 * Capture a single question from a `GeneratedQuestion` item (legacy or v2
 * without a separate evidence object).
 * Returns null if question is null.
 */
export function captureFromGeneratedQuestion(
  item: GeneratedQuestion,
  runId: string | null,
  exportedAt: string,
): QuestionSnapshot | null {
  if (!item.question) return null;

  const isDraft = !item.isFinal;
  const captured = captureQuestion(item.question);
  const index = item.positionUnknown ? null : item.index;
  const contentRevision =
    typeof item.contentRevision === "number" && item.contentRevision > 0
      ? item.contentRevision
      : null;

  const exportMeta = buildExportMeta({
    exportedAt,
    isDraft,
    runId,
    index,
    contentRevision,
    processing: "unknown",
    terminationReason: null,
    deliveryStatus: null,
    missing: [],
    review: { status: "unknown", content_revision: null },
  });

  const exported: ExportedQuestion = { ...captured, _export: exportMeta };
  const imageSources = captureImageSources(captured, contentRevision, null);
  return { exported, captured, isDraft, index, imageSources };
}

// ---------------------------------------------------------------------------
// Batch snapshot (from v2 RunEvidenceState + displayResults, or legacy)
// ---------------------------------------------------------------------------

export interface BatchSnapshotInput {
  /** Items with content available; bodyless items will be filtered out */
  displayResults: GeneratedQuestion[];
  /** Per-question evidence by questionId (v2 only; pass {} for legacy) */
  evidenceByQuestionId: Record<string, QuestionEvidence>;
  runId: string | null;
  exportedAt: string;
}

/**
 * Capture a batch. Returns all non-placeholder items in original order (or
 * stable legacy order). The shared exportedAt is frozen at capture time.
 */
export function captureBatch(input: BatchSnapshotInput): BatchSnapshot {
  const { displayResults, evidenceByQuestionId, runId, exportedAt } = input;

  const exported: ExportedQuestion[] = [];
  let hasDraft = false;

  // Sort by known index ascending; unknown-index items (positionUnknown) go last
  // using their ordinal position in displayResults as a stable tiebreaker.
  const sorted = displayResults
    .map((item, ordinal) => ({ item, ordinal }))
    .sort((a, b) => {
      const ai = a.item.positionUnknown ? Infinity : a.item.index;
      const bi = b.item.positionUnknown ? Infinity : b.item.index;
      if (ai !== bi) return ai - bi;
      return a.ordinal - b.ordinal;
    });

  for (const { item } of sorted) {
    if (!item.question) continue;

    const evidenceEntry =
      item.stableId ? evidenceByQuestionId[item.stableId] : undefined;

    let snapshot: QuestionSnapshot | null;
    if (evidenceEntry) {
      snapshot = captureFromEvidence(item.question, evidenceEntry, runId, exportedAt);
    } else {
      snapshot = captureFromGeneratedQuestion(item, runId, exportedAt);
    }

    if (snapshot === null) continue; // bodyless placeholder

    if (snapshot.isDraft) hasDraft = true;
    exported.push(snapshot.exported);
  }

  return { exported, hasDraft, exportedAt };
}

/**
 * Capture a batch as a list of QuestionSnapshot objects (includes imageSources).
 * Preferred over captureBatch() for ODT export, which needs per-snapshot imageSources.
 * Returns [snapshots, hasDraft] tuple.
 */
export function captureBatchSnapshots(input: BatchSnapshotInput): [QuestionSnapshot[], boolean] {
  const { displayResults, evidenceByQuestionId, runId, exportedAt } = input;

  const snapshots: QuestionSnapshot[] = [];
  let hasDraft = false;

  const sorted = displayResults
    .map((item, ordinal) => ({ item, ordinal }))
    .sort((a, b) => {
      const ai = a.item.positionUnknown ? Infinity : a.item.index;
      const bi = b.item.positionUnknown ? Infinity : b.item.index;
      if (ai !== bi) return ai - bi;
      return a.ordinal - b.ordinal;
    });

  for (const { item } of sorted) {
    if (!item.question) continue;

    const evidenceEntry =
      item.stableId ? evidenceByQuestionId[item.stableId] : undefined;

    let snapshot: QuestionSnapshot | null;
    if (evidenceEntry) {
      snapshot = captureFromEvidence(item.question, evidenceEntry, runId, exportedAt);
    } else {
      snapshot = captureFromGeneratedQuestion(item, runId, exportedAt);
    }

    if (snapshot === null) continue; // bodyless placeholder

    if (snapshot.isDraft) hasDraft = true;
    snapshots.push(snapshot);
  }

  return [snapshots, hasDraft];
}

// ---------------------------------------------------------------------------
// History record snapshot
// ---------------------------------------------------------------------------

/**
 * Build an `_export` annotation for a history detail record (persisted result).
 * History records are always final (isFinal = true).
 */
export function captureFromHistory(
  detail: HistoryDetail,
  exportedAt: string,
): ExportedQuestion | null {
  if (!detail.question_json) return null;

  const question = detail.question_json as unknown as ExamQuestion;
  const captured = captureQuestion(question);

  const exportMeta = buildExportMeta({
    exportedAt,
    isDraft: false,
    runId: detail.generation_log_id,
    index: null, // single record; order is not meaningful
    contentRevision: null, // persisted records have no revision field
    processing: "ended", // persisted = completed run
    terminationReason: "normal",
    deliveryStatus: "complete",
    missing: [],
    review: { status: "unknown", content_revision: null },
  });

  return { ...captured, _export: exportMeta };
}

/**
 * Capture a history record as a full QuestionSnapshot (includes imageSources).
 * Use this for ODT export; use `captureFromHistory` for JSON export.
 * Returns null when `detail.question_json` is absent.
 */
export function captureFromHistorySnapshot(
  detail: HistoryDetail,
  exportedAt: string,
): QuestionSnapshot | null {
  if (!detail.question_json) return null;

  const question = detail.question_json as unknown as ExamQuestion;
  const captured = captureQuestion(question);

  const exportMeta = buildExportMeta({
    exportedAt,
    isDraft: false,
    runId: detail.generation_log_id,
    index: null,
    contentRevision: null,
    processing: "ended",
    terminationReason: "normal",
    deliveryStatus: "complete",
    missing: [],
    review: { status: "unknown", content_revision: null },
  });

  const exported: ExportedQuestion = { ...captured, _export: exportMeta };
  // History records have no live terminal payload; no known-missing image slots.
  const imageSources = captureImageSources(captured, null, null);
  return { exported, captured, isDraft: false, index: null, imageSources };
}

// ---------------------------------------------------------------------------
// Filename helpers
// ---------------------------------------------------------------------------

/**
 * Generate a filename for a single question download.
 * Includes "草稿_" prefix when the question is a draft.
 */
export function singleQuestionFilename(
  questionId: string,
  isDraft: boolean,
): string {
  const base = questionId && questionId.length > 0 ? questionId : "question";
  return isDraft ? `草稿_${base}.json` : `${base}.json`;
}

/**
 * Generate a filename for a batch download.
 * Includes "含草稿_" prefix when any question is a draft.
 */
export function batchFilename(hasDraft: boolean): string {
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  return hasDraft ? `含草稿_batch_${ts}.json` : `batch_${ts}.json`;
}

/**
 * Strip `_export` from a downloaded question to recover the original structure.
 * Does NOT mutate the input.
 */
export function stripExport(exported: ExportedQuestion): ExamQuestion {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { _export: _removed, ...rest } = exported;
  return rest as ExamQuestion;
}

// ---------------------------------------------------------------------------
// DOM markup augmentation (issue #753 — same-source capture)
// ---------------------------------------------------------------------------

/**
 * Augment chart_spec_preview sources in a CapturedImageSources map with
 * HTML markup captured from the live FigureRenderer DOM.
 *
 * Call this immediately after capturing the snapshot, while the QuestionCard
 * DOM is still mounted. The domCaptureFn receives the slot key ("stem" or
 * "sq{序號}") and should return the serialized inner HTML of the FigureRenderer
 * container at that position (using serializeElementToMarkup from domCapture.ts),
 * or null if the element is not found.
 *
 * When markup is captured, it is stored in source.previewMarkup so the
 * rasterizer can use the same rendered output as the visible preview.
 */
export function augmentWithDomMarkup(
  sources: CapturedImageSources,
  domCaptureFn: (slotKey: string) => string | null,
): void {
  for (const [key, source] of Object.entries(sources)) {
    if (source.kind === "chart_spec_preview") {
      const markup = domCaptureFn(key);
      if (markup) {
        sources[key] = { ...source, previewMarkup: markup };
      }
    }
  }
}

// ---------------------------------------------------------------------------
// ODT filename helpers (issue #752)
// ---------------------------------------------------------------------------

/**
 * Generate a filename for a single question ODT download.
 * Includes "草稿_" prefix when the question is a draft.
 */
export function singleQuestionOdtFilename(
  questionId: string,
  isDraft: boolean,
): string {
  const base = questionId && questionId.length > 0 ? questionId : "question";
  return isDraft ? `草稿_${base}.odt` : `${base}.odt`;
}

/**
 * Generate a filename for a batch ODT download.
 * Includes "含草稿_" prefix when any question is a draft.
 */
export function batchOdtFilename(hasDraft: boolean): string {
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  return hasDraft ? `含草稿_batch_${ts}.odt` : `batch_${ts}.odt`;
}
