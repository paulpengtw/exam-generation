/**
 * F5: Real sender fixture transport tests (issue #748).
 *
 * These tests replay `math_single_interleaved.jsonl` through the real decoder
 * and evidence reducer with a test transport that can drop, duplicate, or
 * reorder events — verifying that the seq dedup and bounded-buffer machinery
 * produces correct final state.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { createGenerationStreamDecoder } from "./generationStream";
import { createRunEvidence, applyV2Event, applyDegraded, type RunEvidenceState } from "./generationEvidence";

// ---------------------------------------------------------------------------
// Fixture loading
// ---------------------------------------------------------------------------

interface FixtureLine {
  event: string;
  context: Record<string, unknown>;
  payload: Record<string, unknown>;
}

function loadFixture(name: string): FixtureLine[] {
  const path = resolve(__dirname, "../../../tests/fixtures/generation_v2", name);
  return readFileSync(path, "utf-8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as FixtureLine);
}

// ---------------------------------------------------------------------------
// Transport helper: replay fixture lines through a real decoder+reducer.
// `transform` receives the ordered list of wire payloads and may rearrange,
// duplicate, or drop entries.
// ---------------------------------------------------------------------------

type WireEntry = { eventName: string; rawData: string };

function replayFixture(
  fixture: FixtureLine[],
  transform: (entries: WireEntry[]) => WireEntry[] = (e) => e,
): { state: RunEvidenceState; degraded: boolean } {
  const entries: WireEntry[] = fixture.map((line) => ({
    eventName: line.event,
    rawData: JSON.stringify({ context: line.context, payload: line.payload }),
  }));

  const transformed = transform(entries);

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

  if (!state) throw new Error("No state built — started event was missing or malformed");
  return { state, degraded: dec.degraded };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("fixture transport — math_single_interleaved.jsonl", () => {
  const fixture = loadFixture("math_single_interleaved.jsonl");

  it("clean replay produces 2 final receipts and 2 ended questions", () => {
    const { state, degraded } = replayFixture(fixture);

    // 2 questions in manifest
    expect(Object.keys(state.questions)).toHaveLength(2);

    // Both questions should have ended (question_terminal received)
    const questionIds = state.order;
    let endedCount = 0;
    for (const qid of questionIds) {
      const qev = state.questions[qid];
      if (qev?.terminal !== null) endedCount++;
    }
    expect(endedCount).toBe(2);

    // Both questions should have final receipts
    let finalCount = 0;
    for (const qid of questionIds) {
      const qev = state.questions[qid];
      if (qev?.content.receipt === "final") finalCount++;
    }
    expect(finalCount).toBe(2);
    expect(degraded).toBe(false);
  });

  it("duplicate events are ignored — same final state as clean replay", () => {
    const { state: clean } = replayFixture(fixture);

    // Duplicate every line
    const { state: duped, degraded } = replayFixture(fixture, (entries) => {
      const out: WireEntry[] = [];
      for (const e of entries) {
        out.push(e, e); // send each event twice
      }
      return out;
    });

    expect(degraded).toBe(false);
    expect(Object.keys(duped.questions)).toHaveLength(Object.keys(clean.questions).length);
    // Final receipt count should be the same
    const finalCount = (s: RunEvidenceState) =>
      s.order.filter((qid) => s.questions[qid]?.content.receipt === "final").length;
    expect(finalCount(duped)).toBe(finalCount(clean));
  });

  it("reordering events resolves correctly when all events arrive", () => {
    // Reverse the non-started events to force maximum reordering.
    const { state, degraded } = replayFixture(fixture, (entries) => {
      const [started, ...rest] = entries;
      return [started, ...rest.reverse()];
    });

    // All events eventually arrive so the buffer should fill.
    expect(degraded).toBe(false);
    const finalCount = state.order.filter((qid) => state.questions[qid]?.content.receipt === "final").length;
    expect(finalCount).toBe(2);
  });

  it("dropped activity events cause eof_gap degradation but content/terminal events are flushed and preserved", () => {
    // Drop all stage/pipeline/llm_request/llm_response events. These activity
    // events occupy seq slots, so dropping them creates a permanent seq gap
    // that triggers eof_gap degradation when `done` arrives. The decoder must
    // flush buffered question_update/result/question_terminal events so final
    // question content is still available despite the degraded stream.
    const activityNames = new Set(["stage", "pipeline", "llm_request", "llm_response"]);
    const { state, degraded } = replayFixture(fixture, (entries) =>
      entries.filter((e) => !activityNames.has(e.eventName)),
    );

    // Degradation is expected — activity events held gaps open
    expect(degraded).toBe(true);
    // Content events were flushed from the pending buffer on degradation
    const finalCount = state.order.filter((qid) => state.questions[qid]?.content.receipt === "final").length;
    expect(finalCount).toBe(2);
  });

  it("dropping the 'done' event does not degrade — stream stays open", () => {
    // Without done, the run stays open but should still have received content.
    const { state, degraded } = replayFixture(fixture, (entries) =>
      entries.filter((e) => e.eventName !== "done"),
    );

    expect(degraded).toBe(false);
    const finalCount = state.order.filter((qid) => state.questions[qid]?.content.receipt === "final").length;
    expect(finalCount).toBe(2);
  });
});
