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
import { selectEndedCount, selectFinalReceivedCount, selectGenerationSteps } from "./generationEvidence";

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
