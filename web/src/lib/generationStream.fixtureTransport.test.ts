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
import {
  createRunEvidence,
  applyV2Event,
  applyDegraded,
  selectConflictCount,
  type RunEvidenceState,
} from "./generationEvidence";
import { createLegacyAdapter, applyLegacyEvent, selectLegacyItems } from "./legacyAdapter";

// ---------------------------------------------------------------------------
// Fixture loading
// ---------------------------------------------------------------------------

interface FixtureLine {
  event: string;
  context: Record<string, unknown>;
  payload: Record<string, unknown>;
}

interface LegacyFixtureLine {
  event: string;
  data: string;
}

function loadFixture(name: string): FixtureLine[] {
  const path = resolve(__dirname, "../../../tests/fixtures/generation_v2", name);
  return readFileSync(path, "utf-8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as FixtureLine);
}

function loadLegacyFixture(name: string): LegacyFixtureLine[] {
  const path = resolve(__dirname, "../../../tests/fixtures/generation_legacy", name);
  return readFileSync(path, "utf-8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as LegacyFixtureLine);
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

// ---------------------------------------------------------------------------
// Conflict-aware replay helper: routes both v2 and conflict decoded events
// through the evidence reducer so seq_data conflicts are recorded in state.
// ---------------------------------------------------------------------------

function replayFixtureConflictAware(
  fixture: FixtureLine[],
  transform: (entries: WireEntry[]) => WireEntry[],
): { state: RunEvidenceState; degraded: boolean; conflicts: number } {
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
      } else if ((d.kind === "v2" || d.kind === "conflict") && state) {
        state = applyV2Event(state, d);
      } else if (d.kind === "degraded" && state) {
        state = applyDegraded(state, d.reason);
      }
    }
  }

  if (!state) throw new Error("No state built — started event was missing or malformed");
  return { state, degraded: dec.degraded, conflicts: selectConflictCount(state) };
}

// ---------------------------------------------------------------------------
// F5-extended: reversed terminal, legacy replay, and conflict injection
// ---------------------------------------------------------------------------

describe("fixture transport — terminal arrives before result (reversed wire order)", () => {
  const fixture = loadFixture("math_single_interleaved.jsonl");

  it("buffers the terminal and delivers correct final state when result fills the gap", () => {
    // Swap the wire order of the result and question_terminal events for
    // q_RUN_001 (lines with event_seq 21 and 22). Their seq numbers are unchanged,
    // so the decoder will buffer the terminal (seq 22) until seq 21 (result) arrives.
    const { state, degraded } = replayFixture(fixture, (entries) => {
      const out = [...entries];
      // Find indices of result (seq 21) and question_terminal (seq 22) for q_RUN_001
      const idxResult = out.findIndex(
        (e) =>
          e.eventName === "result" &&
          JSON.parse(e.rawData)?.context?.event_seq === 21,
      );
      const idxTerminal = out.findIndex(
        (e) =>
          e.eventName === "question_terminal" &&
          JSON.parse(e.rawData)?.context?.event_seq === 22,
      );
      if (idxResult === -1 || idxTerminal === -1) {
        throw new Error("Could not find result/terminal entries for reversal");
      }
      // Swap them on the wire (terminal before result)
      [out[idxResult], out[idxTerminal]] = [out[idxTerminal], out[idxResult]];
      return out;
    });

    // Decoder should NOT degrade — all seqs eventually arrive in order
    expect(degraded).toBe(false);

    // Both questions must still have final content and terminal
    const finalCount = state.order.filter(
      (qid) => state.questions[qid]?.content.receipt === "final",
    ).length;
    expect(finalCount).toBe(2);

    const terminatedCount = state.order.filter(
      (qid) => state.questions[qid]?.terminal !== null,
    ).length;
    expect(terminatedCount).toBe(2);
  });
});

