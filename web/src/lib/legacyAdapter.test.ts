/**
 * Issue #750 — Legacy adapter unit tests.
 *
 * Test cases required by the issue:
 *  1. A has index draft, B has no-index final → both kept, B never overwrites A
 *  2. Duplicate final → deduplicated (only first adopted)
 *  3. Late consistent mapping → resolvedIndex updated
 *  4. Inconsistent mapping stays unknown
 *  5. done ≠ terminal (items retained, done flag set, no per-question terminal)
 *  6. Request total labeled correctly (from params, not manifest)
 *  7. Unknown version stays unsupported — tested via decoder in generationStream.test.ts
 *  8. Disconnect retains content (no auto-resubmit; adapter holds items on done)
 */

import { describe, expect, it } from "vitest";
import {
  applyLegacyEvent,
  createLegacyAdapter,
  selectLegacyItems,
} from "./legacyAdapter";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQuestion(题目: string, id?: string) {
  const q: Record<string, unknown> = {
    情境: ["個人"],
    題型種類: "單一題",
    題型: "選擇題",
    題目: [题目],
    正確解題分析: ["answer"],
  };
  if (id !== undefined) q.id = id;
  return q;
}

function qUpdate(index: number, question: Record<string, unknown>, phase = "draft", stable_id?: string): string {
  const p: Record<string, unknown> = { index, phase, question };
  if (stable_id !== undefined) p.stable_id = stable_id;
  return JSON.stringify(p);
}

