import type {
  DraftPhase,
  FigurePolicyTrailEntry,
  GeneratedQuestion,
  LlmCallEvent,
  ReferenceExampleRecordShape,
  VerificationTrailEntry,
} from "../hooks/useGenerate";
import type { GenerationLegacyEvidence, GenerationV2Evidence } from "./runEvidence";
import type { RunEvidenceState } from "./generationEvidence";
import { selectEndedCount, selectFinalReceivedCount, selectConflictCount } from "./generationEvidence";

export function projectGenerationEvidence(
  llmCalls: readonly LlmCallEvent[],
  subQuestionCount: number | null,
  v2Evidence?: RunEvidenceState | null,
): GenerationLegacyEvidence | GenerationV2Evidence {
  if (v2Evidence) {
    return {
      profile: "generate-v2",
      total: v2Evidence.total,
      endedCount: selectEndedCount(v2Evidence),
      finalReceivedCount: selectFinalReceivedCount(v2Evidence),
      closed: v2Evidence.closed,
      degraded: v2Evidence.degraded,
      conflictCount: selectConflictCount(v2Evidence),
      batchConflict: v2Evidence.batchConflict,
      legacyMixed: v2Evidence.legacyMixed,
    };
  }
  return {
    profile: "generate-legacy",
    stageEvents: llmCalls.filter((event) => event.type === "stage"),
    subQuestionCount,
  };
}

export type GenerationCardEvidence = {
  phase: DraftPhase;
  isFinal: boolean;
  trail: VerificationTrailEntry[];
  figurePolicyTrail: FigurePolicyTrailEntry[];
  referenceExampleRecord: ReferenceExampleRecordShape | undefined;
};

export function projectGenerationCardEvidence(item: GeneratedQuestion): GenerationCardEvidence {
  return {
    phase: item.phase,
    isFinal: item.isFinal,
    trail: item.trail ?? [],
    figurePolicyTrail: item.figurePolicyTrail ?? [],
    referenceExampleRecord: item.referenceExampleRecord,
  };
}

// ---------------------------------------------------------------------------
// F1: Generation stream decoder — protocol v2 / legacy / unsupported
// ---------------------------------------------------------------------------

export type DecoderMode = "awaiting-start" | "v2" | "legacy" | "unsupported";

/** The run manifest produced by a valid v2 started event. */
export interface RunManifest {
  runId: string;
  total: number;
  manifest: Array<{ index: number; questionId: string }>;
}

export interface DecoderClock {
  now(): number;
}

/** A decoded event from the stream. */
export type DecodedEvent =
  | { kind: "v2"; event: { name: string; context: Record<string, unknown>; payload: unknown } }
  | { kind: "legacy"; name: string; data: string }
  | { kind: "mode"; mode: "unsupported"; reason: "unknown_protocol" | "invalid_manifest" | "missing_started" }
  | { kind: "ignore"; reason: string }
  | { kind: "held" }
  | { kind: "degraded"; reason: "timeout" | "count" | "size" | "eof_gap" }
  /**
   * Conflict events (issue #749): isolate the problem to the smallest scope.
   * seq_data:      same event_seq with different raw data — fingerprint mismatch.
   *   questionId: string  → locatable to that question; only that question is affected.
   *   questionId: null    → unattributable; whole-batch live stops (batchConflict).
   * legacy_in_v2:  an event without a v2 context envelope arrived while in v2 mode.
   *   The decoder stays in v2 mode; unmatched content is marked incomplete (legacyMixed).
   */
  | { kind: "conflict"; conflictType: "seq_data"; seq: number; eventName: string; questionId: string | null }
  | { kind: "conflict"; conflictType: "legacy_in_v2" };

/** Stateful decoder for a single generate() call's SSE stream. */
export interface GenerationStreamDecoder {
  readonly mode: DecoderMode;
  readonly run: RunManifest | null;
  readonly degraded: boolean;
  /** Decode one SSE event. Returns an array (usually length 1; >1 when held events are replayed). */
  decode(eventName: string, rawData: string): DecodedEvent[];
  /**
   * Timer-driven deadline check: call when the gap timer fires without further
   * events arriving.  Returns a degraded event (+ flushed content/terminal
   * events) if the 2 s bound has now elapsed; returns [] if the gap filled or
   * degradation already happened.
   */
  checkDeadline(): DecodedEvent[];
  /**
   * Remaining milliseconds until the gap deadline, or null if no gap is open
   * (or the decoder is not in v2 mode, or already degraded).
   * Used by useGenerate to re-arm the gap timer after a non-degrading checkDeadline().
   */
  msUntilDeadline(): number | null;
}