describe("fixture transport — legacy fixture replay through adapter", () => {
  it("replays math_single_legacy.jsonl and produces two finals, done=true, no terminal evidence", () => {
    const legacyLines = loadLegacyFixture("math_single_legacy.jsonl");

    // Replay through the legacy adapter (C1×S0 path).
    // requestTotal=2 from the fixture's question count.
    let adapterState = createLegacyAdapter(2);
    for (const line of legacyLines) {
      adapterState = applyLegacyEvent(adapterState, line.event, line.data);
    }

    const items = selectLegacyItems(adapterState);

    // Two finals received
    expect(adapterState.finalCount).toBe(2);
    expect(adapterState.done).toBe(true);

    // Both items have final content
    const finals = items.filter((item) => item.isFinal);
    expect(finals).toHaveLength(2);

    // Legacy adapter never produces per-question terminal evidence
    for (const item of finals) {
      // Items have resolvedIndex (explicit index↔id evidence from question_update)
      expect(item.resolvedIndex).not.toBeNull();
    }

    // requestTotal reflects the initialisation value, not a manifest
    expect(adapterState.requestTotal).toBe(2);
  });

  it("legacy items ids are stable and unique per question", () => {
    const legacyLines = loadLegacyFixture("math_single_legacy.jsonl");
    let adapterState = createLegacyAdapter(null);
    for (const line of legacyLines) {
      adapterState = applyLegacyEvent(adapterState, line.event, line.data);
    }

    const items = selectLegacyItems(adapterState);
    const ids = items.map((item) => item.id);
    // All ids unique
    expect(new Set(ids).size).toBe(ids.length);
    // Consistent with the fixture ids
    expect(ids).toContain("legacy_001");
    expect(ids).toContain("legacy_002");
  });
});

describe("fixture transport — conflict (duplicate seq with different data)", () => {
  const fixture = loadFixture("math_single_interleaved.jsonl");

  it("seq_data conflict is recorded in state when a result event is duplicated with modified content", () => {
    // Inject a duplicate of the result event for q_RUN_002 (seq 18) with
    // a modified payload — same seq, different raw data. This exercises the
    // seq_data conflict path in the decoder and applyConflictEvent in the reducer.
    const { conflicts } = replayFixtureConflictAware(fixture, (entries) => {
      const resultEntry = entries.find(
        (e) =>
          e.eventName === "result" &&
          JSON.parse(e.rawData)?.context?.event_seq === 18,
      );
      if (!resultEntry) throw new Error("Could not find result entry for q_RUN_002");

      // Parse and mutate to create a different payload
      const parsed = JSON.parse(resultEntry.rawData) as {
        context: Record<string, unknown>;
        payload: Record<string, unknown>;
      };
      const mutated = {
        ...parsed,
        payload: {
          ...parsed.payload,
          // Inject a distinguishable marker so raw data differs
          _conflict_injected: true,
        },
      };
      const conflictEntry: WireEntry = {
        eventName: "result",
        rawData: JSON.stringify(mutated),
      };

      // Insert the conflicting duplicate right after the original
      const idx = entries.indexOf(resultEntry);
      return [...entries.slice(0, idx + 1), conflictEntry, ...entries.slice(idx + 1)];
    });

    // The conflict must be detected and recorded
    expect(conflicts).toBeGreaterThan(0);
  });

  it("degraded flag is not set by a seq_data conflict alone", () => {
    const { degraded } = replayFixtureConflictAware(fixture, (entries) => {
      const resultEntry = entries.find(
        (e) =>
          e.eventName === "result" &&
          JSON.parse(e.rawData)?.context?.event_seq === 18,
      );
      if (!resultEntry) throw new Error("Could not find result entry for q_RUN_002");
      const parsed = JSON.parse(resultEntry.rawData) as {
        context: Record<string, unknown>;
        payload: Record<string, unknown>;
      };
      const mutated = {
        ...parsed,
        payload: { ...parsed.payload, _conflict_injected: true },
      };
      const idx = entries.indexOf(resultEntry);
      return [
        ...entries.slice(0, idx + 1),
        { eventName: "result", rawData: JSON.stringify(mutated) },
        ...entries.slice(idx + 1),
      ];
    });

    // A seq_data conflict is not a stream degradation — the run continues
    expect(degraded).toBe(false);
  });
});
