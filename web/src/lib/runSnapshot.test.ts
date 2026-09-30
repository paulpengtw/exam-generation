import { describe, expect, it } from "vitest";

import {
  applyRunSnapshot,
  deriveDisplay,
  evidenceFromAccepted,
  isTerminalRunStatus,
  parseAcceptedRun,
  parseRunSnapshot,
  snapshotEnded,
  stageEventsFromSnapshot,
  type RunSnapshot,
  type RunSnapshotQuestion,
} from "./runSnapshot";
import { applyPollReadFailed, applyStreamLost, applyV2Event, selectEndedCount, selectFinalReceivedCount, selectGenerationSteps } from "./generationEvidence";
import { createGenerationStreamDecoder } from "./generationStream";

function terminal(revision: number | null = 1, reason: "normal" | "failed" = "normal") {
  return revision === null
    ? {
      termination_reason: reason,
      has_final: false,
      final_revision: null,
      delivery_status: "none",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "unknown" },
    }
    : {
      termination_reason: reason,
      has_final: true,
      final_revision: revision,
      delivery_status: "complete",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "passed", content_revision: revision },
    };
}

function question(id: string, extra: Partial<RunSnapshotQuestion> = {}): RunSnapshotQuestion {
  const index = Number(id.split("-")[1]) - 1;
  return {
    index,
    question_id: id,
    processing: "waiting",
    current_step: null,
    termination_reason: null,
    terminal: null,
    error: null,
    result: null,
    ...extra,
  };
}

function endedQuestion(id: string): RunSnapshotQuestion {
  return question(id, {
    processing: "ended",
    termination_reason: "normal",
    terminal: terminal(1),
    result: {
      record_id: `rec-${id}`,
      question: {
        id,
        情境: [],
        題型種類: "single",
        題型: "multiple_choice",
        題目: [`text ${id}`],
        正確解題分析: ["a"],
      },
      verification_trail: [{
        code: "verification_trail",
        kind: "initial",
        question_id: id,
        timestamp: "2026-01-01T00:00:00+00:00",
        snapshot: {},
      }],
      figure_policy_trail: [],
      reference_example_record: { disabled: false, entries: [] },
    },
  });
}

function snapshot(questions: RunSnapshotQuestion[], extra: Partial<RunSnapshot> = {}): RunSnapshot {
  return {
    run_id: "run-1",
    status: "running",
    subject: "math",
    total: questions.length,
    started_at: null,
    completed_at: null,
    error: null,
    questions,
    ...extra,
  };
}

describe("parseAcceptedRun", () => {
  const body = {
    run_id: "run-1",
    protocol_version: 3,
    total: 2,
    questions: [
      { index: 0, question_id: "q-1" },
      { index: 1, question_id: "q-2" },
    ],
  };

  it("accepts a consistent 202 body", () => {
    const parsed = parseAcceptedRun(body);
    expect(parsed.ok).toBe(true);
    if (parsed.ok) {
      expect(parsed.run.total).toBe(2);
      const evidence = evidenceFromAccepted(parsed.run);
      expect(evidence.order).toEqual(["q-1", "q-2"]);
      expect(evidence.questions["q-1"].processing).toBe("waiting");
    }
  });

  it("rejects another protocol version", () => {
    expect(parseAcceptedRun({ ...body, protocol_version: 2 })).toEqual({
      ok: false,
      reason: "unknown_protocol",
    });
  });

  it.each([
    ["total mismatch", { ...body, total: 3 }],
    ["duplicate ids", { ...body, questions: [body.questions[0], body.questions[0]] }],
    ["missing run id", { ...body, run_id: "" }],
    ["not an object", null],
  ])("rejects an invalid manifest: %s", (_name, value) => {
    expect(parseAcceptedRun(value)).toEqual({ ok: false, reason: "invalid_manifest" });
  });
});

describe("parseRunSnapshot", () => {
  it("returns null for a body that is not a snapshot", () => {
    expect(parseRunSnapshot({ detail: "x" })).toBeNull();
    expect(parseRunSnapshot(null)).toBeNull();
  });

  it("normalises missing optional fields", () => {
    const parsed = parseRunSnapshot({
      run_id: "run-1",
      status: "queued",
      questions: [{ index: 0, question_id: "q-1" }],
    });
    expect(parsed?.questions[0]).toMatchObject({
      processing: "waiting",
      current_step: null,
      termination_reason: null,
      terminal: null,
      result: null,
    });
  });
});

