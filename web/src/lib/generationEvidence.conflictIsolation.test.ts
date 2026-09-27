/**
 * F5: Evidence reducer conflict isolation tests (issue #749).
 *
 * Covers:
 *  - same-revision-different-content → contentConflict, body retained
 *  - manifest/payload identity mismatch → contentConflict
 *  - contradictory terminal → terminalConflict, processing=unknown, excluded from X
 *  - review-only contradiction → reviewConflict, processing stays "ended", X unchanged
 *  - seq_data conflict event on terminal → terminalConflict
 *  - seq_data conflict event on content → contentConflict
 *  - unattributable seq conflict → batchConflict
 *  - legacy_in_v2 → legacyMixed only
 *  - A body retained, B unaffected after A has terminal conflict
 *  - after permanent degradation, independent trustworthy results still accepted
 */
import { describe, expect, it } from "vitest";
import type { DecodedEvent } from "./generationStream";
import {
  createRunEvidence,
  applyV2Event,
  applyDegraded,
  selectEndedCount,
  selectFinalReceivedCount,
  type RunEvidenceState,
} from "./generationEvidence";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEvent(name: string, context: Record<string, unknown>, payload: unknown) {
  return { kind: "v2" as const, event: { name, context, payload } };
}

const RUN_ID = "RUN";
const MANIFEST = [
  { index: 0, questionId: "q_001" },
  { index: 1, questionId: "q_002" },
];

function freshRun(): RunEvidenceState {
  return createRunEvidence({ runId: RUN_ID, total: 2, manifest: MANIFEST });
}

function ctx(questionId: string, seq: number, extra: Record<string, unknown> = {}) {
  return { run_id: RUN_ID, event_seq: seq, question_id: questionId, index: 0, ...extra };
}

function sampleQuestion(id: string, marker = "v1") {
  return {
    id,
    情境: ["個人"],
    題型種類: "單一題",
    題型: "選擇題",
    題目: [`question ${id} ${marker}`],
    正確解題分析: ["answer"],
  };
}

/** A valid question_terminal payload for has_final=true, passed review, all empty slots. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function validTerminal(_questionId: string) {
  return {
    termination_reason: "normal" as const,
    has_final: true,
    final_revision: 1,
    delivery_status: "complete" as const,
    expected: [],
    delivered: [],
    missing: [],
    review: { status: "passed", content_revision: 1 },
  };
}

/** A valid question_terminal payload for has_final=false (no final). */
function noFinalTerminal() {
  return {
    termination_reason: "failed" as const,
    has_final: false,
    final_revision: null,
    delivery_status: "none" as const,
    expected: [],
    delivered: [],
    missing: [],
    review: { status: "unknown", unknown_reason: "generation failed" },
  };
}

// ---------------------------------------------------------------------------
// Same-revision-different-content
// ---------------------------------------------------------------------------

