import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  createRunEvidence,
  applyV2Event,
  closeRun,
  selectEndedCount,
  selectFinalReceivedCount,
  selectActiveOperations,
  selectGenerationSteps,
  type RunEvidenceState,
} from "./generationEvidence";

// ---------------------------------------------------------------------------
// helpers
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

const sampleQuestion = (id: string) => ({
  id,
  情境: ["個人"],
  題型種類: "單一題",
  題型: "選擇題",
  題目: [`question ${id}`],
  正確解題分析: ["answer"],
});

// ---------------------------------------------------------------------------
// createRunEvidence
// ---------------------------------------------------------------------------

describe("createRunEvidence", () => {
  it("creates N waiting placeholders in manifest order", () => {
    const state = freshRun();
    expect(state.runId).toBe(RUN_ID);
    expect(state.total).toBe(2);
    expect(state.order).toEqual(["q_001", "q_002"]);
    expect(state.closed).toBe(false);
    expect(state.questions["q_001"].processing).toBe("waiting");
    expect(state.questions["q_001"].content.receipt).toBe("none");
    expect(state.questions["q_002"].processing).toBe("waiting");
  });
});

// ---------------------------------------------------------------------------
// applyV2Event — question_start / stage / llm_* transitions
// ---------------------------------------------------------------------------

describe("applyV2Event — processing state", () => {
  it("transitions to running on pipeline question_start", () => {
    const state = freshRun();
    const ev = makeEvent("pipeline", { run_id: RUN_ID, event_seq: 2, question_id: "q_001", index: 0 }, {
      event_name: "question_start",
    });
    const next = applyV2Event(state, ev);
    expect(next.questions["q_001"].processing).toBe("running");
  });

  it("does not change ended processing on question_start", () => {
    let state = freshRun();
    state = applyV2Event(state, makeEvent("question_terminal", { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 1 },
    }));
    // question_start after terminal should not revert to running
    const next = applyV2Event(state, makeEvent("pipeline", { run_id: RUN_ID, event_seq: 6, question_id: "q_001", index: 0 }, {
      event_name: "question_start",
    }));
    expect(next.questions["q_001"].processing).toBe("ended");
  });
});

// ---------------------------------------------------------------------------
// applyV2Event — question_update (draft content)
// ---------------------------------------------------------------------------

