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
  total: 1,
  questions: [{ index: 0, question_id: "q_001" }],
  generation_log_id: null,
};
const START_CTX = { run_id: RUN_ID, event_seq: 1 };
const validStartedData = JSON.stringify({ context: START_CTX, payload: MANIFEST });

function makeV2Event(name: string, seq: number, payload: unknown = {}) {
  return JSON.stringify({
    context: { run_id: RUN_ID, event_seq: seq, question_id: "q_001", index: 0 },
    payload,
  });
}

describe("seq buffer — time bound (2 s)", () => {
  it("degrades after gap timer exceeds 2000 ms (event-driven path)", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData); // seq 1 processed, nextExpected = 2

    // seq 3 arrives (gap: seq 2 missing) — held, timer starts
    const r1 = dec.decode("stage", makeV2Event("stage", 3, { agent: "verifier", stage: "verify", status: "start" }));
    expect(r1).toEqual([{ kind: "held" }]);
    expect(dec.degraded).toBe(false);

    advance(2001); // now past 2s threshold

    // seq 4 arrives — still out of order, clock check fires
    const r2 = dec.decode("stage", makeV2Event("stage", 4, { agent: "verifier", stage: "verify", status: "end" }));
    expect(r2[0]).toEqual({ kind: "degraded", reason: "timeout" });
    expect(dec.degraded).toBe(true);
  });
});

describe("seq buffer — checkDeadline() (timer-driven path)", () => {
  it("returns degraded when deadline has elapsed with no new event", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // seq 3 arrives — gap opens at t=0
    dec.decode("stage", makeV2Event("stage", 3, { agent: "verifier", stage: "verify", status: "start" }));
    expect(dec.degraded).toBe(false);

    // Advance clock but send no new events
    advance(2001);

    // Timer fires and calls checkDeadline()
    const result = dec.checkDeadline();
    expect(result[0]).toEqual({ kind: "degraded", reason: "timeout" });
    expect(dec.degraded).toBe(true);
  });

  it("returns [] when gap has not yet elapsed", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);
    dec.decode("stage", makeV2Event("stage", 3, { agent: "verifier", stage: "verify", status: "start" }));

    advance(999); // still within 2 s window
    expect(dec.checkDeadline()).toEqual([]);
    expect(dec.degraded).toBe(false);
  });

  it("returns [] when already degraded", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);
    dec.decode("stage", makeV2Event("stage", 3));
    advance(2001);
    dec.decode("stage", makeV2Event("stage", 4)); // triggers event-driven degradation

    expect(dec.degraded).toBe(true);
    expect(dec.checkDeadline()).toEqual([]);
  });

  it("returns [] when no gap is open", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);
    // seq 2 in-order — no gap
    dec.decode("stage", makeV2Event("stage", 2, { agent: "planner", stage: "plan", status: "end" }));
    expect(dec.checkDeadline()).toEqual([]);
  });

  it("flushes buffered content/terminal events alongside degraded on timer fire", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // Enqueue a question_update at seq 3 (gap: seq 2 missing)
    const updateData = JSON.stringify({
      context: { run_id: RUN_ID, event_seq: 3, question_id: "q_001", index: 0, content_revision: 1 },
      payload: { phase: "draft", question: { id: "q_001", 題型種類: "單一題", 題型: "選擇題", 題目: ["q"], 正確解題分析: ["a"], 情境: ["個人"] } },
    });
    dec.decode("question_update", updateData);
    expect(dec.degraded).toBe(false);

    advance(2001);
    const result = dec.checkDeadline();
    expect(result[0]).toEqual({ kind: "degraded", reason: "timeout" });
    // The buffered question_update should have been released as a v2 event
    expect(result.length).toBeGreaterThan(1);
    expect(result[1]).toMatchObject({ kind: "v2", event: { name: "question_update" } });
  });
});

describe("seq buffer — pending flush on degrade", () => {
  it("releases buffered question_update/result/question_terminal on count-bound degradation", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData); // nextExpected = 2

    // Buffer a question_update at seq 3 (gap: seq 2 missing) → pending.size = 1
    const updateData = JSON.stringify({
      context: { run_id: RUN_ID, event_seq: 3, question_id: "q_001", index: 0, content_revision: 1 },
      payload: { phase: "draft", question: { id: "q_001", 題型種類: "單一題", 題型: "選擇題", 題目: ["q"], 正確解題分析: ["a"], 情境: ["個人"] } },
    });
    dec.decode("question_update", updateData);

    // Add 254 more stage events (seqs 4..257) → pending.size = 255 — still under 256
    for (let seq = 4; seq <= 257; seq++) {
      const r = dec.decode("stage", makeV2Event("stage", seq));
      expect(r).toEqual([{ kind: "held" }]);
    }
    expect(dec.degraded).toBe(false);

    // seq 258: pending.size reaches 256 → count-bound degradation fires
    const r = dec.decode("stage", makeV2Event("stage", 258));
    expect(r[0]).toEqual({ kind: "degraded", reason: "count" });
    // The question_update at seq 3 should be in the flush output
    const flushed = r.slice(1);
    expect(flushed.some((e) => e.kind === "v2" && e.event.name === "question_update")).toBe(true);
    expect(dec.degraded).toBe(true);
  });

  it("drops buffered activity events (stage/pipeline/llm_*) on degrade", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // stage event in pending buffer
    dec.decode("stage", makeV2Event("stage", 3, { agent: "verifier", stage: "verify", status: "start" }));
    advance(2001);

    const result = dec.checkDeadline();
    // The stage event at seq 3 must NOT appear in the flush result
    const flushed = result.slice(1);
    expect(flushed.every((e) => e.kind !== "v2" || e.event.name !== "stage")).toBe(true);
  });
});

