/**
 * F5: Conflict isolation tests for the stream decoder (issue #749).
 *
 * Covers:
 *  - same-seq-different-data fingerprinting (seq conflict)
 *  - same-seq-same-data still treated as idempotent duplicate
 *  - raw legacy event mixed into v2 stream (legacy_in_v2)
 *  - seq conflict with no question_id → unattributable
 *  - after permanent degradation, seq conflict still detected
 */
import { describe, expect, it } from "vitest";
import { createGenerationStreamDecoder } from "./generationStream";

function makeClock(initialMs = 0) {
  let t = initialMs;
  return {
    advance(ms: number) { t += ms; },
    clock: { now: () => t },
  };
}

const RUN_ID = "TESTRUN";
const MANIFEST = {
  protocol_version: 2,
  total: 2,
  questions: [
    { index: 0, question_id: "q_001" },
    { index: 1, question_id: "q_002" },
  ],
  generation_log_id: null,
};
const START_CTX = { run_id: RUN_ID, event_seq: 1 };
const validStartedData = JSON.stringify({ context: START_CTX, payload: MANIFEST });

function makeV2Event(name: string, seq: number, extraCtx: Record<string, unknown> = {}, payload: unknown = {}) {
  return JSON.stringify({
    context: { run_id: RUN_ID, event_seq: seq, question_id: "q_001", index: 0, ...extraCtx },
    payload,
  });
}

function makeV2EventNoQuestion(name: string, seq: number, payload: unknown = {}) {
  return JSON.stringify({
    context: { run_id: RUN_ID, event_seq: seq },
    payload,
  });
}

// ---------------------------------------------------------------------------
// Same-seq-different-data (fingerprint conflict)
// ---------------------------------------------------------------------------

describe("conflict isolation — same-seq-different-data", () => {
  it("emits seq_data conflict when same seq arrives with different payload", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);

    // seq 2 arrives and is processed
    const firstData = makeV2Event("stage", 2, {}, { agent: "planner", status: "start" });
    dec.decode("stage", firstData);

    // seq 2 arrives again with different payload → conflict
    const secondData = makeV2Event("stage", 2, {}, { agent: "verifier", status: "start" });
    const result = dec.decode("stage", secondData);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      kind: "conflict",
      conflictType: "seq_data",
      seq: 2,
      questionId: "q_001",
    });
  });

  it("includes the conflicting event's name in the conflict event", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);

    const firstData = makeV2Event("question_update", 2, {}, { content: "v1" });
    dec.decode("question_update", firstData);

    const secondData = makeV2Event("question_update", 2, {}, { content: "v2" });
    const result = dec.decode("question_update", secondData);

    expect(result[0]).toMatchObject({
      kind: "conflict",
      conflictType: "seq_data",
      seq: 2,
      eventName: "question_update",
      questionId: "q_001",
    });
  });

  it("still emits ignore/duplicate_seq when same-seq-same-data (idempotent resend)", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);

    const data = makeV2Event("stage", 2, {}, { agent: "planner", status: "start" });
    dec.decode("stage", data);

    // Exact same raw data → idempotent
    const result = dec.decode("stage", data);
    expect(result).toEqual([{ kind: "ignore", reason: "duplicate_seq" }]);
  });

  it("extracts questionId from context of the conflicting event", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);

    const first = makeV2Event("question_update", 2, { question_id: "q_002" }, { x: 1 });
    dec.decode("question_update", first);

    const second = makeV2Event("question_update", 2, { question_id: "q_002" }, { x: 2 });
    const result = dec.decode("question_update", second);

    expect(result[0]).toMatchObject({ kind: "conflict", conflictType: "seq_data", questionId: "q_002" });
  });

  it("sets questionId to null when conflict event has no question_id in context", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);

    const first = makeV2EventNoQuestion("done", 2, { status: "ok" });
    dec.decode("done", first);

    const second = makeV2EventNoQuestion("done", 2, { status: "err" });
    const result = dec.decode("done", second);

    expect(result[0]).toMatchObject({
      kind: "conflict",
      conflictType: "seq_data",
      seq: 2,
      questionId: null,
    });
  });

  it("detects conflict for a seq that was flushed from pending buffer during degradation", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // seq 3 buffered (gap: seq 2 missing)
    const pending = makeV2Event("question_update", 3, {}, { x: "original" });
    dec.decode("question_update", pending);
    expect(dec.degraded).toBe(false);

    // Degrade via timeout
    advance(2001);
    dec.checkDeadline();
    expect(dec.degraded).toBe(true);

    // seq 3 arrives again with different data → still detectable as conflict
    const conflict = makeV2Event("question_update", 3, {}, { x: "different" });
    const result = dec.decode("question_update", conflict);
    expect(result[0]).toMatchObject({ kind: "conflict", conflictType: "seq_data", seq: 3 });
  });
});

// ---------------------------------------------------------------------------
// Raw legacy events mixed into a v2 stream
// ---------------------------------------------------------------------------

describe("conflict isolation — legacy_in_v2", () => {
  it("emits legacy_in_v2 conflict when a raw legacy event arrives in v2 mode", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);

    // Raw legacy event: no context key
    const legacyData = JSON.stringify({ id: "q_001", 題目: ["legacy question"] });
    const result = dec.decode("result", legacyData);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ kind: "conflict", conflictType: "legacy_in_v2" });
  });

  it("does NOT switch the decoder to legacy mode after a legacy_in_v2 event", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);

    const legacyData = JSON.stringify({ some_field: "raw" });
    dec.decode("result", legacyData);

    // Decoder remains in v2 mode
    expect(dec.mode).toBe("v2");
  });

  it("emits legacy_in_v2 for a plain-string legacy result", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);

    // A legacy event that IS a valid JSON object but has no context key
    const legacyData = JSON.stringify({ generation_log_id: "abc123" });
    const result = dec.decode("update", legacyData);
    expect(result[0]).toMatchObject({ kind: "conflict", conflictType: "legacy_in_v2" });
  });

  it("context present but wrong type is NOT flagged as legacy_in_v2 (remains invalid_envelope)", () => {
    const dec = createGenerationStreamDecoder();
    dec.decode("started", validStartedData);

    // context key present but is a string, not an object
    const malformed = JSON.stringify({ context: "not-an-object", payload: {} });
    const result = dec.decode("stage", malformed);

    // Should be ignored (invalid_envelope), not flagged as legacy
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ kind: "ignore" });
    expect(result[0]).not.toMatchObject({ kind: "conflict" });
  });
});

// ---------------------------------------------------------------------------
// After-degradation seq conflict still detected
// ---------------------------------------------------------------------------

describe("conflict isolation — after degradation", () => {
  it("detects seq_data conflict on a content event after degradation", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // seq 2 in-order
    const first = makeV2Event("question_update", 2, {}, { x: 1 });
    dec.decode("question_update", first);

    // Force degradation via gap
    dec.decode("stage", makeV2Event("stage", 4, {}, {}));
    advance(2001);
    dec.checkDeadline();
    expect(dec.degraded).toBe(true);

    // seq 2 arrives again with different data after degradation → still conflict
    const second = makeV2Event("question_update", 2, {}, { x: 999 });
    const result = dec.decode("question_update", second);
    expect(result[0]).toMatchObject({ kind: "conflict", conflictType: "seq_data", seq: 2 });
  });
});