function qResult(question: Record<string, unknown>, stable_id?: string, index?: number): string {
  const p: Record<string, unknown> = { ...question };
  if (stable_id !== undefined) p.stable_id = stable_id;
  if (index !== undefined) p.index = index;
  return JSON.stringify(p);
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

describe("createLegacyAdapter", () => {
  it("creates an empty state with requestTotal", () => {
    const state = createLegacyAdapter(3);
    expect(state.items.size).toBe(0);
    expect(state.finalCount).toBe(0);
    expect(state.requestTotal).toBe(3);
    expect(state.done).toBe(false);
    expect(state._idCounter).toBe(0);
  });

  it("accepts null requestTotal", () => {
    expect(createLegacyAdapter(null).requestTotal).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Test 1: A index draft, B no-index final → both kept, B never overwrites A
// ---------------------------------------------------------------------------

describe("A index draft + B no-index final", () => {
  it("both items kept, B does not overwrite A, B position unknown", () => {
    let state = createLegacyAdapter(2);

    // A: question_update with explicit index=0
    const qA = makeQuestion("Question A", "q_a");
    state = applyLegacyEvent(state, "question_update", qUpdate(0, qA, "draft"));
    expect(state.items.size).toBe(1);
    const itemA = state.items.get("q_a")!;
    expect(itemA).toBeDefined();
    expect(itemA.resolvedIndex).toBe(0);
    expect(itemA.isFinal).toBe(false);
    expect(state.finalCount).toBe(0);

    // B: result with no id, no index (generates synthetic id)
    const qB = makeQuestion("Question B");
    state = applyLegacyEvent(state, "result", JSON.stringify(qB));
    expect(state.items.size).toBe(2);
    expect(state.finalCount).toBe(1);

    // Find B (synthetic id)
    const itemB = Array.from(state.items.values()).find((i) => i.id !== "q_a");
    expect(itemB).toBeDefined();
    expect(itemB!.resolvedIndex).toBeNull(); // 原題序未知
    expect(itemB!.isFinal).toBe(true);

    // A is unchanged
    const itemAAfter = state.items.get("q_a")!;
    expect(itemAAfter.resolvedIndex).toBe(0);
    expect(itemAAfter.isFinal).toBe(false);
    expect(itemAAfter.question.題目).toEqual(["Question A"]);
  });

  it("result for same id as draft upgrades to final preserving resolvedIndex", () => {
    let state = createLegacyAdapter(1);
    const q = makeQuestion("Draft Q", "q1");

    // Draft arrives first with index=0
    state = applyLegacyEvent(state, "question_update", qUpdate(0, q, "draft", "q1"));
    expect(state.items.get("q1")!.resolvedIndex).toBe(0);
    expect(state.items.get("q1")!.isFinal).toBe(false);

    // Final arrives for same id, no index
    const qFinal = makeQuestion("Final Q", "q1");
    state = applyLegacyEvent(state, "result", qResult(qFinal, "q1"));
    expect(state.items.size).toBe(1); // same item upgraded
    const item = state.items.get("q1")!;
    expect(item.isFinal).toBe(true);
    expect(item.resolvedIndex).toBe(0); // preserved from draft mapping
    expect(state.finalCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Test 2: Duplicate final → deduplicated
// ---------------------------------------------------------------------------

describe("duplicate final", () => {
  it("second result for same stable_id is ignored", () => {
    let state = createLegacyAdapter(1);
    const q = makeQuestion("Q1", "q1");

    state = applyLegacyEvent(state, "result", qResult(q, "q1"));
    expect(state.finalCount).toBe(1);
    const item1 = state.items.get("q1")!;
    expect(item1.question.題目).toEqual(["Q1"]);

    // Second result with same id
    const q2 = makeQuestion("Q1 duplicate", "q1");
    const stateBefore = state;
    state = applyLegacyEvent(state, "result", qResult(q2, "q1"));

    // State should not change
    expect(state).toBe(stateBefore);
    expect(state.finalCount).toBe(1);
    expect(state.items.get("q1")!.question.題目).toEqual(["Q1"]); // original preserved
  });

  it("results for different ids are both counted", () => {
    let state = createLegacyAdapter(2);
    state = applyLegacyEvent(state, "result", qResult(makeQuestion("Q1", "q1"), "q1"));
    state = applyLegacyEvent(state, "result", qResult(makeQuestion("Q2", "q2"), "q2"));
    expect(state.finalCount).toBe(2);
    expect(state.items.size).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Test 3: Late consistent mapping places it
// ---------------------------------------------------------------------------

describe("late consistent mapping", () => {
  it("result arrives without index, later question_update places it", () => {
    let state = createLegacyAdapter(2);

    // result arrives first with no index
    const q = makeQuestion("Q at unknown position", "q_late");
    state = applyLegacyEvent(state, "result", qResult(q, "q_late"));
    expect(state.items.get("q_late")!.resolvedIndex).toBeNull();
    expect(state.finalCount).toBe(1);

    // Later, question_update arrives for same id with explicit index
    const qDraft = makeQuestion("Q draft", "q_late");
    state = applyLegacyEvent(state, "question_update", qUpdate(1, qDraft, "draft", "q_late"));

    // resolvedIndex should now be resolved
    const item = state.items.get("q_late")!;
    expect(item.resolvedIndex).toBe(1);
    // isFinal should still be true (content not overwritten)
    expect(item.isFinal).toBe(true);
    expect(item.question.題目).toEqual(["Q at unknown position"]);
  });

  it("mapping recorded from question_update propagates to later result", () => {
    let state = createLegacyAdapter(1);

    // question_update establishes index mapping
    const qDraft = makeQuestion("Draft", "q_map");
    state = applyLegacyEvent(state, "question_update", qUpdate(3, qDraft, "draft", "q_map"));
    expect(state.items.get("q_map")!.resolvedIndex).toBe(3);

    // result arrives for same id, no index
    const qFinal = makeQuestion("Final", "q_map");
    state = applyLegacyEvent(state, "result", qResult(qFinal, "q_map"));
    expect(state.items.get("q_map")!.resolvedIndex).toBe(3); // inherited
    expect(state.items.get("q_map")!.isFinal).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Test 4: Inconsistent mapping stays unknown
// ---------------------------------------------------------------------------

describe("inconsistent mapping stays unknown", () => {
  it("same id with different index → second mapping rejected", () => {
    let state = createLegacyAdapter(2);

    // First: id=q1 at index=0
    const q = makeQuestion("Q1", "q1");
    state = applyLegacyEvent(state, "question_update", qUpdate(0, q, "draft", "q1"));
    expect(state.items.get("q1")!.resolvedIndex).toBe(0);

    // Second: same id at index=2 → inconsistent
    const q2 = makeQuestion("Q1 updated", "q1");
    state = applyLegacyEvent(state, "question_update", qUpdate(2, q2, "draft", "q1"));
    // resolvedIndex should still be 0 (the first consistent mapping wins)
    expect(state.items.get("q1")!.resolvedIndex).toBe(0);
    // Content IS updated (new draft version)
    expect(state.items.get("q1")!.question.題目).toEqual(["Q1 updated"]);
  });

  it("same index with different id → second id gets no index", () => {
    let state = createLegacyAdapter(2);

    // First: id=q1 at index=0
    state = applyLegacyEvent(state, "question_update", qUpdate(0, makeQuestion("Q1", "q1"), "draft", "q1"));
    expect(state._indexToId.get(0)).toBe("q1");

    // Second: different id at same index=0 → inconsistent
    state = applyLegacyEvent(state, "question_update", qUpdate(0, makeQuestion("Q2", "q2"), "draft", "q2"));
    // q2 should have null resolvedIndex (mapping rejected)
    expect(state.items.get("q2")!.resolvedIndex).toBeNull();
    // q1 mapping is unchanged
    expect(state._indexToId.get(0)).toBe("q1");
  });
});

// ---------------------------------------------------------------------------
// Test 5: done ≠ terminal
// ---------------------------------------------------------------------------

describe("done is not per-question terminal", () => {
  it("done sets done flag; items are retained", () => {
    let state = createLegacyAdapter(2);
    state = applyLegacyEvent(state, "result", qResult(makeQuestion("Q1", "q1"), "q1"));
    state = applyLegacyEvent(state, "question_update", qUpdate(0, makeQuestion("Q2 draft", "q2"), "draft", "q2"));
    state = applyLegacyEvent(state, "done", "");

    expect(state.done).toBe(true);
    expect(state.items.size).toBe(2);
    expect(state.finalCount).toBe(1);
    // Items are still accessible
    expect(state.items.get("q1")!.isFinal).toBe(true);
    expect(state.items.get("q2")!.isFinal).toBe(false);
  });

  it("events after done are ignored", () => {
    let state = createLegacyAdapter(1);
    state = applyLegacyEvent(state, "done", "");
    expect(state.done).toBe(true);

    const stateBefore = state;
    state = applyLegacyEvent(state, "result", qResult(makeQuestion("Late Q", "q1"), "q1"));
    expect(state).toBe(stateBefore); // no change
    expect(state.items.size).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Test 6: Request total
// ---------------------------------------------------------------------------

describe("requestTotal", () => {
  it("is preserved from creation and never inferred from items", () => {
    const state = createLegacyAdapter(5);
    let s = applyLegacyEvent(state, "result", qResult(makeQuestion("Q1", "q1"), "q1"));
    s = applyLegacyEvent(s, "result", qResult(makeQuestion("Q2", "q2"), "q2"));
    expect(s.requestTotal).toBe(5); // unchanged
    expect(s.finalCount).toBe(2);   // actual received count is different
  });
});

// ---------------------------------------------------------------------------
// Test: disconnect retains content (done before all finals)
// ---------------------------------------------------------------------------

describe("disconnect retains content", () => {
  it("partial content remains after done", () => {
    let state = createLegacyAdapter(3);
    state = applyLegacyEvent(state, "question_update", qUpdate(0, makeQuestion("Q1 draft", "q1"), "draft", "q1"));
    state = applyLegacyEvent(state, "result", qResult(makeQuestion("Q1 final", "q1"), "q1"));
    // Disconnect (done) before Q2 and Q3 arrive
    state = applyLegacyEvent(state, "done", "");

    expect(state.done).toBe(true);
    expect(state.items.size).toBe(1);
    expect(state.finalCount).toBe(1);
    expect(state.requestTotal).toBe(3); // still shows the request total
  });
});

// ---------------------------------------------------------------------------
// Test: selectLegacyItems ordering
// ---------------------------------------------------------------------------

describe("selectLegacyItems", () => {
  it("sorts known-index items first (ascending), then unknown-index items", () => {
    let state = createLegacyAdapter(4);

    // Add items in non-sequential order
    state = applyLegacyEvent(state, "result", qResult(makeQuestion("idx2", "q2"), "q2", 2));
    state = applyLegacyEvent(state, "result", qResult(makeQuestion("no-idx", "qx"))); // no index
    state = applyLegacyEvent(state, "result", qResult(makeQuestion("idx0", "q0"), "q0", 0));
    state = applyLegacyEvent(state, "result", qResult(makeQuestion("idx1", "q1"), "q1", 1));

    const items = selectLegacyItems(state);
    expect(items).toHaveLength(4);
    expect(items[0].id).toBe("q0");
    expect(items[0].resolvedIndex).toBe(0);
    expect(items[1].id).toBe("q1");
    expect(items[1].resolvedIndex).toBe(1);
    expect(items[2].id).toBe("q2");
    expect(items[2].resolvedIndex).toBe(2);
    // Unknown-index last
    expect(items[3].resolvedIndex).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Test: no placeholder cards without manifest
// ---------------------------------------------------------------------------

describe("no placeholder cards without manifest", () => {
  it("items.size is always the number of received items (no pre-allocated slots)", () => {
    const state = createLegacyAdapter(5); // requested 5 questions
    expect(state.items.size).toBe(0); // no pre-allocated slots
    expect(selectLegacyItems(state)).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Test: synthetic id for question_update without explicit id or index
// ---------------------------------------------------------------------------

describe("synthetic id generation", () => {
  it("items without any id get unique synthetic ids", () => {
    let state = createLegacyAdapter(3);

    // question_update with no id and no index (rare but handled)
    state = applyLegacyEvent(
      state,
      "question_update",
      JSON.stringify({ phase: "draft", question: makeQuestion("Draft no id or index") }),
    );
    expect(state.items.size).toBe(1);
    const item = Array.from(state.items.values())[0];
    expect(item.resolvedIndex).toBeNull();
    expect(item.id).toMatch(/^legacy-draft-gen-/);
  });
});

// ---------------------------------------------------------------------------
// Test: legacy fixture replay
// ---------------------------------------------------------------------------

describe("legacy fixture replay (math_single_legacy.jsonl)", () => {
  it("produces two items with correct positions", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");

    const path = resolve(__dirname, "../../../tests/fixtures/generation_legacy/math_single_legacy.jsonl");
    const lines = readFileSync(path, "utf-8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as { event: string; data: string });

    let state = createLegacyAdapter(2);
    for (const line of lines) {
      state = applyLegacyEvent(state, line.event, line.data);
    }

    expect(state.done).toBe(true);
    expect(state.finalCount).toBe(2);
    expect(state.items.size).toBe(2);

    const items = selectLegacyItems(state);
    // Both items should have resolved indexes from their question_update → result mapping
    expect(items[0].resolvedIndex).toBe(0);
    expect(items[0].isFinal).toBe(true);
    expect(items[0].question.題目).toEqual(["Legacy Q1 final"]);
    expect(items[1].resolvedIndex).toBe(1);
    expect(items[1].isFinal).toBe(true);
    expect(items[1].question.題目).toEqual(["Legacy Q2 final"]);
  });
});