describe("seq buffer — count bound (256)", () => {
  it("degrades when 256 distinct out-of-order events are pending", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData); // seq 1, nextExpected = 2

    // Send seq 3..257, skipping seq 2 (255 events buffered)
    for (let seq = 3; seq <= 257; seq++) {
      const r = dec.decode("stage", makeV2Event("stage", seq));
      expect(r).toEqual([{ kind: "held" }]);
    }
    expect(dec.degraded).toBe(false);

    // 256th pending event
    const r = dec.decode("stage", makeV2Event("stage", 258));
    expect(r).toEqual([{ kind: "degraded", reason: "count" }]);
    expect(dec.degraded).toBe(true);
  });
});

describe("seq buffer — size bound (4 MiB)", () => {
  it("degrades when pending data exceeds 4 MiB (ASCII)", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // Create a large payload (~2.1 MiB each)
    const bigPayload = JSON.stringify({ text: "x".repeat(2 * 1024 * 1024 + 100) });
    const data3 = JSON.stringify({ context: { run_id: RUN_ID, event_seq: 3, question_id: "q_001", index: 0 }, payload: { text: bigPayload } });
    const data4 = JSON.stringify({ context: { run_id: RUN_ID, event_seq: 4, question_id: "q_001", index: 0 }, payload: { text: bigPayload } });

    const r3 = dec.decode("question_update", data3); // seq 3, gap -> held
    expect(r3).toEqual([{ kind: "held" }]);

    const r4 = dec.decode("question_update", data4); // seq 4, total > 4MiB -> degraded
    expect(r4[0]).toEqual({ kind: "degraded", reason: "size" });
    expect(dec.degraded).toBe(true);
  });

  it("measures UTF-8 bytes: CJK characters (3 bytes each) exceed 4 MiB before UTF-16 chars would", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // Each CJK char is 3 UTF-8 bytes but only 1 UTF-16 char.
    // We need pending bytes > 4 MiB == 4 * 1024 * 1024 bytes.
    // Pack slightly more than 4/3 MiB of CJK per event so two events exceed 4 MiB.
    const cjkBlock = "中".repeat(1024 * 1024 / 2); // ~1.5 MiB UTF-8 per block
    const data3 = JSON.stringify({ context: { run_id: RUN_ID, event_seq: 3, question_id: "q_001", index: 0 }, payload: { text: cjkBlock } });
    const data4 = JSON.stringify({ context: { run_id: RUN_ID, event_seq: 4, question_id: "q_001", index: 0 }, payload: { text: cjkBlock } });
    const data5 = JSON.stringify({ context: { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0 }, payload: { text: cjkBlock } });

    dec.decode("question_update", data3); // seq 3, gap -> held
    dec.decode("question_update", data4); // seq 4, ~3 MiB total -> still held
    const r5 = dec.decode("question_update", data5); // seq 5, ~4.5 MiB -> degraded
    expect(r5[0]).toEqual({ kind: "degraded", reason: "size" });
    expect(dec.degraded).toBe(true);
  });
});

describe("seq buffer — in-bound fill", () => {
  it("delivers buffered events in order when gap is filled", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // seq 3 arrives first (gap) -> held
    const stageData = makeV2Event("stage", 3, { agent: "verifier", stage: "verify", status: "start" });
    const r3 = dec.decode("stage", stageData);
    expect(r3).toEqual([{ kind: "held" }]);

    // seq 2 fills the gap -> returns seq 2 AND the buffered seq 3
    const pipelineData = makeV2Event("pipeline", 2, { event_name: "question_start" });
    const r2 = dec.decode("pipeline", pipelineData);
    expect(r2).toHaveLength(2);
    expect(r2[0]).toMatchObject({ kind: "v2", event: { name: "pipeline" } });
    expect(r2[1]).toMatchObject({ kind: "v2", event: { name: "stage" } });
    expect(dec.degraded).toBe(false);
  });
});

