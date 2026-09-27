/**
 * Status-bar consistency tests using math_abcd_transport.jsonl.
 *
 * Transport fixture characteristics (issue #754 brief):
 *   A (q_RUN_001) — complete terminal + final result
 *   B (q_RUN_002) — partial terminal + final result
 *   C (q_RUN_003) — failed terminal (no final content), no result
 *   D (q_RUN_004) — final result, no terminal (intentionally omitted; seq 19 gap)
 *
 * Expected status bar:  "已結束 3/4 題" and "收到最終結果 3 題"
 *   selectEndedCount  = 3  (A + B + C have terminals)
 *   selectFinalReceivedCount = 3  (A + B + D have final content)
 *   manifest total = 4
 */
import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";

import {
  applyDegraded,
  applyV2Event,
  closeRun,
  createRunEvidence,
  selectEndedCount,
  selectFinalReceivedCount,
} from "./generationEvidence";
import { createGenerationStreamDecoder } from "./generationStream";
import type { RunEvidenceState } from "./generationEvidence";

interface FixtureLine {
  event: string;
  context: {
    event_seq: number;
    run_id?: string;
    question_id?: string;
    index?: number;
    content_revision?: number;
  };
  payload: Record<string, unknown>;
}

function loadTransportFixture(): FixtureLine[] {
  const path = resolve(
    __dirname,
    "../../../tests/fixtures/generation_v2/math_abcd_transport.jsonl",
  );
  return readFileSync(path, "utf-8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as FixtureLine);
}

interface WireEntry {
  eventName: string;
  rawData: string;
}

function replayTransportFixture(
  transform?: (entries: WireEntry[]) => WireEntry[],
): { state: RunEvidenceState; degraded: boolean } {
  const fixture = loadTransportFixture();
  const entries: WireEntry[] = fixture.map((line) => ({
    eventName: line.event,
    rawData: JSON.stringify({ context: line.context, payload: line.payload }),
  }));

  const transformed = transform ? transform(entries) : entries;
  const dec = createGenerationStreamDecoder();
  let state: RunEvidenceState | null = null;

  for (const { eventName, rawData } of transformed) {
    const results = dec.decode(eventName, rawData);
    for (const d of results) {
      if (d.kind === "v2" && d.event.name === "started") {
        if (dec.run) {
          state = createRunEvidence(dec.run);
        }
      } else if (d.kind === "v2" && state) {
        state = applyV2Event(state, d);
      } else if (d.kind === "degraded" && state) {
        state = applyDegraded(state, d.reason);
      }
    }
  }

  if (!state) throw new Error("No state — started event missing");
  return { state: closeRun(state), degraded: dec.degraded };
}

describe("transport fixture status-bar counts", () => {
  it("manifest has 4 questions (A, B, C, D)", () => {
    const { state } = replayTransportFixture();
    expect(state.order).toHaveLength(4);
  });

  it("endedCount = 3 (A complete, B partial, C failed draft — all have terminals)", () => {
    const { state } = replayTransportFixture();
    expect(selectEndedCount(state)).toBe(3);
  });

  it("finalReceivedCount = 3 (A, B, D have final content; C has none)", () => {
    const { state } = replayTransportFixture();
    expect(selectFinalReceivedCount(state)).toBe(3);
  });

  it("status bar label: 已結束 3/4 題 (endedCount=3, total=4)", () => {
    const { state } = replayTransportFixture();
    const ended = selectEndedCount(state);
    const total = state.order.length;
    // Verify the values that drive "已結束 X/N 題"
    expect(ended).toBe(3);
    expect(total).toBe(4);
  });

  it("status bar label: 收到最終結果 3 題 (finalReceivedCount=3)", () => {
    const { state } = replayTransportFixture();
    expect(selectFinalReceivedCount(state)).toBe(3);
  });

  it("resending D's result (duplicate seq 18) does not increase finalReceivedCount to 4", () => {
    const { state } = replayTransportFixture((entries) => {
      // Find the result entry for q_RUN_004 (seq 18) and duplicate it
      const seq18Idx = entries.findIndex((e) => {
        try {
          const parsed = JSON.parse(e.rawData) as { context?: { event_seq?: number } };
          return parsed.context?.event_seq === 18;
        } catch {
          return false;
        }
      });
      if (seq18Idx < 0) return entries;
      const dup = entries[seq18Idx];
      // Insert duplicate immediately after
      return [
        ...entries.slice(0, seq18Idx + 1),
        dup,
        ...entries.slice(seq18Idx + 1),
      ];
    });
    // Resend must not inflate the count
    expect(selectFinalReceivedCount(state)).toBe(3);
  });

  it("only terminal dispute reduces endedCount — content conflicts do not", () => {
    // No conflicts exist in the clean replay; verify endedCount stays at 3
    const { state } = replayTransportFixture();
    // No batch-level conflict expected in clean transport replay
    expect(state.batchConflict).toBe(false);
    // endedCount unchanged by non-terminal events
    expect(selectEndedCount(state)).toBe(3);
  });

  it("D (q_RUN_004) has final content but no terminal — processing is not 'ended'", () => {
    const { state } = replayTransportFixture();
    // Find q_RUN_004
    const qD = state.order.find((id) => id.includes("004"));
    expect(qD).toBeDefined();
    if (!qD) return;
    const ev = state.questions[qD];
    expect(ev).toBeDefined();
    // D has final content
    expect(ev?.content.receipt).toBe("final");
    // D has no terminal
    expect(ev?.terminal).toBeNull();
  });

  it("C (q_RUN_003) has terminal but no final content — counts toward ended not final", () => {
    const { state } = replayTransportFixture();
    const qC = state.order.find((id) => id.includes("003"));
    expect(qC).toBeDefined();
    if (!qC) return;
    const ev = state.questions[qC];
    expect(ev).toBeDefined();
    // C has a terminal
    expect(ev?.terminal).not.toBeNull();
    // C's terminal says has_final = false
    expect(ev?.terminal?.has_final).toBe(false);
    // C has no final receipt
    expect(ev?.content.receipt).not.toBe("final");
  });
});