const SEQ_BUFFER_MAX_COUNT = 256;
const SEQ_BUFFER_MAX_BYTES = 4 * 1024 * 1024;
export const SEQ_BUFFER_MAX_AGE_MS = 2000;

/** Reused across all decoder instances for accurate UTF-8 byte measurement. */
const utf8Encoder = new TextEncoder();

function validateManifest(payload: Record<string, unknown>): { valid: boolean; reason?: string } {
  const total = payload.total;
  const questions = payload.questions;
  if (typeof total !== "number" || !Number.isInteger(total) || total < 1) {
    return { valid: false, reason: "invalid_manifest" };
  }
  if (!Array.isArray(questions) || questions.length !== total) {
    return { valid: false, reason: "invalid_manifest" };
  }
  const ids = new Set<string>();
  for (let i = 0; i < questions.length; i++) {
    const q = questions[i] as Record<string, unknown>;
    if (q.index !== i) return { valid: false, reason: "invalid_manifest" };
    const qid = q.question_id;
    if (typeof qid !== "string" || qid === "") return { valid: false, reason: "invalid_manifest" };
    if (ids.has(qid)) return { valid: false, reason: "invalid_manifest" };
    ids.add(qid);
  }
  return { valid: true };
}

export function createGenerationStreamDecoder(options?: { clock?: DecoderClock }): GenerationStreamDecoder {
  let mode: DecoderMode = "awaiting-start";
  let run: RunManifest | null = null;
  const held: Array<{ name: string; rawData: string }> = [];
  const clock: DecoderClock = options?.clock ?? { now: () => Date.now() };
  let seqNextExpected = 0;
  let seqSeen = new Set<number>();
  /**
   * Fingerprint map for conflict detection (issue #749): maps event_seq →
   * raw data string of the first-processed event at that seq.  When a seq
   * arrives again, the stored fingerprint is compared; a mismatch means the
   * same sequence number carried different data, which is a seq_data conflict.
   * Storing the full rawData string is intentional: events are compact JSON
   * and the map grows linearly with the stream, matching seqSeen's own growth.
   */
  let seqFingerprints = new Map<number, string>();
  let seqPending = new Map<number, { eventName: string; rawData: string; byteSize: number }>();
  let seqPendingBytes = 0;
  let seqGapStart: number | null = null;
  let seqDegraded = false;

  /** Record a processed seq → fingerprint pair. */
  function recordSeq(seq: number, rawData: string) {
    seqSeen.add(seq);
    seqFingerprints.set(seq, rawData);
  }

  function decodeAsV2(eventName: string, rawData: string): DecodedEvent {
    if (run === null) return { kind: "ignore", reason: "no_run" };
    let parsed: unknown;
    try {
      parsed = JSON.parse(rawData);
    } catch {
      return { kind: "ignore", reason: "invalid_json" };
    }
    if (parsed === null || typeof parsed !== "object") {
      return { kind: "ignore", reason: "invalid_envelope" };
    }
    const envelope = parsed as Record<string, unknown>;
    // Issue #749: detect raw legacy events (no context key at all) vs. malformed v2.
    if (!("context" in envelope)) {
      return { kind: "conflict", conflictType: "legacy_in_v2" };
    }
    const ctx = envelope.context;
    if (ctx === null || typeof ctx !== "object") {
      return { kind: "ignore", reason: "invalid_envelope" };
    }
    const context = ctx as Record<string, unknown>;
    if (context.run_id !== run.runId) {
      return { kind: "ignore", reason: "wrong_run" };
    }
    if (typeof context.event_seq !== "number" || !Number.isInteger(context.event_seq)) {
      return { kind: "ignore", reason: "invalid_envelope" };
    }
    return { kind: "v2", event: { name: eventName, context, payload: envelope.payload } };
  }

  /**
   * Degrade the buffer, releasing any content/terminal events that were
   * pending.  Activity-only events (stage, pipeline, llm_*) are dropped.
   * Must only be called when !seqDegraded.
   */
  function degrade(reason: "timeout" | "count" | "size" | "eof_gap"): DecodedEvent[] {
    seqDegraded = true;
    const released: DecodedEvent[] = [];
    const sortedSeqs = [...seqPending.keys()].sort((a, b) => a - b);
    for (const pendingSeq of sortedSeqs) {
      const entry = seqPending.get(pendingSeq)!;
      if (
        entry.eventName === "question_update" ||
        entry.eventName === "result" ||
        entry.eventName === "question_terminal"
      ) {
        const ev = decodeAsV2(entry.eventName, entry.rawData);
        if (ev.kind === "v2") {
          recordSeq(pendingSeq, entry.rawData);
          released.push(ev);
        }
      }
    }
    seqPending.clear();
    seqPendingBytes = 0;
    return [{ kind: "degraded", reason }, ...released];
  }

  /**
   * Build a seq_data conflict event from a duplicate seq that has different data.
   * The questionId is extracted from the NEW event's decoded context (already parsed
   * by decodeAsV2 via the `decoded` arg).
   */
  function seqDataConflict(
    decoded: Extract<DecodedEvent, { kind: "v2" }>,
    seq: number,
    evName: string,
  ): DecodedEvent {
    const questionId = typeof decoded.event.context.question_id === "string"
      ? decoded.event.context.question_id
      : null;
    return { kind: "conflict", conflictType: "seq_data", seq, eventName: evName, questionId };
  }

  function decodeV2WithSeq(eventName: string, rawData: string): DecodedEvent[] {
    const decoded = decodeAsV2(eventName, rawData);
    // Pass through non-v2 results (ignore, conflict, etc.) without seq processing.
    if (decoded.kind !== "v2") return [decoded];

    const eventSeq = decoded.event.context.event_seq as number;

    if (seqSeen.has(eventSeq)) {
      // Issue #749: fingerprint check — same data = idempotent, different data = conflict.
      const stored = seqFingerprints.get(eventSeq);
      if (stored === rawData || stored === undefined) {
        return [{ kind: "ignore", reason: "duplicate_seq" }];
      }
      return [seqDataConflict(decoded, eventSeq, eventName)];
    }

    if (seqDegraded) {
      if (eventName === "question_update" || eventName === "result" || eventName === "question_terminal") {
        recordSeq(eventSeq, rawData);
        return [decoded];
      }
      return [{ kind: "ignore", reason: "degraded" }];
    }

    if (eventSeq === seqNextExpected) {
      if (eventName === "done" && seqPending.size > 0) {
        const degradeResult = degrade("eof_gap");
        recordSeq(eventSeq, rawData);
        seqNextExpected += 1;
        return [...degradeResult, decoded];
      }

      recordSeq(eventSeq, rawData);
      seqNextExpected += 1;
      const results: DecodedEvent[] = [decoded];
      while (seqPending.has(seqNextExpected)) {
        const pendingSeq = seqNextExpected;
        const entry = seqPending.get(pendingSeq)!;
        seqPending.delete(pendingSeq);
        seqPendingBytes -= entry.byteSize;
        recordSeq(pendingSeq, entry.rawData);
        seqNextExpected += 1;
        results.push(decodeAsV2(entry.eventName, entry.rawData));
      }
      if (seqPending.size === 0) seqGapStart = null;
      return results;
    }

    if (eventSeq < seqNextExpected) {
      recordSeq(eventSeq, rawData);
      return [decoded];
    }

    if (seqPending.has(eventSeq)) {
      return [{ kind: "ignore", reason: "duplicate_seq" }];
    }

    // A valid done event is an EOF boundary even when its own sequence is
    // ahead of the missing gap. Keep the decoded done event usable while
    // making the unresolved ordering explicit.
    if (eventName === "done" && seqPending.size > 0) {
      const degradeResult = degrade("eof_gap");
      seqSeen.add(eventSeq);
      return [...degradeResult, decoded];
    }

    const byteSize = utf8Encoder.encode(rawData).length;
    seqPending.set(eventSeq, { eventName, rawData, byteSize });
    seqPendingBytes += byteSize;

    if (seqGapStart === null) seqGapStart = clock.now();
    const now = clock.now();
    if (now - seqGapStart >= SEQ_BUFFER_MAX_AGE_MS) {
      return degrade("timeout");
    }
    if (seqPending.size >= SEQ_BUFFER_MAX_COUNT) {
      return degrade("count");
    }
    if (seqPendingBytes >= SEQ_BUFFER_MAX_BYTES) {
      return degrade("size");
    }
    return [{ kind: "held" }];
  }

  function processStarted(rawData: string): DecodedEvent[] {
    let parsed: unknown = null;
    if (rawData) {
      try { parsed = JSON.parse(rawData); } catch { parsed = null; }
    }

    if (parsed !== null && typeof parsed === "object") {
      const envelope = parsed as Record<string, unknown>;
      if ("context" in envelope && envelope.context !== null && typeof envelope.context === "object") {
        // V2 envelope shape: {context, payload}
        const ctx = envelope.context as Record<string, unknown>;
        const payload = envelope.payload;
        if (payload === null || typeof payload !== "object") {
          mode = "unsupported";
          return [{ kind: "mode", mode: "unsupported", reason: "invalid_manifest" }];
        }
        const p = payload as Record<string, unknown>;
        if (p.protocol_version !== 2) {
          mode = "unsupported";
          return [{ kind: "mode", mode: "unsupported", reason: "unknown_protocol" }];
        }
        const validation = validateManifest(p);
        if (!validation.valid) {
          mode = "unsupported";
          return [{ kind: "mode", mode: "unsupported", reason: "invalid_manifest" }];
        }
        // Valid v2
        const questions = p.questions as Array<{ index: number; question_id: string }>;
        run = {
          runId: ctx.run_id as string,
          total: p.total as number,
          manifest: questions.map((q) => ({ index: q.index, questionId: q.question_id })),
        };
        mode = "v2";
        seqNextExpected = 2;
        seqSeen = new Set([1]);
        seqFingerprints = new Map([[1, rawData]]); // fingerprint the started event (seq 1)
        seqPending = new Map();
        seqPendingBytes = 0;
        seqGapStart = null;
        seqDegraded = false;
        const startedEvent: DecodedEvent = {
          kind: "v2",
          event: { name: "started", context: ctx, payload: p },
        };
        // Replay held events through the now-v2 decoder
        const toReplay = held.splice(0);
        const replayed = toReplay.flatMap((h) => decodeV2WithSeq(h.name, h.rawData));
        return [startedEvent, ...replayed];
      }
      // No context key → legacy (includes {generation_log_id:...} and {})
      mode = "legacy";
      return [{ kind: "legacy", name: "started", data: rawData }];
    }

    // Empty/non-object → legacy
    mode = "legacy";
    return [{ kind: "legacy", name: "started", data: rawData }];
  }

  return {
    get mode() { return mode; },
    get run() { return run; },
    get degraded() { return seqDegraded; },

    checkDeadline(): DecodedEvent[] {
      if (mode !== "v2" || seqDegraded || seqGapStart === null) return [];
      const now = clock.now();
      if (now - seqGapStart >= SEQ_BUFFER_MAX_AGE_MS) {
        return degrade("timeout");
      }
      return [];
    },

    msUntilDeadline(): number | null {
      if (mode !== "v2" || seqDegraded || seqGapStart === null) return null;
      const elapsed = clock.now() - seqGapStart;
      const remaining = SEQ_BUFFER_MAX_AGE_MS - elapsed;
      return remaining > 0 ? remaining : 0;
    },

    decode(eventName: string, rawData: string): DecodedEvent[] {
      if (mode === "unsupported") {
        return [{ kind: "ignore", reason: "unsupported" }];
      }
      if (mode === "v2") {
        return decodeV2WithSeq(eventName, rawData);
      }
      if (mode === "legacy") {
        return [{ kind: "legacy", name: eventName, data: rawData }];
      }
      // awaiting-start
      if (eventName === "started") {
        return processStarted(rawData);
      }
      if (eventName === "done" || eventName === "error") {
        // If the event data has a v2 context envelope, we know this is a v2
        // stream that lost its started event → unsupported missing_started.
        // If the data is legacy/empty (no context key), fall through to legacy.
        let hasV2Context = false;
        if (rawData) {
          try {
            const p = JSON.parse(rawData) as unknown;
            if (p !== null && typeof p === "object" && "context" in (p as object)) {
              hasV2Context = true;
            }
          } catch { /* ignore */ }
        }
        if (hasV2Context) {
          mode = "unsupported";
          return [{ kind: "mode", mode: "unsupported", reason: "missing_started" }];
        }
        // Legacy-format done/error (no context) → transition to legacy
        mode = "legacy";
        return [{ kind: "legacy", name: eventName, data: rawData }];
      }
      // Hold non-started events
      held.push({ name: eventName, rawData });
      return [{ kind: "held" }];
    },
  };
}