describe("applyRunSnapshot", () => {
  it("builds evidence from the manifest when there is none (page reopened)", () => {
    const evidence = applyRunSnapshot(null, snapshot([question("q-1"), question("q-2")]));
    expect(evidence.runId).toBe("run-1");
    expect(evidence.order).toEqual(["q-1", "q-2"]);
    expect(selectEndedCount(evidence)).toBe(0);
  });

  it("shows running processing and the persisted step as an active operation", () => {
    const evidence = applyRunSnapshot(null, snapshot([
      question("q-1", { processing: "running", current_step: "verify" }),
      question("q-2"),
    ]));
    expect(evidence.questions["q-1"].processing).toBe("running");
    expect(evidence.questions["q-2"].processing).toBe("waiting");
    expect(selectGenerationSteps(evidence.questions["q-1"])).toEqual([
      { step: "verify", active: 1, total: 1 },
    ]);
  });

  it("moves the active operation when the step advances", () => {
    const first = applyRunSnapshot(null, snapshot([
      question("q-1", { processing: "running", current_step: "text" }),
    ]));
    const second = applyRunSnapshot(first, snapshot([
      question("q-1", { processing: "running", current_step: "image" }),
    ]));
    const steps = selectGenerationSteps(second.questions["q-1"]);
    expect(steps).toContainEqual({ step: "text", active: 0, total: 1 });
    expect(steps).toContainEqual({ step: "image", active: 1, total: 1 });
  });

  it("counts an ended question and its final result once, however often it is applied", () => {
    const snap = snapshot([endedQuestion("q-1"), question("q-2", { processing: "running" })]);
    const first = applyRunSnapshot(null, snap);
    expect(selectEndedCount(first)).toBe(1);
    expect(selectFinalReceivedCount(first)).toBe(1);
    const again = applyRunSnapshot(first, snap);
    const third = applyRunSnapshot(again, snap);
    expect(again).toBe(first);
    expect(third).toBe(first);
    expect(selectEndedCount(third)).toBe(1);
    expect(selectFinalReceivedCount(third)).toBe(1);
    expect(third.questions["q-1"].terminalConflict).toBe(false);
    expect(third.questions["q-1"].contentConflict).toBe(false);
  });

  it("is idempotent for a running snapshot too", () => {
    const snap = snapshot([question("q-1", { processing: "running", current_step: "text" })]);
    const first = applyRunSnapshot(null, snap);
    expect(applyRunSnapshot(first, snap)).toBe(first);
  });

  it("ends the active step operation when the question ends", () => {
    const running = applyRunSnapshot(null, snapshot([
      question("q-1", { processing: "running", current_step: "verify" }),
    ]));
    const ended = applyRunSnapshot(running, snapshot([endedQuestion("q-1")]));
    expect(selectGenerationSteps(ended.questions["q-1"])).toEqual([
      { step: "verify", active: 0, total: 1 },
    ]);
    expect(ended.questions["q-1"].processing).toBe("ended");
  });

  it("carries the persisted trails onto the question evidence", () => {
    const evidence = applyRunSnapshot(null, snapshot([endedQuestion("q-1")]));
    expect(evidence.questions["q-1"].trail).toHaveLength(1);
    expect(evidence.questions["q-1"].referenceExampleRecord).toEqual({ disabled: false, entries: [] });
  });

  it("closes the run once every question has a termination reason", () => {
    const partial = applyRunSnapshot(null, snapshot([endedQuestion("q-1"), question("q-2")]));
    expect(partial.closed).toBe(false);
    const done = applyRunSnapshot(partial, snapshot([endedQuestion("q-1"), endedQuestion("q-2")], {
      status: "completed",
    }));
    expect(done.closed).toBe(true);
    expect(selectEndedCount(done)).toBe(2);
    expect(applyRunSnapshot(done, snapshot([endedQuestion("q-1"), endedQuestion("q-2")]))).toBe(done);
  });

  it("records a failed question without a final", () => {
    const failed = question("q-1", {
      processing: "ended",
      termination_reason: "failed",
      terminal: terminal(null, "failed"),
    });
    const evidence = applyRunSnapshot(null, snapshot([failed]));
    expect(evidence.questions["q-1"].terminal?.termination_reason).toBe("failed");
    expect(selectFinalReceivedCount(evidence)).toBe(0);
    expect(evidence.closed).toBe(true);
  });

  it("fills a result that appears in a later snapshot after the terminal", () => {
    const withoutResult = { ...endedQuestion("q-1"), result: null };
    const first = applyRunSnapshot(null, snapshot([withoutResult, question("q-2")]));
    expect(first.questions["q-1"].finalPending).toBe(true);
    const second = applyRunSnapshot(first, snapshot([endedQuestion("q-1"), question("q-2")]));
    expect(second.questions["q-1"].finalPending).toBe(false);
    expect(selectFinalReceivedCount(second)).toBe(1);
  });

  it("rebuilds from the manifest when the polled run differs from the held one", () => {
    const first = applyRunSnapshot(null, snapshot([endedQuestion("q-1")]));
    const other = applyRunSnapshot(first, snapshot([question("q-1")], { run_id: "run-2" }));
    expect(other.runId).toBe("run-2");
    expect(selectEndedCount(other)).toBe(0);
  });
});

