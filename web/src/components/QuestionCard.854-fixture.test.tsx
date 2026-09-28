/**
 * Issue #854 acceptance criterion 4: verify the activity-panel summary at three
 * moments by replaying a real server fixture.
 *
 * Fixture: tests/fixtures/generation_v2/natural_sciences_groups_interleaved.jsonl
 * Question under test: ns_RUN_001
 *
 * ns_RUN_001 operation timeline (0-based line indices from the fixture):
 *   idx  5  – OP2 starts  (agent="generator"     → step "text",        sq=none)
 *   idx 22  – OP2 ends    (step "text", ended)
 *   idx 32  – OP5 starts  (agent="sub_generator#2" → step "subquestions", sq=1)
 *   idx 49  – OP5 errors  (step "subquestions", failed)
 *   idx 50  – OP9 starts, supersedes OP5 (step "subquestions", sq=1; OP5→superseded, OP9→active)
 *   idx 53  – OP9 ends    (step "subquestions", ended)
 *
 * Moment A (concurrent sub-questions in progress, SYNTHESIZED):
 *   Real events 0-32 put OP5 (sq=1) active.  A synthetic event adds OP10-SYNTH (sq=0)
 *   starting concurrently, giving two active "subquestions" operations.
 *   Synthesis reason: the fixture serialises sub-question retries one-at-a-time;
 *   no moment in the fixture has two sub-questions active simultaneously for the same
 *   question.  The synthetic event's shape is copied verbatim from event idx=32.
 *
 * Moment B (old operation superseded then finishing late, PARTIALLY SYNTHESIZED):
 *   Real events 0-50 put OP9 active and OP5 superseded.  A synthetic event models
 *   OP5's late "end" arriving after it was already superseded — same shape as idx=49
 *   but status="end".  Per the reducer, a late end for a superseded op does NOT
 *   change its status (the `updatedOperation.status !== "superseded"` guard in
 *   applyActivity keeps it superseded), so OP9 remains the sole active operation.
 *
 * Moment C (all work finished, REAL EVENTS ONLY):
 *   Real events 0-53 leave OP2=ended, OP5=superseded, OP9=ended — no active ops.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import QuestionCard from "./QuestionCard";
import { applyV2Event, createRunEvidence } from "../lib/generationEvidence";

type FixtureLine = {
  event: string;
  context: Record<string, unknown>;
  payload: Record<string, unknown>;
};

function loadNsFixture(): FixtureLine[] {
  return readFileSync(
    resolve(__dirname, "../../../tests/fixtures/generation_v2/natural_sciences_groups_interleaved.jsonl"),
    "utf-8",
  ).trim().split("\n").map((line) => JSON.parse(line) as FixtureLine);
}

/**
 * Replay fixture lines[0..lastIndex] (inclusive) and then apply any synthetic
 * events appended after the real prefix.
 */
function replayUpTo(
  lines: FixtureLine[],
  lastIndex: number,
  synthetics: FixtureLine[] = [],
) {
  const started = lines[0];
  let state = createRunEvidence({
    runId: String(started.context.run_id),
    total: Number(started.payload.total),
    manifest: (started.payload.questions as Array<Record<string, unknown>>).map((q) => ({
      index: Number(q.index),
      questionId: String(q.question_id),
    })),
  });
  for (const line of lines.slice(1, lastIndex + 1)) {
    state = applyV2Event(state, {
      kind: "v2",
      event: { name: line.event, context: line.context, payload: line.payload },
    });
  }
  for (const syn of synthetics) {
    state = applyV2Event(state, {
      kind: "v2",
      event: { name: syn.event, context: syn.context, payload: syn.payload },
    });
  }
  return state;
}

