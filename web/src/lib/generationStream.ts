import type {
  DraftPhase,
  FigurePolicyTrailEntry,
  GeneratedQuestion,
  LlmCallEvent,
  ReferenceExampleRecordShape,
  VerificationTrailEntry,
} from "../hooks/useGenerate";
import type { GenerationLegacyEvidence } from "./runEvidence";

export function projectGenerationEvidence(
  llmCalls: readonly LlmCallEvent[],
  subQuestionCount: number | null,
): GenerationLegacyEvidence {
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

/** A decoded event from the stream. */
export type DecodedEvent =
  | { kind: "v2"; event: { name: string; context: Record<string, unknown>; payload: unknown } }
  | { kind: "legacy"; name: string; data: string }
  | { kind: "mode"; mode: "unsupported"; reason: "unknown_protocol" | "invalid_manifest" | "missing_started" }
  | { kind: "ignore"; reason: string }
  | { kind: "held" };

/** Stateful decoder for a single generate() call's SSE stream. */
export interface GenerationStreamDecoder {
  readonly mode: DecoderMode;
  readonly run: RunManifest | null;
  /** Decode one SSE event. Returns an array (usually length 1; >1 when held events are replayed). */
  decode(eventName: string, rawData: string): DecodedEvent[];
}

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

export function createGenerationStreamDecoder(): GenerationStreamDecoder {
  let mode: DecoderMode = "awaiting-start";
  let run: RunManifest | null = null;
  const held: Array<{ name: string; rawData: string }> = [];

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
        const startedEvent: DecodedEvent = {
          kind: "v2",
          event: { name: "started", context: ctx, payload: p },
        };
        // Replay held events through the now-v2 decoder
        const toReplay = held.splice(0);
        const replayed = toReplay.map((h) => decodeAsV2(h.name, h.rawData));
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

    decode(eventName: string, rawData: string): DecodedEvent[] {
      if (mode === "unsupported") {
        return [{ kind: "ignore", reason: "unsupported" }];
      }
      if (mode === "v2") {
        return [decodeAsV2(eventName, rawData)];
      }
      if (mode === "legacy") {
        return [{ kind: "legacy", name: eventName, data: rawData }];
      }
      // awaiting-start
      if (eventName === "started") {
        return processStarted(rawData);
      }
      if (eventName === "done" || eventName === "error") {
        mode = "unsupported";
        return [{ kind: "mode", mode: "unsupported", reason: "missing_started" }];
      }
      // Hold non-started events
      held.push({ name: eventName, rawData });
      return [{ kind: "held" }];
    },
  };
}