describe("projections", () => {
  it("derives ordered display results and finals from evidence", () => {
    const evidence = applyRunSnapshot(null, snapshot([
      question("q-1", { processing: "running" }),
      endedQuestion("q-2"),
    ]));
    const { displayResults, results } = deriveDisplay(evidence);
    expect(displayResults).toHaveLength(1);
    expect(displayResults[0]).toMatchObject({
      index: 1,
      stableId: "q-2",
      isFinal: true,
      phase: "verified",
      contentRevision: 1,
    });
    expect(results).toHaveLength(1);
  });

  it("emits one running stage event per unfinished question with a step, rebuilt each time", () => {
    const snap = snapshot([
      question("q-1", { processing: "running", current_step: "text" }),
      question("q-2", { processing: "running", current_step: "verify" }),
      endedQuestion("q-3"),
      question("q-4"),
    ]);
    const events = stageEventsFromSnapshot(snap);
    expect(events.map((e) => [e.agent, e.stage, e.status])).toEqual([
      ["generator", "llm_generate", "start"],
      ["verifier", "verify", "start"],
    ]);
    expect(stageEventsFromSnapshot(snap)).toEqual(events);
  });

  it("recognises ended runs and terminal statuses", () => {
    expect(snapshotEnded(snapshot([endedQuestion("q-1")]))).toBe(true);
    expect(snapshotEnded(snapshot([endedQuestion("q-1"), question("q-2")]))).toBe(false);
    expect(snapshotEnded(snapshot([]))).toBe(false);
    expect(isTerminalRunStatus("completed")).toBe(true);
    expect(isTerminalRunStatus("failed")).toBe(true);
    expect(isTerminalRunStatus("cancelled")).toBe(true);
    expect(isTerminalRunStatus("running")).toBe(false);
    expect(isTerminalRunStatus("queued")).toBe(false);
  });
});