describe("same-revision-different-content", () => {
  it("marks contentConflict when question_update same revision arrives with different content; body retained", () => {
    let state = freshRun();

    // First draft at revision 1
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 2, { content_revision: 1 }),
      { question: sampleQuestion("q_001", "v1") },
    ));
    expect(state.questions["q_001"].content.revision).toBe(1);
    expect(state.questions["q_001"].contentConflict).toBeFalsy();

    // Same revision 1, different content
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 3, { content_revision: 1 }),
      { question: sampleQuestion("q_001", "v2_different") },
    ));
    expect(state.questions["q_001"].contentConflict).toBe(true);
    // Original body retained
    expect((state.questions["q_001"].content.question as { 題目: string[] }).題目[0]).toContain("v1");
    // processing NOT set to unknown (only terminal disputes do that)
    expect(state.questions["q_001"].processing).not.toBe("unknown");
  });

  it("idempotent same-revision-same-content is not flagged as conflict", () => {
    let state = freshRun();
    const q = sampleQuestion("q_001");
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 2, { content_revision: 1 }),
      { question: q },
    ));
    // Exact same data resent
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 3, { content_revision: 1 }),
      { question: q },
    ));
    expect(state.questions["q_001"].contentConflict).toBeFalsy();
  });

  it("marks contentConflict when result same final revision arrives with different content", () => {
    let state = freshRun();

    // Final at revision 1
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 2, { content_revision: 1 }),
      sampleQuestion("q_001", "final-v1"),
    ));
    expect(state.questions["q_001"].content.receipt).toBe("final");

    // Same revision 1, different final content
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 3, { content_revision: 1 }),
      sampleQuestion("q_001", "final-v2"),
    ));
    expect(state.questions["q_001"].contentConflict).toBe(true);
    // Original final body retained
    expect((state.questions["q_001"].content.question as { 題目: string[] }).題目[0]).toContain("final-v1");
  });

  it("does not affect sibling question q_002", () => {
    let state = freshRun();
    const q1a = sampleQuestion("q_001", "a");
    const q1b = sampleQuestion("q_001", "b");

    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 2, { content_revision: 1 }), { question: q1a }));
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 3, { content_revision: 1 }), { question: q1b }));

    // q_002 gets normal content
    state = applyV2Event(state, makeEvent("result",
      ctx("q_002", 4, { content_revision: 1 }),
      sampleQuestion("q_002")));
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_002", 5), validTerminal("q_002")));

    expect(state.questions["q_001"].contentConflict).toBe(true);
    expect(state.questions["q_002"].contentConflict).toBeFalsy();
    expect(state.questions["q_002"].processing).toBe("ended");
    expect(selectEndedCount(state)).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Manifest/payload identity mismatch
// ---------------------------------------------------------------------------

describe("manifest/payload identity mismatch", () => {
  it("marks contentConflict when result payload id doesn't match context question_id", () => {
    let state = freshRun();

    // result for q_001 but payload has id="q_999" (not in manifest)
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 2, { content_revision: 1 }),
      { ...sampleQuestion("q_999"), id: "q_999" },
    ));

    expect(state.questions["q_001"].contentConflict).toBe(true);
    expect(state.questions["q_001"].content.receipt).toBe("none"); // not updated
  });

  it("accepts result when payload id matches context question_id", () => {
    let state = freshRun();

    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 2, { content_revision: 1 }),
      sampleQuestion("q_001"),
    ));

    expect(state.questions["q_001"].contentConflict).toBeFalsy();
    expect(state.questions["q_001"].content.receipt).toBe("final");
  });

  it("accepts result when payload has no id field (legacy shape)", () => {
    let state = freshRun();
    const { id: _dropped, ...noId } = sampleQuestion("q_001");
    void _dropped;

    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 2, { content_revision: 1 }),
      noId,
    ));

    expect(state.questions["q_001"].contentConflict).toBeFalsy();
    expect(state.questions["q_001"].content.receipt).toBe("final");
  });

  it("marks contentConflict when question_update payload id doesn't match context", () => {
    let state = freshRun();

    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 2, { content_revision: 1 }),
      { question: { ...sampleQuestion("q_002"), id: "q_002" } },
    ));

    expect(state.questions["q_001"].contentConflict).toBe(true);
    expect(state.questions["q_001"].content.receipt).toBe("none");
  });
});

// ---------------------------------------------------------------------------
// Contradictory terminal and review
// ---------------------------------------------------------------------------

describe("contradictory terminal — terminal conflict", () => {
  it("marks terminalConflict, processing=unknown, and excludes from endedCount (X)", () => {
    let state = freshRun();

    // First valid terminal
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2), validTerminal("q_001")));
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(selectEndedCount(state)).toBe(1);

    // Second terminal with different outcome
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), noFinalTerminal()));

    expect(state.questions["q_001"].terminalConflict).toBe(true);
    expect(state.questions["q_001"].processing).toBe("unknown");
    expect(selectEndedCount(state)).toBe(0); // excluded from X
  });

  it("does not affect sibling q_002 terminal", () => {
    let state = freshRun();

    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2), validTerminal("q_001")));
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), noFinalTerminal()));

    state = applyV2Event(state, makeEvent("result",
      ctx("q_002", 4, { content_revision: 1 }), sampleQuestion("q_002")));
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_002", 5), validTerminal("q_002")));

    expect(state.questions["q_002"].terminalConflict).toBeFalsy();
    expect(state.questions["q_002"].processing).toBe("ended");
    expect(selectEndedCount(state)).toBe(1); // only q_002 counted
  });
});

