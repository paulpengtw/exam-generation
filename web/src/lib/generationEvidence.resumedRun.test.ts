/**
 * Issue #911: Resumed run — 已結束/收到最終結果 counts do not inflate.
 *
 * When a run's host dies and a recovery attempt re-streams events for the same
 * question IDs, the frontend's selectEndedCount and selectFinalReceivedCount
 * must stay at the number of *unique* questions, never double-count.
 *
 * Three scenarios:
 *   A. Duplicate live question_terminal events (same payload) — idempotent.
 *   B. applyRunSnapshot called twice with a completed snapshot — idempotent.
 *   C. Realistic recovery: q-1 ended via DB poll (attempt 1 result),
 *      q-2 ended via live stream (attempt 2), followed by a final poll
 *      that sees both done — selectEndedCount stays 2.
 */

import { describe, expect, it } from "vitest";
import {
  applyRunSnapshot,
  type RunSnapshot,
  type RunSnapshotQuestion,
} from "./runSnapshot";
import {
  createRunEvidence,
  applyV2Event,
  selectEndedCount,
  selectFinalReceivedCount,
  type RunEvidenceState,
} from "./generationEvidence";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RUN_ID = "run-1";
const MANIFEST = [
  { index: 0, questionId: "q-1" },
  { index: 1, questionId: "q-2" },
];

function freshRun(): RunEvidenceState {
  return createRunEvidence({ runId: RUN_ID, total: 2, manifest: MANIFEST });
}

const sampleQuestion = (id: string) => ({
  id,
  情境: ["個人"],
  題型種類: "單一題",
  題型: "選擇題",
  題目: [`question ${id}`],
  正確解題分析: ["answer"],
});

function makeResultEvent(questionId: string, seq: number) {
  return {
    kind: "v2" as const,
    event: {
      name: "result",
      context: {
        run_id: RUN_ID,
        event_seq: seq,
        question_id: questionId,
        index: MANIFEST.findIndex((m) => m.questionId === questionId),
        content_revision: 1,
      },
      payload: sampleQuestion(questionId),
    },
  };
}

function makeTerminalEvent(questionId: string, seq: number) {
  return {
    kind: "v2" as const,
    event: {
      name: "question_terminal",
      context: {
        run_id: RUN_ID,
        event_seq: seq,
        question_id: questionId,
        index: MANIFEST.findIndex((m) => m.questionId === questionId),
      },
      payload: {
        termination_reason: "normal",
        has_final: true,
        final_revision: 1,
        delivery_status: "complete",
        expected: [],
        delivered: [],
        missing: [],
        review: { status: "passed", content_revision: 1 },
      },
    },
  };
}

function endedSnapshotQuestion(id: string, index: number): RunSnapshotQuestion {
  return {
    index,
    question_id: id,
    processing: "ended",
    current_step: null,
    termination_reason: "normal",
    terminal: {
      termination_reason: "normal",
      has_final: true,
      final_revision: 1,
      delivery_status: "complete",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "passed", content_revision: 1 },
    },
    error: null,
    result: {
      record_id: `rec-${id}`,
      question: sampleQuestion(id),
      verification_trail: null,
      figure_policy_trail: null,
      reference_example_record: null,
    },
  };
}

function completedSnapshot(): RunSnapshot {
  return {
    run_id: RUN_ID,
    status: "running",
    subject: "math",
    total: 2,
    started_at: null,
    completed_at: null,
    error: null,
    questions: [
      endedSnapshotQuestion("q-1", 0),
      endedSnapshotQuestion("q-2", 1),
    ],
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("resumed run — 已結束/收到最終結果 counts do not inflate", () => {
  it("scenario A: duplicate question_terminal events for same questions are idempotent", () => {
    let state = freshRun();

    // First delivery: both questions terminated normally.
    state = applyV2Event(state, makeResultEvent("q-1", 1));
    state = applyV2Event(state, makeTerminalEvent("q-1", 2));
    state = applyV2Event(state, makeResultEvent("q-2", 3));
    state = applyV2Event(state, makeTerminalEvent("q-2", 4));
    expect(selectEndedCount(state)).toBe(2);
    expect(selectFinalReceivedCount(state)).toBe(2);

    // Second delivery with the same payloads (recovery reconnect re-streaming).
    state = applyV2Event(state, makeResultEvent("q-1", 5));
    state = applyV2Event(state, makeTerminalEvent("q-1", 6));
    state = applyV2Event(state, makeResultEvent("q-2", 7));
    state = applyV2Event(state, makeTerminalEvent("q-2", 8));

    // Counts must remain at exactly 2 — no inflation from re-delivery.
    expect(selectEndedCount(state)).toBe(2);
    expect(selectFinalReceivedCount(state)).toBe(2);
  });

  it("scenario B: applyRunSnapshot with a completed snapshot is idempotent", () => {
    const snap = completedSnapshot();

    const once = applyRunSnapshot(null, snap);
    expect(selectEndedCount(once)).toBe(2);
    expect(selectFinalReceivedCount(once)).toBe(2);

    // Applying the same snapshot a second time must not change the state.
    const twice = applyRunSnapshot(once, snap);
    expect(selectEndedCount(twice)).toBe(2);
    expect(selectFinalReceivedCount(twice)).toBe(2);
    // Reference equality: applyRunSnapshot is pure and idempotent.
    expect(twice).toBe(once);
  });

  it("scenario C: q-1 ended from DB poll (attempt 1), q-2 ended from live stream (attempt 2), final poll → selectEndedCount = 2", () => {
    // Attempt 1 completed q-1 and then the host died before q-2.
    // A new host picks up the run (attempt 2) and completes q-2.
    // The frontend sees:
    //   1. A poll snapshot where q-1 is ended and q-2 is still running.
    //   2. Live stream events delivering q-2's result and terminal.
    //   3. A follow-up poll with both questions ended.
    // Throughout, selectEndedCount and selectFinalReceivedCount must top out at 2.

    const partialSnap: RunSnapshot = {
      run_id: RUN_ID,
      status: "running",
      subject: "math",
      total: 2,
      started_at: null,
      completed_at: null,
      error: null,
      questions: [
        endedSnapshotQuestion("q-1", 0),
        {
          index: 1,
          question_id: "q-2",
          processing: "running",
          current_step: null,
          termination_reason: null,
          terminal: null,
          error: null,
          result: null,
        },
      ],
    };

    // Step 1: first poll — q-1 ended, q-2 running.
    let state = applyRunSnapshot(null, partialSnap);
    expect(selectEndedCount(state)).toBe(1);
    expect(selectFinalReceivedCount(state)).toBe(1);

    // Step 2: live stream delivers q-2's result and terminal.
    state = applyV2Event(state, makeResultEvent("q-2", 10));
    state = applyV2Event(state, makeTerminalEvent("q-2", 11));
    expect(selectEndedCount(state)).toBe(2);
    expect(selectFinalReceivedCount(state)).toBe(2);

    // Step 3: follow-up poll with both ended — must not inflate counts.
    const finalSnap = completedSnapshot();
    state = applyRunSnapshot(state, finalSnap);
    expect(selectEndedCount(state)).toBe(2);
    expect(selectFinalReceivedCount(state)).toBe(2);
  });
});