describe("spec scenarios", () => {
  it("mixed outcomes — selectEndedCount and selectFinalReceivedCount", () => {
    // Spec scenario "Mixed outcomes in four questions":
    // A (q-1): complete passed final + terminal → endedCount+1, finalReceivedCount+1
    // B (q-2): PARTIAL failed-review final + terminal (delivery_status "partial", non-empty missing)
    //          → endedCount+1, finalReceivedCount+1 (has_final=true)
    // C (q-3): failed no-final terminal + draft (has_final=false, persisted draft result)
    //          → endedCount+1, C's draft does NOT increase finalReceivedCount
    // D (q-4): final WITHOUT terminal (result in snapshot, no terminal yet)
    //          → NOT counted as ended; persisted result counts toward finalReceivedCount
    //
    // Expected: ended=3 (A,B,C) and finalReceived=3 (A,B,D)
    // D stays processing-unknown until persisted state establishes its outcome.
    const imageSlot = { kind: "image" as const, question_id: "q-2", subquestion_id: null };
    const draftResult = {
      record_id: "rec-q-3-draft",
      question: {
        id: "q-3",
        情境: [],
        題型種類: "single",
        題型: "multiple_choice",
        題目: ["draft text q-3"],
        正確解題分析: ["a"],
      },
      verification_trail: [],
      figure_policy_trail: [],
      reference_example_record: { disabled: false, entries: [] },
    };
    const snap = snapshot([
      // A: complete passed final and terminal
      endedQuestion("q-1"),
      // B: partial failed-review final + terminal
      {
        ...question("q-2"),
        processing: "ended",
        termination_reason: "normal",
        terminal: {
          termination_reason: "normal",
          has_final: true,
          final_revision: 1,
          delivery_status: "partial",
          expected: [imageSlot],
          delivered: [],
          missing: [imageSlot],
          review: { status: "failed", content_revision: 1 },
        },
        result: endedQuestion("q-2").result,
      },
      // C: failed no-final terminal (has_final=false) + a draft result
      {
        ...question("q-3"),
        processing: "ended",
        termination_reason: "failed",
        terminal: terminal(null, "failed"),
        result: draftResult,
      },
      // D: persisted result but no terminal yet
      { ...question("q-4"), result: endedQuestion("q-4").result },
    ]);
    const state = applyRunSnapshot(null, snap);
    // X=3: A, B, C each have a terminal; D has no terminal → not ended
    expect(selectEndedCount(state)).toBe(3);
    // Y=3: A, B (has_final=true via terminal), D (persisted result read from state)
    // C's no-final terminal means C does NOT count toward Y despite having a draft
    expect(selectFinalReceivedCount(state)).toBe(3);
    // C has a failed no-final terminal; has_final=false so the result is NOT
    // promoted to a final receipt.  The draft exists in the DB but the
    // terminal declares "no final" so the frontend leaves the receipt at "none".
    // This is what prevents C from raising Y.
    expect(state.questions["q-3"].content.receipt).toBe("none");
    // D is not ended (no terminal)
    expect(state.questions["q-4"].terminal).toBeNull();
    expect(state.questions["q-4"].processing).not.toBe("ended");
    // D has a receipt of "final" from the persisted result
    expect(state.questions["q-4"].content.receipt).toBe("final");
  });

  it("D persisted final applied; later snapshot delivers D terminal with same final_revision — no conflict, counts unchanged", () => {
    // D receives a persisted final result from the initial snapshot (no terminal yet).
    // A subsequent poll snapshot then delivers D's terminal with final_revision 1.
    // applyRunSnapshot uses nominalRevision=1 for the initial result, so final_revision=1
    // matches — no conflict.  selectEndedCount rises, selectFinalReceivedCount stays.
    const dFinalResult = {
      record_id: "rec-q-4-final",
      question: {
        id: "q-4",
        情境: [],
        題型種類: "single",
        題型: "multiple_choice",
        題目: ["final text q-4"],
        正確解題分析: ["a"],
      },
      verification_trail: [],
      figure_policy_trail: [],
      reference_example_record: { disabled: false, entries: [] },
    };
    // Initial snapshot: D has a persisted result but no terminal yet.
    const snap1 = snapshot([
      endedQuestion("q-1"),
      { ...question("q-4"), result: { ...dFinalResult } },
    ]);
    const state1 = applyRunSnapshot(null, snap1);
    expect(selectEndedCount(state1)).toBe(1); // only A (q-1) ended
    expect(selectFinalReceivedCount(state1)).toBe(2); // A + D (persisted final)
    expect(state1.questions["q-4"].processing).not.toBe("ended");
    expect(state1.questions["q-4"].terminal).toBeNull();

    // Second snapshot: D now has a terminal with final_revision 1.
    // The nominalRevision used by snap1 is also 1 → no revision conflict.
    const dTerminal = {
      termination_reason: "normal",
      has_final: true,
      final_revision: 1,          // matches nominalRevision=1 from snap1
      delivery_status: "complete",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "passed", content_revision: 1 },
    };
    const snap2 = snapshot([
      endedQuestion("q-1"),
      {
        ...question("q-4"),
        processing: "ended",
        termination_reason: "normal",
        terminal: dTerminal,
        result: { ...dFinalResult },
      },
    ]);
    const state2 = applyRunSnapshot(state1, snap2);
    // D is now ended — X increases by 1
    expect(selectEndedCount(state2)).toBe(2);
    // Y is unchanged: D was already counted toward finalReceived in snap1
    expect(selectFinalReceivedCount(state2)).toBe(2);
    expect(state2.questions["q-4"].processing).toBe("ended");
    // No terminal conflict: final_revision 1 matches nominalRevision 1
    expect(state2.questions["q-4"].terminalConflict).toBeFalsy();
  });

  it("D persisted final applied (nominalRevision=1); later snapshot delivers D terminal with final_revision=3 — no conflict, D ended, counts correct", () => {
    // Regression: when the initial snapshot stored the result under nominalRevision=1
    // and the terminal arrives with final_revision=3, the terminal handler used to
    // see content.revision(1) !== final_revision(3) and raise terminalConflict.
    // The fix re-applies the result at the correct final_revision before applying
    // the terminal.
    const dFinalResult = {
      record_id: "rec-q-4-final-r3",
      question: {
        id: "q-4",
        情境: [],
        題型種類: "single",
        題型: "multiple_choice",
        題目: ["final text q-4 r3"],
        正確解題分析: ["a"],
      },
      verification_trail: [],
      figure_policy_trail: [],
      reference_example_record: { disabled: false, entries: [] },
    };
    // Initial snapshot: D has a persisted result but no terminal yet.
    const snap1 = snapshot([
      endedQuestion("q-1"),
      { ...question("q-4"), result: { ...dFinalResult } },
    ]);
    const state1 = applyRunSnapshot(null, snap1);
    expect(selectEndedCount(state1)).toBe(1); // only A (q-1) ended
    expect(selectFinalReceivedCount(state1)).toBe(2); // A + D (persisted final)
    expect(state1.questions["q-4"].processing).not.toBe("ended");
    expect(state1.questions["q-4"].terminal).toBeNull();

    // Second snapshot: D now has a terminal with final_revision=3 (mismatch with nominalRevision=1).
    const dTerminal = {
      termination_reason: "normal",
      has_final: true,
      final_revision: 3,          // does NOT match nominalRevision=1
      delivery_status: "complete",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "passed", content_revision: 3 },
    };
    const snap2 = snapshot([
      endedQuestion("q-1"),
      {
        ...question("q-4"),
        processing: "ended",
        termination_reason: "normal",
        terminal: dTerminal,
        result: { ...dFinalResult },
      },
    ]);
    const state2 = applyRunSnapshot(state1, snap2);
    // D is now ended — X increases by 1
    expect(selectEndedCount(state2)).toBe(2);
    // Y is unchanged: D was already counted toward finalReceived in snap1
    expect(selectFinalReceivedCount(state2)).toBe(2);
    expect(state2.questions["q-4"].processing).toBe("ended");
    // No terminal conflict: fix re-applies result at final_revision=3 before terminal
    expect(state2.questions["q-4"].terminalConflict).toBeFalsy();
  });

  it("idempotent: applying same snapshot twice gives same counts", () => {
    const snap = snapshot([
      endedQuestion("q-1"),
      question("q-2", { processing: "running" }),
    ]);
    const once = applyRunSnapshot(null, snap);
    const twice = applyRunSnapshot(once, snap);
    expect(selectEndedCount(twice)).toBe(selectEndedCount(once));
    expect(selectFinalReceivedCount(twice)).toBe(selectFinalReceivedCount(once));
  });

  it("persisted fallback: later snapshot with terminal supersedes earlier running state", () => {
    const snap1 = snapshot([question("q-1", { processing: "running" })]);
    const snap2 = snapshot([endedQuestion("q-1")]);
    const state1 = applyRunSnapshot(null, snap1);
    const state2 = applyRunSnapshot(state1, snap2);
    expect(selectEndedCount(state2)).toBe(1);
    expect(selectFinalReceivedCount(state2)).toBe(1);
  });

  it("counts are read after returning", () => {
    // Spec scenario "Counts are read after returning":
    // WHEN the owner reopens a run whose persisted state records three ended questions of four
    // THEN the page reads 已結束 3/4 題 without any live events
    // Use total=4 with 3 ended questions (per spec wording "three ended of four").
    const snap = snapshot(
      [endedQuestion("q-1"), endedQuestion("q-2"), endedQuestion("q-3"), question("q-4")],
      { status: "running", total: 4 },
    );
    const state = applyRunSnapshot(null, snap);
    expect(state.total).toBe(4);
    expect(selectEndedCount(state)).toBe(3);
    expect(selectFinalReceivedCount(state)).toBe(3);
    // q-4 is still waiting (not ended)
    expect(state.questions["q-4"].processing).toBe("waiting");
  });

  it("connection ends during generation", () => {
    // Spec scenario "Connection ends during generation":
    // A receives a terminal via live stream; B receives a draft via live stream
    // and is running at its current_step. The stream connection is LOST
    // (applyStreamLost, NOT closeRun — the run is still executing on the server).
    //
    // After stream loss: A retains its "ended" conclusion; B stays "running" at
    // its current processing state (NOT "unknown"). Unknown is reserved for
    // applyPollReadFailed (persisted-state unreadable). Live-only activity
    // indicators are cleared. The run is NOT closed (polling continues).
    let state = applyRunSnapshot(null, snapshot([
      question("q-1"),
      question("q-2", { processing: "running", current_step: "subquestions" }),
    ]));

    // A: terminal via live stream
    state = applyV2Event(state, {
      kind: "v2",
      event: {
        name: "question_terminal",
        context: { question_id: "q-1" },
        payload: terminal(1),
      },
    });

    // B: draft via live stream (question_update)
    state = applyV2Event(state, {
      kind: "v2",
      event: {
        name: "question_update",
        context: { question_id: "q-2", content_revision: 1 },
        payload: { index: 1, phase: "draft", question: { id: "q-2" } },
      },
    });
    expect(state.questions["q-2"].content.receipt).toBe("draft");

    // Stream connection lost — NOT closeRun
    state = applyStreamLost(state);

    // A: terminal established → retains "ended"
    expect(state.questions["q-1"].processing).toBe("ended");
    // B: stream lost → stays "running" (NOT "unknown"; unknown = applyPollReadFailed)
    expect(state.questions["q-2"].processing).toBe("running");
    expect(selectEndedCount(state)).toBe(1);
    // Stream loss does NOT mark the run as closed (run still executing on server)
    expect(state.closed).toBe(false);
    // Live-only activity indicators are cleared
    expect(state.questions["q-2"].activity).toEqual({ operations: {}, calls: {} });
  });

  it("stale started event rejected — decoder ignores started with wrong run id", () => {
    // Spec scenario "A stale connection delivers started":
    // WHEN a previous request's callback delivers started or later events after a new submission
    // THEN it does not change the new run, cards, activity or counts
    //
    // A started event whose run_id differs from the decoder's accepted run_id
    // must be ignored so the new run's evidence state is never corrupted.
    const decoder = createGenerationStreamDecoder();

    // Send the real started for run-1 (the new run)
    const realStarted = JSON.stringify({
      context: { run_id: "run-1", event_seq: 1 },
      payload: {
        protocol_version: 2,
        run_id: "run-1",
        total: 2,
        questions: [
          { index: 0, question_id: "q-1" },
          { index: 1, question_id: "q-2" },
        ],
      },
    });
    const results1 = decoder.decode("started", realStarted);
    expect(results1[0].kind).toBe("v2");
    expect(decoder.mode).toBe("v2");
    expect(decoder.run?.runId).toBe("run-1");

    // Stale started from a previous request arrives with a different run_id
    const staleStarted = JSON.stringify({
      context: { run_id: "run-old", event_seq: 99 },
      payload: {
        protocol_version: 2,
        run_id: "run-old",
        total: 1,
        questions: [{ index: 0, question_id: "q-stale" }],
      },
    });
    const results2 = decoder.decode("started", staleStarted);
    // Decoder is in v2 mode — wrong run_id is ignored
    expect(results2[0]).toMatchObject({ kind: "ignore", reason: "wrong_run" });
    // Decoder still tracks run-1, not the stale run
    expect(decoder.run?.runId).toBe("run-1");

    // A follow-on event for run-old is also ignored
    const staleEvent = JSON.stringify({
      context: { run_id: "run-old", event_seq: 100 },
      payload: {},
    });
    const results3 = decoder.decode("question_update", staleEvent);
    expect(results3[0]).toMatchObject({ kind: "ignore", reason: "wrong_run" });
  });

  it("persisted state unavailable — applyPollReadFailed marks unresolved questions unknown", () => {
    // Spec scenario "Persisted state is unavailable":
    // WHEN the stream closes and reading persisted run state fails
    // THEN received contents remain, unestablished outcomes are shown unknown,
    //   and the client retries reading without resubmitting generation
    let state = applyRunSnapshot(null, snapshot([
      endedQuestion("q-1"),
      question("q-2", { processing: "running", current_step: "text" }),
      question("q-3"),
    ]));
    // q-1 has a terminal, q-2 and q-3 are in-flight
    expect(selectEndedCount(state)).toBe(1);

    // Simulate 3+ consecutive poll failures
    state = applyPollReadFailed(state);

    // q-1 (terminal) unchanged
    expect(state.questions["q-1"].processing).toBe("ended");
    // q-2 and q-3 without terminals are now "unknown"
    expect(state.questions["q-2"].processing).toBe("unknown");
    expect(state.questions["q-3"].processing).toBe("unknown");
    // Content is retained
    expect(state.questions["q-1"].content.receipt).toBe("final");
    // selectEndedCount still counts only those with confirmed terminals
    expect(selectEndedCount(state)).toBe(1);
  });

  it("persisted state recovery — successful snapshot restores unknown questions", () => {
    // WHEN a read succeeds again after applyPollReadFailed, the unknown state
    // is replaced by persisted truth
    let state = applyRunSnapshot(null, snapshot([
      question("q-1", { processing: "running", current_step: "verify" }),
      question("q-2"),
    ]));
    state = applyPollReadFailed(state);
    expect(state.questions["q-1"].processing).toBe("unknown");
    expect(state.questions["q-2"].processing).toBe("unknown");

    // Successful snapshot arrives — restores from persisted state
    const recoverySnap = snapshot([
      question("q-1", { processing: "running", current_step: "verify" }),
      endedQuestion("q-2"),
    ]);
    state = applyRunSnapshot(state, recoverySnap);
    // q-1 restored to "running" from persisted state
    expect(state.questions["q-1"].processing).toBe("running");
    // q-2 is now ended (terminal arrived in persistence)
    expect(state.questions["q-2"].processing).toBe("ended");
    expect(selectEndedCount(state)).toBe(1);
  });
});