describe("contradictory review — review-only conflict", () => {
  it("marks reviewConflict but keeps processing=ended and does NOT reduce endedCount", () => {
    let state = freshRun();

    // First terminal: passed review
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2), validTerminal("q_001")));

    // Second terminal: same outcome, different review (failed instead of passed)
    const failedReview = {
      ...validTerminal("q_001"),
      review: { status: "failed", content_revision: 1 },
    };
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), failedReview));

    expect(state.questions["q_001"].reviewConflict).toBe(true);
    expect(state.questions["q_001"].terminalConflict).toBeFalsy();
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(selectEndedCount(state)).toBe(1); // still counted in X
  });
});

// ---------------------------------------------------------------------------
// Conflict DecodedEvent handling in applyV2Event
// ---------------------------------------------------------------------------

describe("applyV2Event — conflict events from decoder", () => {
  it("seq_data conflict on question_terminal → terminalConflict, processing=unknown, excluded from X", () => {
    let state = freshRun();
    const conflictEv: DecodedEvent = {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 3,
      eventName: "question_terminal",
      questionId: "q_001",
    };
    state = applyV2Event(state, conflictEv);

    expect(state.questions["q_001"].terminalConflict).toBe(true);
    expect(state.questions["q_001"].processing).toBe("unknown");
    expect(selectEndedCount(state)).toBe(0);
  });

  it("seq_data conflict on question_update → contentConflict, processing unchanged", () => {
    let state = freshRun();
    const conflictEv: DecodedEvent = {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 2,
      eventName: "question_update",
      questionId: "q_001",
    };
    state = applyV2Event(state, conflictEv);

    expect(state.questions["q_001"].contentConflict).toBe(true);
    expect(state.questions["q_001"].processing).toBe("waiting"); // unchanged from initial
    expect(selectEndedCount(state)).toBe(0);
  });

  it("seq_data conflict on result → contentConflict", () => {
    let state = freshRun();
    const conflictEv: DecodedEvent = {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 2,
      eventName: "result",
      questionId: "q_001",
    };
    state = applyV2Event(state, conflictEv);

    expect(state.questions["q_001"].contentConflict).toBe(true);
  });

  it("seq_data conflict on activity event → no question flags changed, no batchConflict", () => {
    let state = freshRun();
    const conflictEv: DecodedEvent = {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 2,
      eventName: "stage",
      questionId: "q_001",
    };
    state = applyV2Event(state, conflictEv);

    expect(state.questions["q_001"].terminalConflict).toBeFalsy();
    expect(state.questions["q_001"].contentConflict).toBeFalsy();
    expect(state.batchConflict).toBe(false);
  });

  it("seq_data conflict with questionId=null → batchConflict, individual questions unaffected", () => {
    let state = freshRun();
    const conflictEv: DecodedEvent = {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 5,
      eventName: "done",
      questionId: null,
    };
    state = applyV2Event(state, conflictEv);

    expect(state.batchConflict).toBe(true);
    expect(state.questions["q_001"].terminalConflict).toBeFalsy();
    expect(state.questions["q_001"].contentConflict).toBeFalsy();
    expect(state.questions["q_002"].terminalConflict).toBeFalsy();
  });

  it("seq_data conflict with unknown questionId → batchConflict", () => {
    let state = freshRun();
    const conflictEv: DecodedEvent = {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 5,
      eventName: "question_update",
      questionId: "q_unknown_not_in_manifest",
    };
    state = applyV2Event(state, conflictEv);

    expect(state.batchConflict).toBe(true);
  });

  it("legacy_in_v2 → sets legacyMixed, does NOT set batchConflict or question flags", () => {
    let state = freshRun();
    const conflictEv: DecodedEvent = { kind: "conflict", conflictType: "legacy_in_v2" };
    state = applyV2Event(state, conflictEv);

    expect(state.legacyMixed).toBe(true);
    expect(state.batchConflict).toBe(false);
    expect(state.questions["q_001"].terminalConflict).toBeFalsy();
    expect(state.questions["q_001"].contentConflict).toBeFalsy();
  });

  it("legacy_in_v2 does NOT erase independently confirmed terminal facts", () => {
    let state = freshRun();
    // q_001 ends normally
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 2, { content_revision: 1 }), sampleQuestion("q_001")));
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), validTerminal("q_001")));

    expect(state.questions["q_001"].processing).toBe("ended");
    expect(state.questions["q_001"].terminal).not.toBeNull();

    // Now a legacy event arrives
    state = applyV2Event(state, { kind: "conflict", conflictType: "legacy_in_v2" });

    // q_001's terminal fact must NOT be erased
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(state.questions["q_001"].terminal).not.toBeNull();
    expect(selectEndedCount(state)).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Unknown completeness does not erase confirmed terminals
