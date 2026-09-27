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
  it("degrades after gap timer exceeds 2000 ms", () => {
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
    expect(r2).toEqual([{ kind: "degraded", reason: "timeout" }]);
    expect(dec.degraded).toBe(true);
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
  it("degrades when pending data exceeds 4 MiB", () => {
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
    expect(r4).toEqual([{ kind: "degraded", reason: "size" }]);
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
  it("accepts unknown kind in valid envelope and advances seq", () => {
    const { clock } = makeClock();
    const dec = createGenerationStreamDecoder({ clock });
    dec.decode("started", validStartedData); // nextExpected = 2

    // seq 2 with unknown name
    const unknownData = makeV2Event("future_unknown_event", 2);
    const result = dec.decode("future_unknown_event", unknownData);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ kind: "v2", event: { name: "future_unknown_event" } });

    // seq 3 should be next expected (seq 2 was consumed)
    const stageData = makeV2Event("stage", 3);
    const r3 = dec.decode("stage", stageData);
    expect(r3[0]).toMatchObject({ kind: "v2" }); // in-order, not held
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
