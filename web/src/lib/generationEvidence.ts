/**
 * F2: Per-question evidence reducer for generation stream v2.
 *
 * This module is pure (no React state) so it can be unit-tested without a DOM.
 */

import type {
  DraftPhase,
  ExamQuestion,
  FigurePolicyTrailEntry,
  ReferenceExampleRecordShape,
  VerificationTrailEntry,
} from "../hooks/useGenerate";
import type { RunManifest, DecodedEvent } from "./generationStream";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GenerationSlotReference {
  kind: "subquestion" | "image";
  question_id: string;
  subquestion_id?: string | null;
  subquestion_index?: number | null;
  reason?: string;
}

export interface QuestionTerminalPayload {
  termination_reason: "normal" | "failed" | "cancelled";
  has_final: boolean;
  final_revision: number | null;
  delivery_status: "complete" | "partial" | "none" | "unknown";
  expected: GenerationSlotReference[];
  delivered: GenerationSlotReference[];
  missing: GenerationSlotReference[];
  review: {
    status: "passed" | "failed" | "skipped" | "unknown";
    content_revision?: number | null;
    unknown_reason?: string;
    reason?: string;
  };
  unknown_reason?: string;
}

export type GenerationOperationStatus = "active" | "ended" | "failed" | "superseded";

export interface GenerationOperationEvidence {
  operationId: string;
  step: string;
  status: GenerationOperationStatus;
  agent: string | null;
  subquestionIndex: number | null;
  supersedesOperationId: string | null;
  callIds: string[];
}

export interface GenerationCallEvidence {
  runId: string;
  callId: string;
  operationId: string;
  purpose: string;
  agent: string;
  status: "active" | "ended" | "failed";
  retryOfCallId: string | null;
  thinking: string;
  content: string;
}

export interface QuestionActivity {
  operations: Record<string, GenerationOperationEvidence>;
  /** Keys are run/call pairs, never an agent or purpose. */
  calls: Record<string, GenerationCallEvidence>;
}

export interface QuestionEvidence {
  questionId: string;
  index: number;
  processing: "waiting" | "running" | "ended" | "unknown";
  content: {
    receipt: "none" | "draft" | "final";
    revision: number | null;
    question: ExamQuestion | null;
    phase: DraftPhase | null;
  };
  terminal: QuestionTerminalPayload | null;
  /** A malformed or contradictory terminal is retained as an uncertainty, not an ending. */
  terminalConflict?: boolean;
  terminalConflictReason?: string;
  /** Review-only disagreement does not invalidate the processing conclusion. */
  reviewConflict?: boolean;
  /**
   * Content version conflict (issue #749): same content_revision but different data, or
   * a manifest/payload identity mismatch, or a seq_data conflict on a content event.
   * Does NOT affect processing status or endedCount — only terminal disputes do that.
   * The already-received body is retained unchanged.
   */
  contentConflict?: boolean;
  contentConflictReason?: string;
  /** terminal says has_final but final_revision not yet received */
  finalPending: boolean;
  /** stream closed while finalPending was true */
  finalMissing: boolean;
  review: {
    status: "passed" | "failed" | "skipped" | "unknown";
    revision: number | null;
    pending?: boolean;
    reason?: string;
  };
  trail: VerificationTrailEntry[];
  figurePolicyTrail: FigurePolicyTrailEntry[];
  referenceExampleRecord: ReferenceExampleRecordShape | undefined;
  /** Present for v2 events; optional for legacy/history fixtures. */
  activity?: QuestionActivity;
}

export interface RunEvidenceState {
  runId: string;
  total: number;
  /** manifest order of question IDs */
  order: string[];
  questions: Record<string, QuestionEvidence>;
  closed: boolean;
  degraded: boolean;
  degradedReason: "timeout" | "count" | "size" | "eof_gap" | null;
  /**
   * True when an unattributable seq conflict stops whole-batch live updates
   * (issue #749).  Individual already-confirmed terminals are NOT erased.
   */
  batchConflict: boolean;
  batchConflictReason: string | null;
  /**
   * True when a raw legacy event was received in v2 mode (issue #749).
   * The decoder stays in v2 mode; unmatched content is incomplete.
   */
  legacyMixed: boolean;
}

// ---------------------------------------------------------------------------
// Constructors
// ---------------------------------------------------------------------------