describe(
  "QuestionCard activity-panel summary — issue #854 fixture replay" +
  " (natural_sciences_groups_interleaved.jsonl / ns_RUN_001)",
  () => {
    const lines = loadNsFixture();

    it(
      "moment A (concurrent sub-questions in progress): summary shows in-progress count, not 0" +
      " [events 0-32 real + 1 synthetic OP10-SYNTH start sq=0]",
      () => {
        // Real events 0-32: OP5 (sq=1) is active; text-step OP2 already ended.
        // Synthetic: OP10-SYNTH starts for sq=0 (same shape as event idx=32 but different op/subq).
        const synConcurrent: FixtureLine = {
          event: "stage",
          context: {
            run_id: "RUN",
            event_seq: 100,
            question_id: "ns_RUN_001",
            index: 0,
            subquestion_index: 0,
            operation_id: "RUN:operation:OP10-SYNTH",
          },
          payload: {
            type: "stage",
            agent: "sub_generator#1",
            stage: "llm_generate",
            status: "start",
            run_id: "RUN",
            operation_id: "RUN:operation:OP10-SYNTH",
            subquestion_index: 0,
            ts: 0.0,
          },
        };
        const state = replayUpTo(lines, 32, [synConcurrent]);
        const evidence = state.questions["ns_RUN_001"];

        render(<QuestionCard evidence={evidence} index={0} />);

        const summary = screen.getByTestId("question-card-activity-summary");
        // OP5 (sq=1) and OP10-SYNTH (sq=0) both active → "subquestions" step has active=2
        expect(summary).toHaveTextContent("Sub-questions");
        expect(summary).toHaveTextContent("2");
        expect(summary).not.toHaveTextContent("No steps in progress");
        // No step should show " 0" (old bug: finished "text" step would show "Text 0")
        expect(summary).not.toHaveTextContent(" 0");
      },
    );

    it(
      "moment B (old op superseded then finishing late): summary still shows only the in-progress op" +
      " [events 0-50 real + 1 synthetic late-end for OP5]",
      () => {
        // Real events 0-50: OP9 active, OP5 superseded.
        // Synthetic: late "end" event for OP5 arriving after supersede.
        // The reducer preserves "superseded" status when a late end arrives
        // (guarded by `updatedOperation.status !== "superseded"`), so OP5 stays
        // superseded and does NOT appear as active or as a 0-count entry.
        const synLateEnd: FixtureLine = {
          event: "stage",
          context: {
            run_id: "RUN",
            event_seq: 102,
            question_id: "ns_RUN_001",
            index: 0,
            subquestion_index: 1,
            operation_id: "RUN:operation:OP5",
          },
          payload: {
            type: "stage",
            agent: "sub_generator#2",
            stage: "llm_generate",
            status: "end",
            run_id: "RUN",
            operation_id: "RUN:operation:OP5",
            subquestion_index: 1,
            ts: 0.0,
          },
        };
        const state = replayUpTo(lines, 50, [synLateEnd]);
        const evidence = state.questions["ns_RUN_001"];

        render(<QuestionCard evidence={evidence} index={0} />);

        const summary = screen.getByTestId("question-card-activity-summary");
        // OP9 is still the only active operation (count=1); late finish of OP5 has no effect
        expect(summary).toHaveTextContent("Sub-questions");
        expect(summary).toHaveTextContent("1");
        expect(summary).not.toHaveTextContent("2");
        expect(summary).not.toHaveTextContent(" 0");
        expect(summary).not.toHaveTextContent("No steps in progress");
      },
    );

    it(
      "moment C (all work finished): summary shows neutral phrase, no 0 counts" +
      " [events 0-53 real only]",
      () => {
        // Real events 0-53: OP2=ended (text), OP5=superseded (subquestions), OP9=ended (subquestions)
        // All steps have active=0 → neutral phrase expected
        const state = replayUpTo(lines, 53);
        const evidence = state.questions["ns_RUN_001"];

        render(<QuestionCard evidence={evidence} index={0} />);

        const summary = screen.getByTestId("question-card-activity-summary");
        expect(summary).toHaveTextContent("No steps in progress");
        // Neither " 0" nor any step name with a count should appear
        expect(summary).not.toHaveTextContent(" 0");
        expect(summary).not.toHaveTextContent("Sub-questions");
        expect(summary).not.toHaveTextContent("Text");
        // Panel stays visible for traceability (expandable detail)
        expect(screen.getByTestId("question-card-activity")).toBeInTheDocument();
      },
    );
  },
);