// ---------------------------------------------------------------------------

describe("unknown completeness — batchConflict does not erase individual terminals", () => {
  it("batchConflict does not change endedCount for already-confirmed questions", () => {
    let state = freshRun();

    // Both questions end normally
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 2, { content_revision: 1 }), sampleQuestion("q_001")));
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), validTerminal("q_001")));
    state = applyV2Event(state, makeEvent("result",
      ctx("q_002", 4, { content_revision: 1 }), sampleQuestion("q_002")));
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_002", 5), validTerminal("q_002")));

    expect(selectEndedCount(state)).toBe(2);

    // Batch conflict arrives
    const conflictEv: DecodedEvent = {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 6,
      eventName: "done",
      questionId: null,
    };
    state = applyV2Event(state, conflictEv);

    expect(state.batchConflict).toBe(true);
    // Confirmed terminals NOT erased
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(state.questions["q_002"].processing).toBe("ended");
    expect(selectEndedCount(state)).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// A body retained, B unaffected — combined scenario
// ---------------------------------------------------------------------------

describe("conflict isolation — A body retained, B unaffected", () => {
  it("A has terminal conflict (body retained); B's trusted final/terminal unaffected; only B counted in X", () => {
    let state = freshRun();

    // A receives content
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 2, { content_revision: 1 }), sampleQuestion("q_001", "original")));

    // A gets conflicting terminals
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), validTerminal("q_001")));
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 4), noFinalTerminal()));

    // B receives content and valid terminal
    state = applyV2Event(state, makeEvent("result",
      ctx("q_002", 5, { content_revision: 1 }), sampleQuestion("q_002")));
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_002", 6), validTerminal("q_002")));

    // A: body retained (original question kept)
    const aBody = state.questions["q_001"].content.question as { 題目: string[] } | null;
    expect(aBody).not.toBeNull();
    expect(aBody?.題目[0]).toContain("original");
    // A: terminalConflict, processing=unknown
    expect(state.questions["q_001"].terminalConflict).toBe(true);
    expect(state.questions["q_001"].processing).toBe("unknown");

    // B: unaffected
    expect(state.questions["q_002"].terminalConflict).toBeFalsy();
    expect(state.questions["q_002"].processing).toBe("ended");
    expect(state.questions["q_002"].content.receipt).toBe("final");

    // X excludes A (terminal conflict), counts only B
    expect(selectEndedCount(state)).toBe(1);
    expect(selectFinalReceivedCount(state)).toBe(2); // both have final receipts
  });
});

// ---------------------------------------------------------------------------
// After permanent degradation, independent trustworthy results still accepted
// ---------------------------------------------------------------------------