function emptyQuestionEvidence(questionId: string, index: number): QuestionEvidence {
  return {
    questionId,
    index,
    processing: "waiting",
    content: { receipt: "none", revision: null, question: null, phase: null },
    terminal: null,
    terminalConflict: false,
    terminalConflictReason: undefined,
    reviewConflict: false,
    contentConflict: false,
    contentConflictReason: undefined,
    finalPending: false,
    finalMissing: false,
    review: { status: "unknown", revision: null, pending: false },
    trail: [],
    figurePolicyTrail: [],
    referenceExampleRecord: undefined,
    activity: { operations: {}, calls: {} },
  };
}

export function createRunEvidence(run: RunManifest): RunEvidenceState {
  const order = run.manifest.map((m) => m.questionId);
  const questions: Record<string, QuestionEvidence> = {};
  for (const m of run.manifest) {
    questions[m.questionId] = emptyQuestionEvidence(m.questionId, m.index);
  }
  return {
    runId: run.runId,
    total: run.total,
    order,
    questions,
    closed: false,
    degraded: false,
    degradedReason: null,
    batchConflict: false,
    batchConflictReason: null,
    legacyMixed: false,
  };
}

export function applyDegraded(
  state: RunEvidenceState,
  reason: "timeout" | "count" | "size" | "eof_gap",
): RunEvidenceState {
  if (state.degraded) return state;
  return { ...state, degraded: true, degradedReason: reason };
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

type TerminalRecord = Record<string, unknown>;

function isRecord(value: unknown): value is TerminalRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function positiveRevision(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function slotKey(slot: GenerationSlotReference): string {
  return JSON.stringify([
    slot.kind,
    slot.question_id,
    slot.subquestion_id ?? null,
    slot.subquestion_index ?? null,
  ]);
}

function parseSlotReferences(value: unknown, questionId: string): GenerationSlotReference[] | null {
  if (!Array.isArray(value)) return null;
  const parsed: GenerationSlotReference[] = [];
  for (const item of value) {
    if (!isRecord(item)) return null;
    if (item.kind !== "subquestion" && item.kind !== "image") return null;
    if (typeof item.question_id !== "string" || item.question_id !== questionId) return null;
    if (
      item.subquestion_id !== undefined
      && item.subquestion_id !== null
      && typeof item.subquestion_id !== "string"
    ) return null;
    if (
      item.subquestion_index !== undefined
      && item.subquestion_index !== null
      && (!Number.isInteger(item.subquestion_index) || (item.subquestion_index as number) < 0)
    ) return null;
    if (item.reason !== undefined && typeof item.reason !== "string") return null;
    parsed.push({
      kind: item.kind,
      question_id: item.question_id,
      ...(item.subquestion_id === undefined ? {} : { subquestion_id: item.subquestion_id as string | null }),
      ...(item.subquestion_index === undefined
        ? {}
        : { subquestion_index: item.subquestion_index as number | null }),
      ...(item.reason === undefined ? {} : { reason: item.reason as string }),
    });
  }
  return parsed;
}

function uniqueSlotKeys(slots: GenerationSlotReference[]): Set<string> | null {
  const keys = slots.map(slotKey);
  if (new Set(keys).size !== keys.length) return null;
  return new Set(keys);
}

/** Validate the server terminal invariants before they affect evidence state. */
export function parseQuestionTerminalPayload(
  value: unknown,
  questionId: string,
): QuestionTerminalPayload | null {
  if (!isRecord(value)) return null;
  const terminationReason = value.termination_reason;
  if (terminationReason !== "normal" && terminationReason !== "failed" && terminationReason !== "cancelled") {
    return null;
  }
  if (typeof value.has_final !== "boolean") return null;
  const hasFinal = value.has_final;
  const finalRevision = value.final_revision;
  if (hasFinal ? !positiveRevision(finalRevision) : finalRevision !== null) return null;
  if (terminationReason === "cancelled" && hasFinal) return null;

  const deliveryStatus = value.delivery_status;
  if (deliveryStatus !== "complete" && deliveryStatus !== "partial" && deliveryStatus !== "none" && deliveryStatus !== "unknown") {
    return null;
  }
  if (hasFinal && deliveryStatus === "none") return null;
  if (!hasFinal && deliveryStatus !== "none" && deliveryStatus !== "unknown") return null;
  const unknownReason = value.unknown_reason;
  if (deliveryStatus === "unknown" && (typeof unknownReason !== "string" || unknownReason.length === 0)) {
    return null;
  }
  if (unknownReason !== undefined && unknownReason !== null && typeof unknownReason !== "string") return null;

  const expected = parseSlotReferences(value.expected, questionId);
  const delivered = parseSlotReferences(value.delivered, questionId);
  const missing = parseSlotReferences(value.missing, questionId);
  if (expected === null || delivered === null || missing === null) return null;
  const expectedKeys = uniqueSlotKeys(expected);
  const deliveredKeys = uniqueSlotKeys(delivered);
  const missingKeys = uniqueSlotKeys(missing);
  if (expectedKeys === null || deliveredKeys === null || missingKeys === null) return null;
  if ([...deliveredKeys].some((key) => !expectedKeys.has(key))) return null;
  if ([...missingKeys].some((key) => !expectedKeys.has(key))) return null;
  if ([...deliveredKeys].some((key) => missingKeys.has(key))) return null;
  const covered = new Set([...deliveredKeys, ...missingKeys]);
  if (covered.size !== expectedKeys.size || [...expectedKeys].some((key) => !covered.has(key))) return null;
  if (deliveryStatus === "complete" && missing.length > 0) return null;
  if (deliveryStatus === "partial" && (missing.length === 0 || !hasFinal)) return null;
  if (deliveryStatus === "none" && (delivered.length > 0 || missingKeys.size !== expectedKeys.size)) return null;

  if (!isRecord(value.review)) return null;
  const reviewStatus = value.review.status;
  if (reviewStatus !== "passed" && reviewStatus !== "failed" && reviewStatus !== "skipped" && reviewStatus !== "unknown") {
    return null;
  }
  if (!hasFinal && reviewStatus !== "unknown") return null;
  const reviewRevision = value.review.content_revision;
  if (reviewStatus === "passed" || reviewStatus === "failed" || reviewStatus === "skipped") {
    if (!hasFinal || reviewRevision !== finalRevision) return null;
  } else if (
    hasFinal
    && (typeof value.review.reason !== "string" || value.review.reason.length === 0)
    && (typeof value.review.unknown_reason !== "string" || value.review.unknown_reason.length === 0)
  ) {
    return null;
  }
  if (reviewRevision !== undefined && reviewRevision !== null && !positiveRevision(reviewRevision)) return null;

  return {
    termination_reason: terminationReason,
    has_final: hasFinal,
    final_revision: finalRevision as number | null,
    delivery_status: deliveryStatus,
    expected,
    delivered,
    missing,
    review: {
      status: reviewStatus,
      ...(reviewRevision === undefined ? {} : { content_revision: reviewRevision as number | null }),
      ...(typeof value.review.unknown_reason === "string" ? { unknown_reason: value.review.unknown_reason } : {}),
      ...(typeof value.review.reason === "string" ? { reason: value.review.reason } : {}),
    },
    ...(typeof unknownReason === "string" ? { unknown_reason: unknownReason } : {}),
  };
}

function sameTerminal(left: QuestionTerminalPayload, right: QuestionTerminalPayload): boolean {
  return sameTerminalOutcome(left, right) && JSON.stringify(left.review) === JSON.stringify(right.review);
}

/**
 * Build a string multiset key from a slot array: serialize each SlotRef with
 * sorted object keys, sort the resulting strings, and JSON-stringify the sorted
 * array.  Used for order-independent comparison of expected/delivered/missing
 * slot arrays.
 */
function slotMultisetKey(slots: GenerationSlotReference[]): string {
  return JSON.stringify(
    slots
      .map((s) => JSON.stringify(s, Object.keys(s).sort()))
      .sort(),
  );
}

/**
 * Compare two terminal payloads for "same outcome" — used to detect when only
 * the review block differs (review disagreement ≠ terminal contradiction).
 *
 * expected/delivered/missing arrays are compared as multisets: each SlotRef is
 * canonicalized with sorted object keys and the resulting keys are sorted, so
 * a resend that merely reorders slots is not flagged as terminal_contradiction.
 */
function sameTerminalOutcome(left: QuestionTerminalPayload, right: QuestionTerminalPayload): boolean {
  if (
    left.termination_reason !== right.termination_reason
    || left.has_final !== right.has_final
    || left.final_revision !== right.final_revision
    || left.delivery_status !== right.delivery_status
    || left.unknown_reason !== right.unknown_reason
  ) return false;
  return (
    slotMultisetKey(left.expected) === slotMultisetKey(right.expected)
    && slotMultisetKey(left.delivered) === slotMultisetKey(right.delivered)
    && slotMultisetKey(left.missing) === slotMultisetKey(right.missing)
  );
}

/**
 * Transport/sidecar fields that the publisher adds to a `result` payload at
 * emission time and that are NOT part of the immutable content signature.
 * Confirmed by inspection of all five committed v2 fixtures: `metadata` is
 * null in `question_update` (draft) and populated in `result` (final) for the
 * same content_revision; all other question fields are byte-identical.
 * Excluding these from the fingerprint lets the draft→final promotion pass
 * without a false content conflict.
 */
const CONTENT_SIDECAR_FIELDS = new Set(["metadata"]);

/**
 * A lightweight fingerprint for content-conflict detection (issue #749).
 * Normalises the question object by excluding transport/sidecar fields before
 * serialising.  An empty string on stringify failure ensures a mismatch is
 * never silently treated as identical.
 */
function questionContentFingerprint(q: unknown): string {
  if (q !== null && q !== undefined && typeof q === "object" && !Array.isArray(q)) {
    const normalized: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(q as Record<string, unknown>)) {
      if (!CONTENT_SIDECAR_FIELDS.has(k)) normalized[k] = v;
    }
    try { return JSON.stringify(normalized) ?? ""; } catch { return ""; }
  }
  try {
    return JSON.stringify(q) ?? "";
  } catch {
    return "";
  }
}

/**
 * Handle conflict events emitted by the stream decoder (issue #749).
 * seq_data conflicts are locatable to a question when questionId is present;
 * otherwise they stop whole-batch live (batchConflict).  legacy_in_v2 sets
 * legacyMixed without stopping live or erasing any confirmed terminals.
 */
function applyConflictEvent(
  state: RunEvidenceState,
  ev: Extract<DecodedEvent, { kind: "conflict" }>,
): RunEvidenceState {
  if (ev.conflictType === "legacy_in_v2") {
    if (state.legacyMixed) return state;
    return { ...state, legacyMixed: true };
  }

  if (ev.conflictType === "seq_data") {
    const { eventName, questionId } = ev;

    if (!questionId) {
      // Unattributable — stop whole-batch live; confirmed terminals remain.
      if (state.batchConflict) return state;
      return { ...state, batchConflict: true, batchConflictReason: "seq_data" };
    }

    const qev = state.questions[questionId];
    if (!qev) {
      // questionId not in manifest → treat as unattributable
      if (state.batchConflict) return state;
      return { ...state, batchConflict: true, batchConflictReason: "seq_data" };
    }

    if (eventName === "question_terminal") {
      // Terminal seq conflict → terminalConflict, processing=unknown, excluded from X
      if (qev.terminalConflict) return state;
      return updateQuestion(state, questionId, {
        processing: "unknown",
        terminalConflict: true,
        terminalConflictReason: "seq_data",
        reviewConflict: false,
        finalPending: false,
        review: {
          status: "unknown",
          revision: qev.review.revision,
          pending: false,
          reason: "seq_data",
        },
      });
    }

    if (eventName === "result" || eventName === "question_update") {
      // Content seq conflict → contentConflict; processing and terminal unaffected
      if (qev.contentConflict) return state;
      return updateQuestion(state, questionId, {
        contentConflict: true,
        contentConflictReason: "seq_data",
      });
    }

    // Activity event seq conflict (stage, llm_*, pipeline) → no question-level effect;
    // does not constitute evidence-grade data, so the conclusion stays reliable.
    return state;
  }

  return state;
}

export function applyV2Event(state: RunEvidenceState, decodedEvent: DecodedEvent): RunEvidenceState {
  // Issue #749: handle conflict events before the v2-only gate.
  if (decodedEvent.kind === "conflict") {
    return applyConflictEvent(state, decodedEvent);
  }

  if (decodedEvent.kind !== "v2") return state;
  const { name, context, payload } = decodedEvent.event;

  // When degraded, skip activity-only events; content and terminal still apply.
  if (state.degraded && (
    name === "stage" || name === "pipeline"
    || name === "llm_request" || name === "llm_response"
    || name === "llm_thinking" || name === "llm_content" || name === "llm_failure"
  )) {
    return state;
  }

  const ctx = context as Record<string, unknown>;

  // Done event closes the run
  if (name === "done") {
    return closeRun(state);
  }

  // Question-scoped events
  const questionId = typeof ctx.question_id === "string" ? ctx.question_id : null;
  if (!questionId) return state;

  let qev = state.questions[questionId];
  if (!qev) return state; // unknown question id

  const p = payload as Record<string, unknown>;

  if (
    qev.terminalConflict
    && name !== "question_terminal"
  ) {
    return state;
  }

  if (
    qev.terminal !== null
    && (name === "pipeline" || name === "stage" || name === "llm_request"
      || name === "llm_response" || name === "llm_thinking" || name === "llm_content"
      || name === "llm_failure")
  ) {
    return state;
  }

  const activity = applyActivity(
    qev.activity ?? { operations: {}, calls: {} },
    name,
    ctx,
    p,
    state.runId,
  );
  if (activity !== qev.activity) {
    state = updateQuestion(state, questionId, { activity });
    qev = state.questions[questionId];
  }

  switch (name) {
    case "pipeline": {
      const eventName = p.event_name as string | undefined;
      if (eventName === "question_start" && qev.processing !== "ended") {
        return updateQuestion(state, questionId, { processing: "running" });
      }
      return state;
    }

    case "stage":
    case "llm_request":
    case "llm_response":
    case "llm_thinking":
    case "llm_content": {
      // These signal running if not ended
      if (qev.processing !== "ended") {
        return updateQuestion(state, questionId, { processing: "running" });
      }
      return state;
    }

    case "llm_failure": {
      if (qev.processing !== "ended") {
        return updateQuestion(state, questionId, { processing: "running" });
      }
      return state;
    }

    case "question_update": {
      if (qev.terminalConflict) return state;
      const contentRevision = typeof ctx.content_revision === "number" ? ctx.content_revision : null;
      if (contentRevision === null) return state;
      if (qev.terminal !== null) {
        if (!qev.terminal.has_final || qev.terminal.final_revision === null) return state;
        if (contentRevision > qev.terminal.final_revision) return state;
      }
      // Ignore older revisions
      if (qev.content.revision !== null && contentRevision < qev.content.revision) return state;

      // Issue #749: manifest/payload identity mismatch — question object id must match context.
      const questionObj = p.question as Record<string, unknown> | null | undefined;
      if (
        questionObj !== null
        && questionObj !== undefined
        && typeof questionObj.id === "string"
        && questionObj.id !== questionId
      ) {
        if (qev.contentConflict) return state;
        return updateQuestion(state, questionId, {
          contentConflict: true,
          contentConflictReason: "identity_mismatch",
        });
      }

      // Issue #749: same-revision-different-content — only flag when an already-stored
      // DRAFT arrives again at the same revision with different content.  A `result` event
      // at the same revision as a prior `question_update` draft is intentional finalisation,
      // not a conflict; we must not compare the two.
      if (qev.content.receipt === "draft" && qev.content.revision === contentRevision && qev.content.question !== null) {
        const storedFp = questionContentFingerprint(qev.content.question);
        const newFp = questionContentFingerprint(questionObj);
        if (storedFp !== newFp) {
          if (qev.contentConflict) return state;
          return updateQuestion(state, questionId, {
            contentConflict: true,
            contentConflictReason: "same_revision_different_content",
          });
        }
        // Same draft revision, same content → idempotent resend, no state change needed
        return state;
      }

      // Only update if this is not a final receipt, or if revision is higher
      if (qev.content.receipt === "final" && qev.content.revision !== null && contentRevision <= qev.content.revision) {
        return state;
      }
      const question = p.question as ExamQuestion | null | undefined;
      const phase = p.phase as DraftPhase | null | undefined;
      const content = {
        receipt: qev.content.receipt === "final" ? "final" : "draft",
        revision: contentRevision,
        question: question ?? qev.content.question,
        phase: phase ?? qev.content.phase,
      } as QuestionEvidence["content"];
      const nextQuestion = { ...qev, content };
      return updateQuestion(state, questionId, {
        content,
        review: qev.terminal ? reviewForContent(nextQuestion) : qev.review,
      });
    }

    case "result": {
      if (qev.terminalConflict) return state;
      const contentRevision = typeof ctx.content_revision === "number" ? ctx.content_revision : null;
      if (contentRevision === null) return state;
      if (qev.terminal !== null) {
        if (!qev.terminal.has_final || qev.terminal.final_revision !== contentRevision) return state;
      }
      // Ignore lower revisions than any already-received content.
      if (qev.content.revision !== null && contentRevision < qev.content.revision) {
        return state;
      }

      // Issue #749: manifest/payload identity mismatch — result payload id must match context.
      const resultPayload = payload as Record<string, unknown>;
      if (typeof resultPayload.id === "string" && resultPayload.id !== questionId) {
        if (qev.contentConflict) return state;
        return updateQuestion(state, questionId, {
          contentConflict: true,
          contentConflictReason: "identity_mismatch",
        });
      }

      if (qev.content.receipt === "final" && qev.content.revision !== null && contentRevision <= qev.content.revision) {
        // Issue #749: same-revision-different-content — two `result` events for the same
        // final revision with different data is a conflict.  A result at a lower revision
        // than the stored final is silently ignored (older, not a conflict).
        if (contentRevision === qev.content.revision && qev.content.question !== null) {
          const storedFp = questionContentFingerprint(qev.content.question);
          const newFp = questionContentFingerprint(payload);
          if (storedFp !== newFp) {
            if (qev.contentConflict) return state;
            return updateQuestion(state, questionId, {
              contentConflict: true,
              contentConflictReason: "same_revision_different_content",
            });
          }
        }
        return state;
      }

      // Issue #749 (Gap 1): same-revision draft→final content conflict.
      // Per snapshot-ledger contract (tasks 3.1/3.3), a revision's content is immutable.
      // A `result` at the same content_revision as a stored draft may only promote
      // identical (normalised) content.  `metadata` is a sidecar field added by the
      // publisher at result-time and is legitimately absent from the draft; exclude it
      // before comparing so real fixtures (social/NS) do not produce false conflicts.
      if (
        qev.content.receipt === "draft"
        && qev.content.revision === contentRevision
        && qev.content.question !== null
      ) {
        const storedFp = questionContentFingerprint(qev.content.question);
        const newFp = questionContentFingerprint(payload);
        if (storedFp !== newFp) {
          if (qev.contentConflict) return state;
          return updateQuestion(state, questionId, {
            contentConflict: true,
            contentConflictReason: "same_revision_different_content",
          });
        }
        // Same normalised content: intentional finalisation — fall through to adopt as final.
      }

      const question = payload as ExamQuestion;
      // Clear finalPending if this matches the expected final_revision
      const newFinalPending = qev.finalPending && qev.terminal !== null
        ? qev.terminal.final_revision !== contentRevision
        : false;
      const content = { receipt: "final" as const, revision: contentRevision, question, phase: "verified" as const };
      const nextQuestion = { ...qev, content };
      return updateQuestion(state, questionId, {
        content,
        finalPending: newFinalPending,
        review: qev.terminal ? reviewForContent(nextQuestion) : qev.review,
      });
    }

    case "question_terminal": {
      const terminal = parseQuestionTerminalPayload(payload, questionId);
      if (terminal === null) {
        return updateQuestion(state, questionId, {
          processing: "unknown",
          terminalConflict: true,
          terminalConflictReason: "terminal_invalid",
          reviewConflict: false,
          finalPending: false,
          review: { status: "unknown", revision: qev.review.revision, pending: false, reason: "terminal_invalid" },
        });
      }
      if (qev.terminalConflict) return state;
      if (qev.terminal !== null) {
        if (sameTerminal(qev.terminal, terminal)) return state;
        if (sameTerminalOutcome(qev.terminal, terminal)) {
          return updateQuestion(state, questionId, {
            reviewConflict: true,
            review: {
              status: "unknown",
              revision: qev.review.revision,
              pending: false,
              reason: "review_contradiction",
            },
          });
        }
        return updateQuestion(state, questionId, {
          processing: "unknown",
          terminalConflict: true,
          terminalConflictReason: "terminal_contradiction",
          reviewConflict: false,
          finalPending: false,
          review: { status: "unknown", revision: qev.review.revision, pending: false, reason: "terminal_contradiction" },
        });
      }
      if (
        (terminal.has_final
          && qev.content.receipt === "final"
          && qev.content.revision !== terminal.final_revision)
        || (!terminal.has_final && qev.content.receipt === "final")
        || (terminal.has_final
          && qev.content.revision !== null
          && qev.content.revision > (terminal.final_revision ?? 0))
      ) {
        return updateQuestion(state, questionId, {
          processing: "unknown",
          terminalConflict: true,
          terminalConflictReason: "terminal_contradiction",
          reviewConflict: false,
          finalPending: false,
          review: { status: "unknown", revision: qev.review.revision, pending: false, reason: "terminal_contradiction" },
        });
      }
      // finalPending: terminal says has_final but we haven't received the final_revision yet
      const finalPending = terminal.has_final &&
        terminal.final_revision !== null &&
        !(qev.content.receipt === "final" && qev.content.revision === terminal.final_revision);
      const nextQuestion = { ...qev, terminal, finalPending };
      return updateQuestion(state, questionId, {
        processing: "ended",
        terminal,
        terminalConflict: false,
        terminalConflictReason: undefined,
        reviewConflict: false,
        review: reviewForContent(nextQuestion),
        finalPending,
      });
    }

    default:
      return state;
  }
}

function activityRunId(context: Record<string, unknown>, fallback: string): string {
  return typeof context.run_id === "string" && context.run_id
    ? context.run_id
    : fallback;
}

function activityStep(payload: Record<string, unknown>): string {
  const stage = typeof payload.stage === "string" ? payload.stage : "";
  const agent = typeof payload.agent === "string" ? payload.agent : "";
  if (agent.startsWith("sub_generator#")) return "subquestions";
  if (agent === "image_agent" || stage.includes("image")) return "image";
  if (agent === "verifier" || stage === "verify") return "verify";
  if (agent === "corrector" || stage === "correct") return "correct";
  if (agent === "planner" || stage === "batch_briefs") return "planner";
  if (stage === "llm_generate" || agent === "generator") return "text";
  return stage || agent || "unknown";
}

function applyActivity(
  previous: QuestionActivity,
  eventName: string,
  context: Record<string, unknown>,
  payload: Record<string, unknown>,
  fallbackRunId: string,
): QuestionActivity {
  const operationId = typeof context.operation_id === "string" ? context.operation_id : null;
  const callId = typeof context.call_id === "string" ? context.call_id : null;
  if (!operationId && !callId) return previous;

  const runId = activityRunId(context, fallbackRunId);
  const operations = { ...previous.operations };
  const calls = { ...previous.calls };
  const effectiveOperationId = operationId ?? (callId ? `${runId}/call/${callId}` : "");
  const existingOperation = operations[effectiveOperationId];
  const operation: GenerationOperationEvidence = existingOperation ?? {
    operationId: effectiveOperationId,
    step: activityStep(payload),
    status: "active",
    agent: typeof payload.agent === "string" ? payload.agent : null,
    subquestionIndex: typeof context.subquestion_index === "number"
      ? context.subquestion_index
      : null,
    supersedesOperationId: null,
    callIds: [],
  };
  const updatedOperation: GenerationOperationEvidence = {
    ...operation,
    step: operation.step === "unknown" ? activityStep(payload) : operation.step,
    agent: operation.agent ?? (typeof payload.agent === "string" ? payload.agent : null),
    subquestionIndex: operation.subquestionIndex ?? (
      typeof context.subquestion_index === "number" ? context.subquestion_index : null
    ),
    callIds: [...operation.callIds],
  };

  if (eventName === "stage") {
    const status = payload.status;
    if (status === "start") {
      updatedOperation.status = "active";
      if (typeof payload.supersedes_operation_id === "string") {
        updatedOperation.supersedesOperationId = payload.supersedes_operation_id;
        const superseded = operations[payload.supersedes_operation_id];
        if (superseded) {
          operations[payload.supersedes_operation_id] = { ...superseded, status: "superseded" };
        }
      }
    } else if (status === "error") {
      if (updatedOperation.status !== "superseded") updatedOperation.status = "failed";
    } else if (updatedOperation.status !== "superseded") {
      updatedOperation.status = "ended";
    }
  }
  operations[effectiveOperationId] = updatedOperation;

  if (callId && operationId) {
    const callKey = `${runId}/${callId}`;
    const existingCall = calls[callKey];
    const call: GenerationCallEvidence = existingCall ?? {
      runId,
      callId,
      operationId,
      purpose: typeof payload.purpose === "string" ? payload.purpose : "",
      agent: typeof payload.agent === "string" ? payload.agent : "",
      status: "active",
      retryOfCallId: typeof payload.retry_of_call_id === "string"
        ? payload.retry_of_call_id
        : null,
      thinking: "",
      content: "",
    };
    const updatedCall: GenerationCallEvidence = {
      ...call,
      purpose: call.purpose || (typeof payload.purpose === "string" ? payload.purpose : ""),
      agent: call.agent || (typeof payload.agent === "string" ? payload.agent : ""),
      retryOfCallId: call.retryOfCallId ?? (
        typeof payload.retry_of_call_id === "string" ? payload.retry_of_call_id : null
      ),
    };
    if (!updatedOperation.callIds.includes(callId)) {
      updatedOperation.callIds = [...updatedOperation.callIds, callId];
      operations[effectiveOperationId] = updatedOperation;
    }
    if (eventName === "llm_thinking") updatedCall.thinking += typeof payload.text === "string" ? payload.text : "";
    if (eventName === "llm_content") updatedCall.content += typeof payload.text === "string" ? payload.text : "";
    if (eventName === "llm_response") updatedCall.status = "ended";
    if (eventName === "llm_failure") updatedCall.status = "failed";
    calls[callKey] = updatedCall;
  }

  return { operations, calls };
}

function updateQuestion(
  state: RunEvidenceState,
  questionId: string,
  updates: Partial<QuestionEvidence>,
): RunEvidenceState {
  return {
    ...state,
    questions: {
      ...state.questions,
      [questionId]: { ...state.questions[questionId], ...updates },
    },
  };
}

function reviewForContent(qev: QuestionEvidence): QuestionEvidence["review"] {
  if (qev.reviewConflict) return qev.review;
  const terminal = qev.terminal;
  if (terminal === null) return qev.review;
  const review = terminal.review ?? {};
  const reviewStatus = (review.status ?? "unknown") as QuestionEvidence["review"]["status"];
  const reviewRevision = typeof review.content_revision === "number" ? review.content_revision : null;
  const definitive = reviewStatus === "passed" || reviewStatus === "failed" || reviewStatus === "skipped";
  const matchesFinal = terminal.has_final
    && terminal.final_revision !== null
    && qev.content.receipt === "final"
    && qev.content.revision === terminal.final_revision
    && reviewRevision === terminal.final_revision;
  if (definitive && !matchesFinal) {
    return {
      status: "unknown",
      revision: reviewRevision,
      pending: true,
      reason: "waiting for matching final content",
    };
  }
  return {
    status: reviewStatus,
    revision: reviewRevision,
    pending: false,
    reason: typeof review.reason === "string"
      ? review.reason
      : typeof review.unknown_reason === "string" ? review.unknown_reason : undefined,
  };
}

export function closeRun(state: RunEvidenceState): RunEvidenceState {
  /**
   * Stream loss: the live SSE connection ended. Retain established terminal
   * facts; keep unresolved questions at their current persisted processing
   * state (the snapshot poller takes over). Do NOT mark questions unknown
   * merely because the stream ended — "unknown" is reserved for when
   * persisted state itself is unreadable (see applyPollReadFailed).
   *
   * terminalConflict stays unresolved — a conflict is a data error, not a
   * stream-loss artifact.  finalPending upgrades to finalMissing when the
   * live stream closed before delivering the expected final content.
   */
  const questions: Record<string, QuestionEvidence> = {};
  for (const [qid, qev] of Object.entries(state.questions)) {
    const hadFinalPending = qev.finalPending;
    questions[qid] = {
      ...qev,
      // Do not change processing; persisted-state polling drives it now.
      finalPending: false,
      finalMissing: hadFinalPending,
      review: hadFinalPending
        ? {
          status: "unknown",
          revision: qev.review.revision,
          pending: false,
          reason: "final content missing",
        }
        : qev.review,
    };
  }
  return { ...state, questions, closed: true };
}

/**
 * Mark every question WITHOUT an established termination reason as "unknown"
 * when persisted state becomes temporarily unreadable (≥3 consecutive poll
 * failures, per the pollReadFailCount threshold in useGenerate).
 *
 * Already-confirmed terminals and their processing states are preserved.
 * The unknown state is replaced by persisted truth when the next successful
 * snapshot is applied through applyRunSnapshot / applyQuestion.
 */
export function applyPollReadFailed(state: RunEvidenceState): RunEvidenceState {
  const questions: Record<string, QuestionEvidence> = {};
  let changed = false;
  for (const [qid, qev] of Object.entries(state.questions)) {
    const shouldMarkUnknown =
      qev.terminal === null && !qev.terminalConflict && qev.processing !== "unknown";
    if (shouldMarkUnknown) {
      changed = true;
      questions[qid] = { ...qev, processing: "unknown" };
    } else {
      questions[qid] = qev;
    }
  }
  return changed ? { ...state, questions } : state;
}

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

/** Number of unique questions that have received a question_terminal event. */
export function selectEndedCount(state: RunEvidenceState): number {
  return Object.values(state.questions).filter((q) => q.terminal !== null && !q.terminalConflict).length;
}

/**
 * Number of unique questions with any active conflict flag
 * (terminalConflict, contentConflict, or reviewConflict).  Issue #749.
 */
export function selectConflictCount(state: RunEvidenceState): number {
  return Object.values(state.questions).filter(
    (q) => q.terminalConflict || q.contentConflict || q.reviewConflict,
  ).length;
}

/** Number of unique questions whose content.receipt === 'final'. */
export function selectFinalReceivedCount(state: RunEvidenceState): number {
  return Object.values(state.questions).filter((q) => q.content.receipt === "final").length;
}

/** Operations whose own lifecycle is still active for one question. */
export function selectActiveOperations(question: QuestionEvidence): GenerationOperationEvidence[] {
  return Object.values(question.activity?.operations ?? {}).filter(
    (operation) => operation.status === "active",
  );
}

/** Aggregate operation activity by the actual generation step, not agent name. */
export function selectGenerationSteps(
  question: QuestionEvidence,
): Array<{ step: string; active: number; total: number }> {
  const byStep = new Map<string, { step: string; active: number; total: number }>();
  for (const operation of Object.values(question.activity?.operations ?? {})) {
    const current = byStep.get(operation.step) ?? { step: operation.step, active: 0, total: 0 };
    current.total += 1;
    if (operation.status === "active") current.active += 1;
    byStep.set(operation.step, current);
  }
  return [...byStep.values()];
}
