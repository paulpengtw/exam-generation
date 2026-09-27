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
import { selectEndedCount, selectFinalReceivedCount } from "./generationEvidence";

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
  | { kind: "degraded"; reason: "timeout" | "count" | "size" | "eof_gap" };

/** Stateful decoder for a single generate() call's SSE stream. */
export interface GenerationStreamDecoder {
  readonly mode: DecoderMode;
  readonly run: RunManifest | null;
  readonly degraded: boolean;
  /** Decode one SSE event. Returns an array (usually length 1; >1 when held events are replayed). */
  decode(eventName: string, rawData: string): DecodedEvent[];
}

const SEQ_BUFFER_MAX_COUNT = 256;
const SEQ_BUFFER_MAX_BYTES = 4 * 1024 * 1024;
const SEQ_BUFFER_MAX_AGE_MS = 2000;

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
  let seqPending = new Map<number, { eventName: string; rawData: string; byteSize: number }>();
  let seqPendingBytes = 0;
  let seqGapStart: number | null = null;
  let seqDegraded = false;

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

  function decodeV2WithSeq(eventName: string, rawData: string): DecodedEvent[] {
    const decoded = decodeAsV2(eventName, rawData);
    if (decoded.kind !== "v2") return [decoded];

    const eventSeq = decoded.event.context.event_seq as number;

    if (seqSeen.has(eventSeq)) {
      return [{ kind: "ignore", reason: "duplicate_seq" }];
    }

    if (seqDegraded) {
      if (eventName === "question_update" || eventName === "result" || eventName === "question_terminal") {
        seqSeen.add(eventSeq);
        return [decoded];
      }
      return [{ kind: "ignore", reason: "degraded" }];
    }

    if (eventSeq === seqNextExpected) {
      if (eventName === "done" && seqPending.size > 0) {
        seqDegraded = true;
        seqSeen.add(eventSeq);
        seqNextExpected += 1;
        return [{ kind: "degraded", reason: "eof_gap" }, decoded];
      }

      seqSeen.add(eventSeq);
      seqNextExpected += 1;
      const results: DecodedEvent[] = [decoded];
      while (seqPending.has(seqNextExpected)) {
        const pendingSeq = seqNextExpected;
        const entry = seqPending.get(pendingSeq)!;
        seqPending.delete(pendingSeq);
        seqPendingBytes -= entry.byteSize;
        seqSeen.add(pendingSeq);
        seqNextExpected += 1;
        results.push(decodeAsV2(entry.eventName, entry.rawData));
      }
      if (seqPending.size === 0) seqGapStart = null;
      return results;
    }

    if (eventSeq < seqNextExpected) {
      seqSeen.add(eventSeq);
      return [decoded];
    }

    if (seqPending.has(eventSeq)) {
      return [{ kind: "ignore", reason: "duplicate_seq" }];
    }

    // A valid done event is an EOF boundary even when its own sequence is
    // ahead of the missing gap. Keep the decoded done event usable while
    // making the unresolved ordering explicit.
    if (eventName === "done" && seqPending.size > 0) {
      seqDegraded = true;
      seqSeen.add(eventSeq);
      return [{ kind: "degraded", reason: "eof_gap" }, decoded];
    }

    const byteSize = rawData.length;
    seqPending.set(eventSeq, { eventName, rawData, byteSize });
    seqPendingBytes += byteSize;

    if (seqGapStart === null) seqGapStart = clock.now();
    const now = clock.now();
    if (now - seqGapStart >= SEQ_BUFFER_MAX_AGE_MS) {
      seqDegraded = true;
      return [{ kind: "degraded", reason: "timeout" }];
    }
    if (seqPending.size >= SEQ_BUFFER_MAX_COUNT) {
      seqDegraded = true;
      return [{ kind: "degraded", reason: "count" }];
    }
    if (seqPendingBytes >= SEQ_BUFFER_MAX_BYTES) {
      seqDegraded = true;
      return [{ kind: "degraded", reason: "size" }];
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
