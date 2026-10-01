/**
 * Builders for detached-run wire bodies (issue #908): the 202 acceptance and
 * the `GET /api/runs/{id}` snapshot. Shared by hook, page, and adapter tests.
 */
import type { ExamQuestion } from "../hooks/useGenerate";
import type { AcceptedRun, RunSnapshot, RunSnapshotQuestion } from "../lib/runSnapshot";

export function questionIds(total: number, prefix = "q-"): string[] {
  return Array.from({ length: total }, (_, i) => `${prefix}${i + 1}`);
}

export function acceptedRun(total = 1, runId = "run-1"): AcceptedRun {
  return {
    run_id: runId,
    protocol_version: 3,
    total,
    questions: questionIds(total).map((id, index) => ({ index, question_id: id })),
  };
}

export function terminalPayload(
  revision: number | null = 1,
  reason: "normal" | "failed" | "cancelled" = "normal",
) {
  if (revision === null) {
    return {
      termination_reason: reason,
      has_final: false,
      final_revision: null,
      delivery_status: reason === "cancelled" ? "unknown" : "none",
      expected: [],
      delivered: [],
      missing: [],
      review: { status: "unknown" },
      ...(reason === "cancelled" ? { unknown_reason: "cancelled before completion" } : {}),
    };
  }
  return {
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

export function examQuestion(id: string, text = `text ${id}`): ExamQuestion {
  return {
    id,
    情境: [],
    題型種類: "單一題",
    題型: "選擇題",
    題目: [text],
    正確解題分析: ["analysis"],
  };
}

export function waitingQuestion(id: string, index?: number): RunSnapshotQuestion {
  const parsed = Number(id.split("-").at(-1)) - 1;
  index = index ?? (Number.isInteger(parsed) && parsed >= 0 ? parsed : 0);
  return {
    index,
    question_id: id,
    processing: "waiting",
    current_step: null,
    termination_reason: null,
    terminal: null,
    error: null,
    result: null,
  };
}

export function runningQuestion(id: string, step: string | null = "text"): RunSnapshotQuestion {
  return { ...waitingQuestion(id), processing: "running", current_step: step };
}

export function endedQuestion(
  id: string,
  overrides: { question?: ExamQuestion; reason?: "normal" | "failed"; revision?: number; index?: number } = {},
): RunSnapshotQuestion {
  const reason = overrides.reason ?? "normal";
  const base = waitingQuestion(id, overrides.index);
  if (reason === "failed") {
    return {
      ...base,
      processing: "ended",
      termination_reason: "failed",
      terminal: terminalPayload(null, "failed"),
      error: "boom",
    };
  }
  const revision = overrides.revision ?? 1;
  return {
    ...base,
    processing: "ended",
    termination_reason: "normal",
    terminal: terminalPayload(revision),
    result: {
      record_id: `rec-${id}`,
      question: overrides.question ?? examQuestion(id),
      verification_trail: [],
      figure_policy_trail: [],
      reference_example_record: null,
    },
  };
}

export function runSnapshot(
  questions: RunSnapshotQuestion[],
  extra: Partial<RunSnapshot> = {},
): RunSnapshot {
  const allEnded = questions.length > 0 && questions.every((q) => q.termination_reason !== null);
  return {
    run_id: "run-1",
    status: allEnded ? "completed" : "running",
    subject: "math",
    total: questions.length,
    started_at: "2026-01-01T00:00:00+00:00",
    completed_at: allEnded ? "2026-01-01T00:05:00+00:00" : null,
    error: null,
    questions,
    ...extra,
  };
}