describe("seq buffer — EOF gap", () => {
  it("degrades immediately when done arrives with open gap", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // Create gap: seq 3 buffered, seq 2 missing
    dec.decode("stage", makeV2Event("stage", 3));

    // done event at seq 4 — gap still open
    const doneData = makeV2Event("done", 4);
    const result = dec.decode("done", doneData);
    expect(result[0]).toEqual({ kind: "degraded", reason: "eof_gap" });
    expect(result[1]).toMatchObject({ kind: "v2", event: { name: "done" } });
  });
});

describe("seq buffer — unknown event kind", () => {
  // Issue #748 acceptance: an unknown-but-legal v2 event occupies its seq slot
  // so it closes the gap and prevents a permanent hole.
  it("accepts unknown kind in valid envelope and advances seq", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData); // nextExpected = 2

    // seq 2 with unknown name
    const unknownData = makeV2Event("future_unknown_event", 2);
    const result = dec.decode("future_unknown_event", unknownData);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ kind: "v2", event: { name: "future_unknown_event" } });

    // seq 3 should be next expected (seq 2 was consumed — no permanent gap)
    const stageData = makeV2Event("stage", 3);
    const r3 = dec.decode("stage", stageData);
    expect(r3[0]).toMatchObject({ kind: "v2" }); // in-order, not held
    expect(dec.degraded).toBe(false);
  });

  it("unknown kind fills gap when it arrives out-of-order", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData); // nextExpected = 2

    // seq 3 arrives first — gap
    dec.decode("stage", makeV2Event("stage", 3));

    // seq 2 unknown kind fills the gap
    const r2 = dec.decode("future_event", makeV2Event("future_event", 2));
    expect(r2[0]).toMatchObject({ kind: "v2", event: { name: "future_event" } });
    // seq 3 should be flushed from buffer
    expect(r2).toHaveLength(2);
    expect(r2[1]).toMatchObject({ kind: "v2", event: { name: "stage" } });
    expect(dec.degraded).toBe(false);
  });
});

describe("seq buffer — duplicate non-inflation", () => {
  it("ignores duplicate seq and does not inflate pending buffer", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // seq 3 -> held
    const data3 = makeV2Event("stage", 3);
    dec.decode("stage", data3);

    // Same seq 3 again -> duplicate, ignored
    const r = dec.decode("stage", data3);
    expect(r).toEqual([{ kind: "ignore", reason: "duplicate_seq" }]);

    expect(dec.degraded).toBe(false);
  });

  it("duplicate of already-seen in-order event is also ignored", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    const data2 = makeV2Event("pipeline", 2, { event_name: "question_start" });
    dec.decode("pipeline", data2); // in-order, processes seq 2

    // Send seq 2 again
    const r = dec.decode("pipeline", data2);
    expect(r).toEqual([{ kind: "ignore", reason: "duplicate_seq" }]);
  });
});

describe("seq buffer — large in-order body", () => {
  it("does not count in-order large event toward pending bytes", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // 5 MiB in-order event at seq 2
    const bigRawData = JSON.stringify({
      context: { run_id: RUN_ID, event_seq: 2, question_id: "q_001", index: 0 },
      payload: { text: "x".repeat(5 * 1024 * 1024) },
    });
    const result = dec.decode("question_update", bigRawData);
    expect(result[0]).toMatchObject({ kind: "v2" });
    expect(dec.degraded).toBe(false);
  });
});

describe("seq buffer — post-degradation pass-through", () => {
  it("forwards question_update with unseen seq after degradation", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);

    // Trigger time-bound degradation
    dec.decode("stage", makeV2Event("stage", 3)); // gap, timer starts
    advance(2001);
    dec.decode("stage", makeV2Event("stage", 4)); // -> degraded
    expect(dec.degraded).toBe(true);

    // Now send a question_update with a new (unseen) seq
    const updateDataWithRevision = JSON.stringify({
      context: { run_id: RUN_ID, event_seq: 10, question_id: "q_001", index: 0, content_revision: 1 },
      payload: { phase: "draft", question: { id: "q_001", 題型種類: "單一題", 題型: "選擇題", 題目: ["q"], 正確解題分析: ["a"], 情境: ["個人"] } },
    });
    const r = dec.decode("question_update", updateDataWithRevision);
    expect(r[0]).toMatchObject({ kind: "v2", event: { name: "question_update" } });
  });

  it("ignores stage events after degradation", () => {
    const { clock, advance } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData);
    dec.decode("stage", makeV2Event("stage", 3));
    advance(2001);
    dec.decode("stage", makeV2Event("stage", 4)); // -> degraded

    const r = dec.decode("stage", makeV2Event("stage", 99));
    expect(r).toEqual([{ kind: "ignore", reason: "degraded" }]);
  });
});