describe("applyV2Event — question_update", () => {
  it("stores draft content at the given revision", () => {
    const state = freshRun();
    const q = sampleQuestion("q_001");
    const ev = makeEvent("question_update", { run_id: RUN_ID, event_seq: 3, question_id: "q_001", index: 0, content_revision: 1 }, {
      index: 0, phase: "draft", question: q,
    });
    const next = applyV2Event(state, ev);
    expect(next.questions["q_001"].content.receipt).toBe("draft");
    expect(next.questions["q_001"].content.revision).toBe(1);
    expect(next.questions["q_001"].content.question).toEqual(q);
    expect(next.questions["q_001"].content.phase).toBe("draft");
  });

  it("ignores an older revision (idempotent for stale updates)", () => {
    let state = freshRun();
    const q1 = sampleQuestion("q_001");
    const q2 = { ...q1, 題目: ["updated"] };
    state = applyV2Event(state, makeEvent("question_update", { run_id: RUN_ID, event_seq: 3, question_id: "q_001", index: 0, content_revision: 2 }, {
      index: 0, phase: "draft", question: q2,
    }));
    const next = applyV2Event(state, makeEvent("question_update", { run_id: RUN_ID, event_seq: 4, question_id: "q_001", index: 0, content_revision: 1 }, {
      index: 0, phase: "draft", question: q1,
    }));
    expect(next.questions["q_001"].content.question).toEqual(q2);
    expect(next.questions["q_001"].content.revision).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// applyV2Event — result (final content)
// ---------------------------------------------------------------------------

describe("applyV2Event — result", () => {
  it("stores final content and sets receipt to final", () => {
    const state = freshRun();
    const q = sampleQuestion("q_001");
    const ev = makeEvent("result", { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0, content_revision: 1 }, q);
    const next = applyV2Event(state, ev);
    expect(next.questions["q_001"].content.receipt).toBe("final");
    expect(next.questions["q_001"].content.revision).toBe(1);
    expect(next.questions["q_001"].content.question).toEqual(q);
  });

  it("ignores a lower revision than an already-received final", () => {
    let state = freshRun();
    const qHigh = sampleQuestion("q_001");
    state = applyV2Event(state, makeEvent("result", { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0, content_revision: 3 }, qHigh));
    const qLow = { ...qHigh, 題目: ["old"] };
    const next = applyV2Event(state, makeEvent("result", { run_id: RUN_ID, event_seq: 6, question_id: "q_001", index: 0, content_revision: 1 }, qLow));
    expect(next.questions["q_001"].content.revision).toBe(3);
    expect(next.questions["q_001"].content.question).toEqual(qHigh);
  });

  it("B final before A keeps both at their manifest positions", () => {
    const state = freshRun();
    const qB = sampleQuestion("q_002");
    const s1 = applyV2Event(state, makeEvent("result", { run_id: RUN_ID, event_seq: 5, question_id: "q_002", index: 1, content_revision: 1 }, qB));
    expect(s1.questions["q_002"].content.receipt).toBe("final");
    expect(s1.questions["q_001"].content.receipt).toBe("none");
    const qA = sampleQuestion("q_001");
    const s2 = applyV2Event(s1, makeEvent("result", { run_id: RUN_ID, event_seq: 6, question_id: "q_001", index: 0, content_revision: 1 }, qA));
    expect(s2.questions["q_001"].content.receipt).toBe("final");
    expect(s2.order).toEqual(["q_001", "q_002"]);
  });
});

// ---------------------------------------------------------------------------
// applyV2Event — question_terminal
// ---------------------------------------------------------------------------

describe("applyV2Event — question_terminal", () => {
  it("sets ended processing and review from terminal", () => {
    const state = freshRun();
    const ev = makeEvent("question_terminal", { run_id: RUN_ID, event_seq: 6, question_id: "q_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 1 },
    });
    const next = applyV2Event(state, ev);
    expect(next.questions["q_001"].processing).toBe("ended");
    expect(next.questions["q_001"].review.status).toBe("passed");
    expect(next.questions["q_001"].terminal).toBeDefined();
  });

  it("sets finalPending when terminal has_final but final not yet received", () => {
    const state = freshRun();
    const ev = makeEvent("question_terminal", { run_id: RUN_ID, event_seq: 6, question_id: "q_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 1 },
    });
    const next = applyV2Event(state, ev);
    expect(next.questions["q_001"].finalPending).toBe(true);
  });

  it("keeps fixed delivered 1/3 content and the missing slot identity", () => {
    const state = freshRun();
    const partialQuestion = {
      ...sampleQuestion("q_001"),
      核心問題: "core",
      文本: "passage",
      subquestions: [
        { id: "q_001-sq001", 序號: 1, 題目: "first" },
        { id: "q_001-sq003", 序號: 3, 題目: "third" },
      ],
    };
    let next = applyV2Event(state, makeEvent(
      "question_update",
      { run_id: RUN_ID, event_seq: 7, question_id: "q_001", index: 0, content_revision: 3 },
      { phase: "draft", question: partialQuestion },
    ));
    next = applyV2Event(next, makeEvent(
      "question_terminal",
      { run_id: RUN_ID, event_seq: 8, question_id: "q_001", index: 0 },
      {
        termination_reason: "normal",
        has_final: true,
        final_revision: 3,
        delivery_status: "partial",
        expected: [
          { kind: "subquestion", question_id: "q_001", subquestion_id: "q_001-sq001", subquestion_index: 0 },
          { kind: "subquestion", question_id: "q_001", subquestion_id: "q_001-sq002", subquestion_index: 1 },
          { kind: "subquestion", question_id: "q_001", subquestion_id: "q_001-sq003", subquestion_index: 2 },
        ],
        delivered: [
          { kind: "subquestion", question_id: "q_001", subquestion_id: "q_001-sq001", subquestion_index: 0 },
          { kind: "subquestion", question_id: "q_001", subquestion_id: "q_001-sq003", subquestion_index: 2 },
        ],
        missing: [
          {
            kind: "subquestion",
            question_id: "q_001",
            subquestion_id: "q_001-sq002",
            subquestion_index: 1,
            reason: "subquestion not delivered",
          },
        ],
        review: { status: "skipped", content_revision: 3 },
      },
    ));

    expect(next.questions["q_001"].content.question?.subquestions?.map((sub) => sub.id)).toEqual([
      "q_001-sq001",
      "q_001-sq003",
    ]);
    expect(next.questions["q_001"].terminal?.missing[0].subquestion_id).toBe("q_001-sq002");
    expect(next.questions["q_001"].terminal?.missing[0].subquestion_index).toBe(1);
  });

  it("does not set finalPending when terminal matches received final revision", () => {
    let state = freshRun();
    // Receive final first
    state = applyV2Event(state, makeEvent("result", { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0, content_revision: 1 }, sampleQuestion("q_001")));
    // Then terminal
    const next = applyV2Event(state, makeEvent("question_terminal", { run_id: RUN_ID, event_seq: 6, question_id: "q_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 1 },
    }));
    expect(next.questions["q_001"].finalPending).toBe(false);
  });

  it("clears finalPending when a later result matching final_revision arrives", () => {
    let state = freshRun();
    // Terminal first
    state = applyV2Event(state, makeEvent("question_terminal", { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 2,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 2 },
    }));
    expect(state.questions["q_001"].finalPending).toBe(true);
    // Then final
    const next = applyV2Event(state, makeEvent("result", { run_id: RUN_ID, event_seq: 6, question_id: "q_001", index: 0, content_revision: 2 }, sampleQuestion("q_001")));
    expect(next.questions["q_001"].finalPending).toBe(false);
    // processing should remain ended
    expect(next.questions["q_001"].processing).toBe("ended");
  });

  it("does not double count a second terminal for the same question", () => {
    let state = freshRun();
    const terminal = makeEvent("question_terminal", { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 1 },
    });
    state = applyV2Event(state, terminal);
    const next = applyV2Event(state, terminal);
    expect(selectEndedCount(next)).toBe(1);
  });

  it("sets review.status to skipped for skipped review", () => {
    const state = freshRun();
    const ev = makeEvent("question_terminal", { run_id: RUN_ID, event_seq: 6, question_id: "q_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "skipped", content_revision: 1 },
    });
    const next = applyV2Event(state, ev);
    expect(next.questions["q_001"].review.status).toBe("skipped");
  });
});

// ---------------------------------------------------------------------------
// closeRun / done event
// ---------------------------------------------------------------------------

describe("closeRun and done event", () => {
  it("sets closed=true", () => {
    const state = freshRun();
    const closed = closeRun(state);
    expect(closed.closed).toBe(true);
  });

  it("marks questions without terminal as unknown", () => {
    const state = freshRun();
    const closed = closeRun(state);
    expect(closed.questions["q_001"].processing).toBe("unknown");
    expect(closed.questions["q_002"].processing).toBe("unknown");
  });

  it("sets finalMissing for questions that had finalPending", () => {
    let state = freshRun();
    state = applyV2Event(state, makeEvent("question_terminal", { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 1 },
    }));
    expect(state.questions["q_001"].finalPending).toBe(true);
    const closed = closeRun(state);
    expect(closed.questions["q_001"].finalMissing).toBe(true);
    expect(closed.questions["q_001"].finalPending).toBe(false);
  });

  it("done event via applyV2Event closes the run", () => {
    const state = freshRun();
    const doneEv = makeEvent("done", { run_id: RUN_ID, event_seq: 10 }, {});
    const next = applyV2Event(state, doneEv);
    expect(next.closed).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

describe("selectors", () => {
  it("endedCount counts unique questions with terminal", () => {
    let state = freshRun();
    expect(selectEndedCount(state)).toBe(0);
    state = applyV2Event(state, makeEvent("question_terminal", { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 1 },
    }));
    expect(selectEndedCount(state)).toBe(1);
  });

  it("finalReceivedCount counts questions with receipt===final", () => {
    let state = freshRun();
    expect(selectFinalReceivedCount(state)).toBe(0);
    state = applyV2Event(state, makeEvent("result", { run_id: RUN_ID, event_seq: 5, question_id: "q_001", index: 0, content_revision: 1 }, sampleQuestion("q_001")));
    expect(selectFinalReceivedCount(state)).toBe(1);
  });

  it("four-question scenario: A complete+terminal, B partial+terminal, C failed no-final+draft, D final without terminal → ended 3/4, final 3", () => {
    const run = createRunEvidence({
      runId: "R",
      total: 4,
      manifest: [
        { index: 0, questionId: "A" },
        { index: 1, questionId: "B" },
        { index: 2, questionId: "C" },
        { index: 3, questionId: "D" },
      ],
    });

    // A: complete + terminal
    let state = applyV2Event(run, makeEvent("result", { run_id: "R", event_seq: 1, question_id: "A", index: 0, content_revision: 1 }, sampleQuestion("A")));
    state = applyV2Event(state, makeEvent("question_terminal", { run_id: "R", event_seq: 2, question_id: "A", index: 0 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "complete", expected: [], delivered: [], missing: [],
      review: { status: "passed", content_revision: 1 },
    }));

    // B: partial + terminal (has final but delivery partial)
    state = applyV2Event(state, makeEvent("result", { run_id: "R", event_seq: 3, question_id: "B", index: 1, content_revision: 1 }, sampleQuestion("B")));
    state = applyV2Event(state, makeEvent("question_terminal", { run_id: "R", event_seq: 4, question_id: "B", index: 1 }, {
      termination_reason: "normal", has_final: true, final_revision: 1,
      delivery_status: "partial", expected: [{ kind: "image", question_id: "B", subquestion_id: null }],
      delivered: [], missing: [{ kind: "image", question_id: "B", subquestion_id: null }],
      review: { status: "passed", content_revision: 1 },
    }));

    // C: failed - no-final, draft only
    state = applyV2Event(state, makeEvent("question_update", { run_id: "R", event_seq: 5, question_id: "C", index: 2, content_revision: 1 }, {
      index: 2, phase: "draft", question: sampleQuestion("C"),
    }));
    state = applyV2Event(state, makeEvent("question_terminal", { run_id: "R", event_seq: 6, question_id: "C", index: 2 }, {
      termination_reason: "failed", has_final: false, final_revision: null,
      delivery_status: "none", expected: [], delivered: [], missing: [],
      review: { status: "unknown", unknown_reason: "no final content" },
    }));

    // D: final without terminal
    state = applyV2Event(state, makeEvent("result", { run_id: "R", event_seq: 7, question_id: "D", index: 3, content_revision: 1 }, sampleQuestion("D")));

    expect(selectEndedCount(state)).toBe(3); // A, B, C have terminals
    expect(selectFinalReceivedCount(state)).toBe(3); // A, B, D have receipt===final
  });
});

describe("operation-scoped live activity", () => {
  it("keeps overlapping operations active when an older operation ends", () => {
    let state = freshRun();
    let eventSeq = 20;
    const context = (operationId: string, callId?: string) => ({
      run_id: RUN_ID,
      event_seq: eventSeq++,
      question_id: "q_001",
      index: 0,
      operation_id: operationId,
      ...(callId ? { call_id: callId } : {}),
    });

    state = applyV2Event(state, makeEvent("stage", context("O1"), {
      agent: "sub_generator#1", stage: "llm_generate", status: "start",
    }));
    state = applyV2Event(state, makeEvent("stage", context("O2"), {
      agent: "sub_generator#1", stage: "llm_generate", status: "start",
    }));
    state = applyV2Event(state, makeEvent("stage", context("O1"), {
      agent: "sub_generator#1", stage: "llm_generate", status: "end",
    }));

    expect(selectActiveOperations(state.questions["q_001"])).toEqual([
      expect.objectContaining({ operationId: "O2", status: "active" }),
    ]);
    expect(state.questions["q_001"].processing).toBe("running");
    expect(selectGenerationSteps(state.questions["q_001"])).toEqual([
      expect.objectContaining({ step: "subquestions", active: 1 }),
    ]);
  });

  it("keeps same-purpose text streams separate by run/call/channel and does not infer termination", () => {
    let state = freshRun();
    const event = (name: string, operationId: string, callId: string, text?: string) =>
      makeEvent(name, {
        run_id: RUN_ID,
        event_seq: 40 + (text?.length ?? 0),
        question_id: "q_001",
        index: 0,
        operation_id: operationId,
        call_id: callId,
      }, {
        purpose: "generate",
        agent: "sub_generator#1",
        ...(text === undefined ? {} : { text }),
      });

    state = applyV2Event(state, event("llm_request", "O1", "C1"));
    state = applyV2Event(state, event("llm_request", "O2", "C2"));
    state = applyV2Event(state, event("llm_content", "O1", "C1", "old"));
    state = applyV2Event(state, event("llm_content", "O2", "C2", "new"));
    state = applyV2Event(state, event("llm_response", "O1", "C1"));

    const calls = Object.values(state.questions["q_001"].activity?.calls ?? {});
    expect(calls).toEqual(expect.arrayContaining([
      expect.objectContaining({ callId: "C1", content: "old" }),
      expect.objectContaining({ callId: "C2", content: "new" }),
    ]));
    expect(selectActiveOperations(state.questions["q_001"]).map((op) => op.operationId)).toEqual(["O1", "O2"]);
    expect(state.questions["q_001"].terminal).toBeNull();
  });

  it("marks only the superseded operation and never creates a later step from an empty active set", () => {
    let state = freshRun();
    const base = { run_id: RUN_ID, question_id: "q_001", index: 0 };
    state = applyV2Event(state, makeEvent("stage", { ...base, event_seq: 1, operation_id: "O1" }, {
      agent: "sub_generator#1", stage: "llm_generate", status: "start",
    }));
    state = applyV2Event(state, makeEvent("stage", { ...base, event_seq: 2, operation_id: "O2" }, {
      agent: "sub_generator#1", stage: "llm_generate", status: "start", supersedes_operation_id: "O1",
    }));
    state = applyV2Event(state, makeEvent("stage", { ...base, event_seq: 3, operation_id: "O1" }, {
      agent: "sub_generator#1", stage: "llm_generate", status: "end",
    }));

    expect(state.questions["q_001"].activity?.operations["O1"].status).toBe("superseded");
    expect(state.questions["q_001"].activity?.operations["O2"].status).toBe("active");
    expect(selectGenerationSteps(state.questions["q_001"])).toHaveLength(1);
  });
});

describe("social fixed-slot fixture replay", () => {
  it("keeps A's 1/3 draft, B's earlier final, and A's superseded retry activity", () => {
    const lines = readFileSync(
      resolve(__dirname, "../../../tests/fixtures/generation_v2/social_groups_interleaved.jsonl"),
      "utf-8",
    ).trim().split("\n").map((line) => JSON.parse(line) as {
      event: string;
      context: Record<string, unknown>;
      payload: Record<string, unknown>;
    });
    const started = lines[0];
    const startedPayload = started.payload;
    let state = createRunEvidence({
      runId: String(started.context.run_id),
      total: Number(startedPayload.total),
      manifest: (startedPayload.questions as Array<Record<string, unknown>>).map((question) => ({
        index: Number(question.index),
        questionId: String(question.question_id),
      })),
    });
    let bFinalBeforeA = false;

    for (const line of lines.slice(1)) {
      state = applyV2Event(state, {
        kind: "v2",
        event: { name: line.event, context: line.context, payload: line.payload },
      });
      if (
        state.questions["ss_RUN_002"]?.content.receipt === "final"
        && state.questions["ss_RUN_001"]?.content.receipt !== "final"
      ) {
        bFinalBeforeA = true;
      }
    }

    const a = state.questions["ss_RUN_001"];
    expect(bFinalBeforeA).toBe(true);
    expect(a.content.question?.subquestions?.map((sub) => sub.id)).toEqual([
      "ss_RUN_001-sq001",
      "ss_RUN_001-sq003",
    ]);
    expect(a.terminal?.delivery_status).toBe("partial");
    expect(a.terminal?.missing.map((slot) => slot.subquestion_id)).toEqual([
      "ss_RUN_001-sq002",
    ]);
    expect(Object.values(a.activity?.operations ?? {}).some(
      (operation) => operation.supersedesOperationId !== null,
    )).toBe(true);
    expect(Object.values(a.activity?.calls ?? {}).some(
      (call) => call.retryOfCallId !== null,
    )).toBe(true);
    expect(selectEndedCount(state)).toBe(2);
    expect(selectFinalReceivedCount(state)).toBe(2);
  });
});