describe("after permanent degradation", () => {
  it("result and question_terminal are still accepted after degradation", () => {
    let state = freshRun();
    state = applyDegraded(state, "timeout");
    expect(state.degraded).toBe(true);

    // result accepted after degradation
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 10, { content_revision: 1 }), sampleQuestion("q_001")));
    expect(state.questions["q_001"].content.receipt).toBe("final");

    // question_terminal accepted after degradation
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 11), validTerminal("q_001")));
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(selectEndedCount(state)).toBe(1);
  });

  it("activity events (stage, llm_*) are skipped after degradation", () => {
    let state = freshRun();
    state = applyDegraded(state, "timeout");

    state = applyV2Event(state, makeEvent("stage",
      ctx("q_001", 10), { stage: "verify", agent: "verifier", status: "start" }));
    // No change expected (activity dropped)
    expect(state.questions["q_001"].processing).toBe("waiting");
  });

  it("seq_data conflict events are still handled after degradation", () => {
    let state = freshRun();
    state = applyDegraded(state, "timeout");

    const conflictEv: DecodedEvent = {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 5,
      eventName: "question_terminal",
      questionId: "q_001",
    };
    state = applyV2Event(state, conflictEv);
    expect(state.questions["q_001"].terminalConflict).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Gap 1: draft→final same-revision conflict with normalized fingerprint (#749)
// ---------------------------------------------------------------------------

describe("draft→final same-revision conflict (Gap 1 — normalized fingerprint)", () => {
  function draftQuestion(id: string, body: string) {
    // Draft: no metadata (null, absent from question_update)
    return { id, 題目: [body], 正確解題分析: ["ans"], metadata: null };
  }

  function finalQuestion(id: string, body: string) {
    // Final (result): metadata sidecar added by publisher at emit time
    return {
      id,
      題目: [body],
      正確解題分析: ["ans"],
      metadata: { grade: 8, model: "gemini", generated_at: "2026-01-01T00:00:00Z", difficulty: "medium" },
    };
  }

  it("draft r1 → final r1 identical normalized content ⇒ no conflict, adopted as final", () => {
    let state = freshRun();
    // Draft arrives first
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 2, { content_revision: 1 }),
      { question: draftQuestion("q_001", "same content") },
    ));
    expect(state.questions["q_001"].content.receipt).toBe("draft");
    expect(state.questions["q_001"].contentConflict).toBeFalsy();

    // Result at same revision; normalized content matches draft (metadata differs but is sidecar)
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 3, { content_revision: 1 }),
      finalQuestion("q_001", "same content"),
    ));
    expect(state.questions["q_001"].contentConflict).toBeFalsy();
    expect(state.questions["q_001"].content.receipt).toBe("final");
    // Final body adopted
    const q = state.questions["q_001"].content.question as { metadata: unknown };
    expect(q.metadata).toBeTruthy(); // publisher-added metadata present in adopted final
  });

  it("draft r1 → final r1 different normalized content ⇒ conflict, draft body kept", () => {
    let state = freshRun();
    // Draft arrives first
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 2, { content_revision: 1 }),
      { question: draftQuestion("q_001", "original draft content") },
    ));

    // Result at same revision; normalized content differs (question text changed)
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 3, { content_revision: 1 }),
      finalQuestion("q_001", "DIFFERENT content — server error"),
    ));
    expect(state.questions["q_001"].contentConflict).toBe(true);
    expect(state.questions["q_001"].contentConflictReason).toBe("same_revision_different_content");
    // Draft body is retained (receipt still "draft")
    expect(state.questions["q_001"].content.receipt).toBe("draft");
    const q = state.questions["q_001"].content.question as { 題目: string[] };
    expect(q.題目[0]).toContain("original draft content");
    // processing NOT set to unknown (content conflicts don't affect X)
    expect(state.questions["q_001"].processing).not.toBe("unknown");
  });

  it("real fixture pattern: metadata=null in draft, metadata populated in final, same text ⇒ no conflict", () => {
    // Mirrors the social / natural_sciences fixture pattern confirmed by fixture analysis.
    let state = freshRun();
    const sharedBody = "台灣民主的發展過程";

    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 2, { content_revision: 1 }),
      { question: { id: "q_001", 核心問題: sharedBody, metadata: null } },
    ));

    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 3, { content_revision: 1 }),
      { id: "q_001", 核心問題: sharedBody, metadata: { grade: 8, model: "unknown", generated_at: "ts", difficulty: "medium" } },
    ));
    expect(state.questions["q_001"].contentConflict).toBeFalsy();
    expect(state.questions["q_001"].content.receipt).toBe("final");
  });
});

