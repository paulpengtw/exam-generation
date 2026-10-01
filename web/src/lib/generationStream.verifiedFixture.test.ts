/**
 * Issue #932 — regression: replay math_single_verified.jsonl through the real
 * stream decoder and evidence reducer.
 *
 * The fixture represents a normal verified run:
 *   started → generate stage/llm → question_update rev=1 (draft, no sidecar)
 *   → verify stage/llm → question_update rev=1 (post-verify, +verification sidecar)
 *   → result rev=1 (+verification + metadata + review sidecar)
 *   → question_terminal (review: passed)
 *   → done
 *
 * Before the #932 fix, the browser's questionContentFingerprint only stripped
 * `metadata` at the top level. The post-verify question_update and the result
 * both carry revision=1 but the result adds `verification`, `metadata`, and
 * `review` fields that the old fingerprint treated as content changes, firing
 * same_revision_different_content.
 *
 * After the fix, all 10 sidecar fields are stripped recursively before
 * comparing, so the revision-1 draft → revision-1 result promotion is clean.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { createGenerationStreamDecoder } from "./generationStream";
import {
  createRunEvidence,
  applyV2Event,
  selectEndedCount,
  selectFinalReceivedCount,
  type RunEvidenceState,
} from "./generationEvidence";

// ---------------------------------------------------------------------------
// Fixture replay helper
// ---------------------------------------------------------------------------

interface FixtureLine {
  event: string;
  context: Record<string, unknown>;
  payload: unknown;
}

function loadFixture(name: string): FixtureLine[] {
  const path = resolve(__dirname, "../../../tests/fixtures/generation_v2", name);
  return readFileSync(path, "utf-8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as FixtureLine);
}

function replayFixture(fixture: FixtureLine[]): RunEvidenceState {
  const dec = createGenerationStreamDecoder();
  let state: RunEvidenceState | null = null;

  for (const line of fixture) {
    const rawData = JSON.stringify({ context: line.context, payload: line.payload });
    const results = dec.decode(line.event, rawData);
    for (const d of results) {
      if (d.kind === "v2" && d.event.name === "started") {
        if (dec.run) {
          state = createRunEvidence(dec.run);
        }
      } else if (d.kind === "v2" && state) {
        state = applyV2Event(state, d);
      }
    }
  }

  if (!state) throw new Error("No state — started event missing or malformed");
  return state;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("fixture replay — math_single_verified.jsonl (issue #932)", () => {
  const fixture = loadFixture("math_single_verified.jsonl");

  it("clean replay: 1 question, final receipt, no conflict", () => {
    const state = replayFixture(fixture);
    expect(Object.keys(state.questions)).toHaveLength(1);
    expect(selectFinalReceivedCount(state)).toBe(1);
    expect(selectEndedCount(state)).toBe(1);
  });

  it("no content conflict despite sidecar fields added at same revision", () => {
    const state = replayFixture(fixture);
    const qids = state.order;
    expect(qids).toHaveLength(1);
    const qev = state.questions[qids[0]!];
    expect(qev).toBeDefined();
    // The core fix: no same_revision_different_content conflict
    expect(qev!.contentConflict).toBe(false);
    expect(qev!.contentConflictReason).toBeUndefined();
  });

  it("review status is passed", () => {
    const state = replayFixture(fixture);
    const qids = state.order;
    const qev = state.questions[qids[0]!];
    expect(qev!.review.status).toBe("passed");
  });

  it("no batch-level conflict", () => {
    const state = replayFixture(fixture);
    expect(state.batchConflict).toBe(false);
  });

  it("decoder did not degrade", () => {
    const dec = createGenerationStreamDecoder();
    for (const line of fixture) {
      dec.decode(line.event, JSON.stringify({ context: line.context, payload: line.payload }));
    }
    expect(dec.degraded).toBe(false);
  });
});