describe("no-double-counting — live events and snapshots", () => {
  it("live result + terminal then snapshot with same outcome: counts unchanged", () => {
    // Apply live question_terminal for q-1, then a snapshot recording the same outcome.
    // Counts must not grow on the second application.
    let state = applyRunSnapshot(null, snapshot([question("q-1"), question("q-2")]));

    // Live: result then terminal for q-1
    state = applyV2Event(state, {
      kind: "v2",
      event: {
        name: "result",
        context: { question_id: "q-1", content_revision: 1 },
        payload: endedQuestion("q-1").result!.question,
      },
    });
    state = applyV2Event(state, {
      kind: "v2",
      event: {
        name: "question_terminal",
        context: { question_id: "q-1" },
        payload: terminal(1),
      },
    });
    expect(selectEndedCount(state)).toBe(1);
    expect(selectFinalReceivedCount(state)).toBe(1);

    // Snapshot arrives recording the same q-1 outcome
    const snap = snapshot([endedQuestion("q-1"), question("q-2")]);
    state = applyRunSnapshot(state, snap);
    // Counts must not have grown
    expect(selectEndedCount(state)).toBe(1);
    expect(selectFinalReceivedCount(state)).toBe(1);
  });

  it("snapshot first then live terminal for the same question: no double-counting", () => {
    // Snapshot establishes q-1 as ended; live terminal for q-1 arrives afterward.
    const snap = snapshot([endedQuestion("q-1"), question("q-2")]);
    let state = applyRunSnapshot(null, snap);
    expect(selectEndedCount(state)).toBe(1);
    expect(selectFinalReceivedCount(state)).toBe(1);

    // Live terminal for q-1 arrives (duplicate of what the snapshot already recorded)
    state = applyV2Event(state, {
      kind: "v2",
      event: {
        name: "question_terminal",
        context: { question_id: "q-1" },
        payload: terminal(1),
      },
    });
    // Still 1, not 2
    expect(selectEndedCount(state)).toBe(1);
    expect(selectFinalReceivedCount(state)).toBe(1);
  });
});