// ---------------------------------------------------------------------------
// Gap 2: Reason codes (not English prose)
// ---------------------------------------------------------------------------

describe("conflict reason codes (Gap 2)", () => {
  it("seq_data terminal conflict reason is 'seq_data'", () => {
    let state = freshRun();
    state = applyV2Event(state, {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 5,
      eventName: "question_terminal",
      questionId: "q_001",
    });
    expect(state.questions["q_001"].terminalConflictReason).toBe("seq_data");
    expect(state.questions["q_001"].review.reason).toBe("seq_data");
  });

  it("seq_data content conflict reason is 'seq_data'", () => {
    let state = freshRun();
    state = applyV2Event(state, {
      kind: "conflict",
      conflictType: "seq_data",
      seq: 5,
      eventName: "result",
      questionId: "q_001",
    });
    expect(state.questions["q_001"].contentConflictReason).toBe("seq_data");
  });

  it("identity mismatch reason is 'identity_mismatch'", () => {
    let state = freshRun();
    state = applyV2Event(state, makeEvent("result",
      ctx("q_001", 2, { content_revision: 1 }),
      { id: "q_999", 題目: ["x"] },
    ));
    expect(state.questions["q_001"].contentConflictReason).toBe("identity_mismatch");
  });

  it("question_update identity mismatch reason is 'identity_mismatch'", () => {
    let state = freshRun();
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 2, { content_revision: 1 }),
      { question: { id: "q_999", 題目: ["x"] } },
    ));
    expect(state.questions["q_001"].contentConflictReason).toBe("identity_mismatch");
  });

  it("same-revision-different-content reason is 'same_revision_different_content'", () => {
    let state = freshRun();
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 2, { content_revision: 1 }),
      { question: { id: "q_001", 題目: ["version A"] } },
    ));
    state = applyV2Event(state, makeEvent("question_update",
      ctx("q_001", 3, { content_revision: 1 }),
      { question: { id: "q_001", 題目: ["version B"] } },
    ));
    expect(state.questions["q_001"].contentConflictReason).toBe("same_revision_different_content");
  });

  it("terminal_invalid reason is 'terminal_invalid'", () => {
    let state = freshRun();
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2),
      { termination_reason: "bad" }, // invalid
    ));
    expect(state.questions["q_001"].terminalConflictReason).toBe("terminal_invalid");
    expect(state.questions["q_001"].review.reason).toBe("terminal_invalid");
  });

  it("terminal_contradiction reason is 'terminal_contradiction'", () => {
    let state = freshRun();
    // First terminal (normal)
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2),
      validTerminal("q_001"),
    ));
    expect(state.questions["q_001"].processing).toBe("ended");

    // Second, contradictory terminal with different outcome
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3),
      { ...noFinalTerminal() },
    ));
    expect(state.questions["q_001"].terminalConflictReason).toBe("terminal_contradiction");
  });

  it("review_contradiction reason is 'review_contradiction'", () => {
    let state = freshRun();
    const first = validTerminal("q_001");
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2), first));
    // Second terminal with same outcome but different review
    const reviewConflictTerminal = {
      ...validTerminal("q_001"),
      review: { status: "failed" as const, content_revision: 1 },
    };
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), reviewConflictTerminal));
    expect(state.questions["q_001"].reviewConflict).toBe(true);
    expect(state.questions["q_001"].review.reason).toBe("review_contradiction");
  });
});

// ---------------------------------------------------------------------------
// S2 (#749, #897): sameTerminalOutcome order-independent slot comparison
// expected/delivered/missing arrays are compared as multisets (order-insensitive).
// A resend with the same slots in a different array order must NOT be flagged as
// a conflict.  A genuinely different outcome (different slot, missing slot, extra
// duplicate) must still be detected as terminal_contradiction.
// ---------------------------------------------------------------------------

describe("sameTerminalOutcome: order-independent slot comparison (S2)", () => {
  const slotA = {
    kind: "subquestion" as const,
    question_id: "q_001",
    subquestion_id: "q_001-sq001",
    subquestion_index: 0,
  };
  const slotB = {
    kind: "subquestion" as const,
    question_id: "q_001",
    subquestion_id: "q_001-sq002",
    subquestion_index: 1,
  };

  function terminalWith(
    missing: typeof slotA[],
    delivered: typeof slotA[],
    expected: typeof slotA[],
  ) {
    return {
      termination_reason: "normal" as const,
      has_final: true,
      final_revision: 1,
      delivery_status: "partial" as const,
      expected,
      delivered,
      missing,
      review: { status: "passed", content_revision: 1 },
    };
  }

  it("identical resend (same slot order) is NOT flagged as terminal_contradiction", () => {
    let state = freshRun();
    const first = terminalWith([slotA], [slotB], [slotA, slotB]);
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2), first));
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(state.questions["q_001"].terminalConflict).toBeFalsy();

    // Resend byte-identical terminal
    const resend = terminalWith([slotA], [slotB], [slotA, slotB]);
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), resend));
    // Idempotent resend → no conflict, stays ended
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(state.questions["q_001"].terminalConflict).toBeFalsy();
  });

  it("reordered slots in resend are NOT flagged as terminal_contradiction", () => {
    // #897: consumers must treat slot arrays as multisets — order is non-normative.
    let state = freshRun();
    const first = terminalWith([slotA], [slotB], [slotA, slotB]);
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2), first));
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(state.questions["q_001"].terminalConflict).toBeFalsy();

    // Resend with same slots but reversed array order in expected (slotB, slotA)
    const reordered = terminalWith([slotA], [slotB], [slotB, slotA]);
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), reordered));
    // Same multiset → no conflict, processing stays ended
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(state.questions["q_001"].terminalConflict).toBeFalsy();
    expect(state.questions["q_001"].reviewConflict).toBeFalsy();
  });

  it("reordered slots + different review → reviewConflict only (not terminalConflict)", () => {
    // sameTerminalOutcome returns true (same slots, different order) so the
    // review-only path fires, setting reviewConflict but not terminalConflict.
    let state = freshRun();
    const first = terminalWith([slotA], [slotB], [slotA, slotB]);
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2), first));
    expect(state.questions["q_001"].processing).toBe("ended");

    // Resend: slots reordered AND review changed to "failed"
    const reorderedDifferentReview = {
      ...terminalWith([slotA], [slotB], [slotB, slotA]),
      review: { status: "failed" as const, content_revision: 1 },
    };
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), reorderedDifferentReview));
    // Outcome is the same (multiset match) but review differs → reviewConflict
    expect(state.questions["q_001"].processing).toBe("ended");
    expect(state.questions["q_001"].terminalConflict).toBeFalsy();
    expect(state.questions["q_001"].reviewConflict).toBe(true);
  });

  it("different missing set triggers terminal_contradiction", () => {
    let state = freshRun();
    const first = terminalWith([slotA], [slotB], [slotA, slotB]);
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 2), first));

    // Second terminal with slotB missing instead of slotA
    const different = terminalWith([slotB], [slotA], [slotA, slotB]);
    state = applyV2Event(state, makeEvent("question_terminal",
      ctx("q_001", 3), different));
    expect(state.questions["q_001"].processing).toBe("unknown");
    expect(state.questions["q_001"].terminalConflictReason).toBe("terminal_contradiction");
  });
});
