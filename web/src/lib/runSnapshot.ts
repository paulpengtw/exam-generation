/**
 * Persisted-state adapter for detached generation runs (issue #908).
 *
 * A 生成執行 no longer streams: the client submits, then polls
 * `GET /api/runs/{id}` and receives the run's persisted per-question state
 * (處理狀態 / 生成步驟 / 終止原因 and, once a question ends, its result). This
 * module converts one polled snapshot into the existing per-question evidence
 * model (`generationEvidence`) so cards, the 生成進度列 and the 已結束 X/N /
 * 收到最終結果 Y counts keep working unchanged.
 *
 * It is pure and idempotent: applying the same snapshot repeatedly returns the
 * very same state object (reference equality), so nothing is counted twice and
 * callers can skip re-rendering when nothing changed.
 */

import type {
  DraftPhase,
  ExamQuestion,
  FigurePolicyTrailEntry,
  GeneratedQuestion,
  ReferenceExampleRecordShape,
  StageEvent,
  VerificationTrailEntry,
} from "../hooks/useGenerate";
import {
  applyV2Event,
  createRunEvidence,
  type RunEvidenceState,
} from "./generationEvidence";

/** The detached-run protocol version this client speaks. */
export const DETACHED_RUN_PROTOCOL_VERSION = 3;

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

/** `202` body of `POST /api/generate` (受理). */
export interface AcceptedRun {
  run_id: string;
  protocol_version: number;
  total: number;
  questions: Array<{ index: number; question_id: string }>;
}

export interface RunSnapshotResult {
  record_id: string;
  question: ExamQuestion;
  verification_trail: VerificationTrailEntry[] | null;
  figure_policy_trail: FigurePolicyTrailEntry[] | null;
  reference_example_record: ReferenceExampleRecordShape | null;
}

export interface RunSnapshotQuestion {
  index: number;
  question_id: string;
  processing: string;
  current_step: string | null;
  termination_reason: string | null;
  terminal: Record<string, unknown> | null;
  error: string | null;
  result: RunSnapshotResult | null;
}

/** Body of `GET /api/runs/{id}`. */
export interface RunSnapshot {
  run_id: string;
  status: string;
  subject: string | null;
  total: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  questions: RunSnapshotQuestion[];
  live_events_available?: boolean;
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export type AcceptedRunParse =
  | { ok: true; run: AcceptedRun }
  | { ok: false; reason: "unknown_protocol" | "invalid_manifest" };

/** Validate the 202 body; a manifest that does not add up is rejected whole. */
export function parseAcceptedRun(raw: unknown): AcceptedRunParse {
  if (!isRecord(raw)) return { ok: false, reason: "invalid_manifest" };
  if (raw.protocol_version !== DETACHED_RUN_PROTOCOL_VERSION) {
    return { ok: false, reason: "unknown_protocol" };
  }
  if (typeof raw.run_id !== "string" || raw.run_id === "") {
    return { ok: false, reason: "invalid_manifest" };
  }
  const questions = raw.questions;
  if (
    !Array.isArray(questions)
    || questions.length < 1
    || raw.total !== questions.length
  ) {
    return { ok: false, reason: "invalid_manifest" };
  }
  const seen = new Set<string>();
  const parsed: AcceptedRun["questions"] = [];
  for (const item of questions) {
    if (
      !isRecord(item)
      || typeof item.question_id !== "string"
      || item.question_id === ""
      || typeof item.index !== "number"
      || !Number.isInteger(item.index)
      || item.index < 0
      || seen.has(item.question_id)
    ) {
      return { ok: false, reason: "invalid_manifest" };
    }
    seen.add(item.question_id);
    parsed.push({ index: item.index, question_id: item.question_id });
  }
  return {
    ok: true,
    run: {
      run_id: raw.run_id,
      protocol_version: DETACHED_RUN_PROTOCOL_VERSION,
      total: parsed.length,
      questions: parsed,
    },
  };
}

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseResult(value: unknown): RunSnapshotResult | null {
  if (!isRecord(value) || !isRecord(value.question)) return null;
  return {
    record_id: typeof value.record_id === "string" ? value.record_id : "",
    question: value.question as unknown as ExamQuestion,
    verification_trail: Array.isArray(value.verification_trail)
      ? (value.verification_trail as VerificationTrailEntry[])
      : null,
    figure_policy_trail: Array.isArray(value.figure_policy_trail)
      ? (value.figure_policy_trail as FigurePolicyTrailEntry[])
      : null,
    reference_example_record: isRecord(value.reference_example_record)
      ? (value.reference_example_record as unknown as ReferenceExampleRecordShape)
      : null,
  };
}

/** Parse a polled snapshot; returns null when the body is not a run snapshot. */
export function parseRunSnapshot(raw: unknown): RunSnapshot | null {
  if (!isRecord(raw) || typeof raw.run_id !== "string" || !Array.isArray(raw.questions)) {
    return null;
  }
  const questions: RunSnapshotQuestion[] = [];
  for (const item of raw.questions) {
    if (
      !isRecord(item)
      || typeof item.question_id !== "string"
      || typeof item.index !== "number"
    ) {
      return null;
    }
    questions.push({
      index: item.index,
      question_id: item.question_id,
      processing: typeof item.processing === "string" ? item.processing : "waiting",
      current_step: stringOrNull(item.current_step),
      termination_reason: stringOrNull(item.termination_reason),
      terminal: isRecord(item.terminal) ? item.terminal : null,
      error: stringOrNull(item.error),
      result: parseResult(item.result),
    });
  }
  return {
    run_id: raw.run_id,
    status: typeof raw.status === "string" ? raw.status : "running",
    subject: stringOrNull(raw.subject),
    total: typeof raw.total === "number" ? raw.total : questions.length,
    started_at: stringOrNull(raw.started_at),
    completed_at: stringOrNull(raw.completed_at),
    error: stringOrNull(raw.error),
    questions,
    live_events_available: raw.live_events_available === true ? true : undefined,
  };
}

// ---------------------------------------------------------------------------
// Run status
// ---------------------------------------------------------------------------

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

/** True when the run's own status says it will not change any more. */
export function isTerminalRunStatus(status: string): boolean {
  return TERMINAL_RUN_STATUSES.has(status);
}

/** The run has ended once every question carries a 終止原因. */
export function snapshotEnded(snapshot: RunSnapshot): boolean {
  return snapshot.questions.length > 0
    && snapshot.questions.every((q) => q.termination_reason !== null);
}

// ---------------------------------------------------------------------------
// Evidence construction
// ---------------------------------------------------------------------------

/** Evidence for a freshly accepted run: every question waiting. */
export function evidenceFromAccepted(accepted: AcceptedRun): RunEvidenceState {
  return createRunEvidence({
    runId: accepted.run_id,
    total: accepted.total,
    manifest: accepted.questions.map((q) => ({ index: q.index, questionId: q.question_id })),
  });
}

function evidenceFromSnapshotManifest(snapshot: RunSnapshot): RunEvidenceState {
  return createRunEvidence({
    runId: snapshot.run_id,
    total: snapshot.questions.length,
    manifest: snapshot.questions.map((q) => ({ index: q.index, questionId: q.question_id })),
  });
}

/**
 * How each persisted 生成步驟 shows up in the evidence model: the agent and
 * stage names are the ones the live stage events used, so the existing
 * step/phase selectors classify them identically.
 */
const STEP_STAGE: Record<string, { agent: string; stage: string }> = {
  text: { agent: "generator", stage: "llm_generate" },
  subquestions: { agent: "sub_generator#1", stage: "subquestion" },
  image: { agent: "image_agent", stage: "render_image" },
  verify: { agent: "verifier", stage: "verify" },
  correct: { agent: "corrector", stage: "correct" },
};

function operationId(questionId: string, step: string): string {
  return `persisted/${questionId}/${step}`;
}

function applyStage(
  state: RunEvidenceState,
  questionId: string,
  step: string,
  status: "start" | "end",
): RunEvidenceState {
  const { agent, stage } = STEP_STAGE[step];
  return applyV2Event(state, {
    kind: "v2",
    event: {
      name: "stage",
      context: { question_id: questionId, operation_id: operationId(questionId, step) },
      payload: { agent, stage, status },
    },
  });
}

function activePersistedSteps(state: RunEvidenceState, questionId: string): string[] {
  const prefix = `persisted/${questionId}/`;
  const steps: string[] = [];
  for (const [id, operation] of Object.entries(state.questions[questionId]?.activity?.operations ?? {})) {
    if (id.startsWith(prefix) && operation.status === "active") steps.push(id.slice(prefix.length));
  }
  return steps;
}

function endActiveSteps(
  state: RunEvidenceState,
  questionId: string,
  keep: string | null,
): RunEvidenceState {
  for (const step of activePersistedSteps(state, questionId)) {
    if (step !== keep && STEP_STAGE[step]) state = applyStage(state, questionId, step, "end");
  }
  return state;
}

function applyQuestion(
  state: RunEvidenceState,
  q: RunSnapshotQuestion,
): RunEvidenceState {
  const id = q.question_id;
  const qev = state.questions[id];
  if (!qev) return state;

  if (q.termination_reason === null) {
    if (qev.terminal !== null) return state;

    // A persisted result exists for a question that does not yet have a
    // terminal (e.g. the run is still executing, or the page was opened while
    // the terminal was in-flight).  Apply it so selectFinalReceivedCount
    // correctly counts it — "final results received live OR read from
    // persisted run state" (spec: "Batch counts are unique terminal and
    // receipt counts").
    //
    // We restore the state even when processing === "unknown" (a prior
    // applyPollReadFailed call), so the question evidence is correct once
    // the snapshot read succeeds again.
    if (q.result !== null && qev.content.receipt !== "final") {
      // Use revision 1 as a nominal sentinel when the terminal has not yet
      // arrived; the actual final_revision will be established once the
      // terminal is persisted and applied.
      const nominalRevision = 1;
      state = applyV2Event(state, {
        kind: "v2",
        event: {
          name: "result",
          context: { question_id: id, content_revision: nominalRevision },
          payload: q.result.question,
        },
      });
      const updated = state.questions[id];
      if (updated.content.receipt === "final") {
        state = {
          ...state,
          questions: {
            ...state.questions,
            [id]: {
              ...updated,
              trail: q.result.verification_trail ?? [],
              figurePolicyTrail: q.result.figure_policy_trail ?? [],
              referenceExampleRecord: q.result.reference_example_record ?? undefined,
            },
          },
        };
      }
    }

    // Restore processing from snapshot when it was previously set to "unknown"
    // by applyPollReadFailed (persisted state now readable again).
    if (qev.processing === "unknown" && q.processing !== "unknown") {
      const restored = q.processing === "running" || q.processing === "waiting"
        ? q.processing
        : "waiting";
      state = { ...state, questions: { ...state.questions, [id]: { ...state.questions[id], processing: restored } } };
    }

    if (qev.processing === "waiting" && (q.processing === "running" || q.current_step !== null)) {
      state = applyV2Event(state, {
        kind: "v2",
        event: {
          name: "pipeline",
          context: { question_id: id },
          payload: { event_name: "question_start" },
        },
      });
    }
    const step = q.current_step !== null && STEP_STAGE[q.current_step] ? q.current_step : null;
    if (step === null) return state;
    const active = activePersistedSteps(state, id);
    if (active.length === 1 && active[0] === step) return state;
    state = endActiveSteps(state, id, step);
    if (!activePersistedSteps(state, id).includes(step)) {
      state = applyStage(state, id, step, "start");
    }
    return state;
  }

  // The question has ended. A terminal, once received, is immutable server
  // side, so an already-applied one is never re-sent (idempotent, and no
  // spurious contradiction on repeated polls).
  const terminal = q.terminal;
  if (terminal === null || qev.terminalConflict) return state;

  // Result first, then terminal — the same order the live stream used, so the
  // final content is in place when the terminal is judged.
  const finalRevision = terminal.has_final === true && typeof terminal.final_revision === "number"
    ? terminal.final_revision
    : null;
  if (q.result !== null && finalRevision !== null && qev.content.receipt !== "final") {
    state = applyV2Event(state, {
      kind: "v2",
      event: {
        name: "result",
        context: { question_id: id, content_revision: finalRevision },
        payload: q.result.question,
      },
    });
    const updated = state.questions[id];
    if (updated.content.receipt === "final") {
      state = {
        ...state,
        questions: {
          ...state.questions,
          [id]: {
            ...updated,
            trail: q.result.verification_trail ?? [],
            figurePolicyTrail: q.result.figure_policy_trail ?? [],
            referenceExampleRecord: q.result.reference_example_record ?? undefined,
          },
        },
      };
    }
  }
  if (state.questions[id].terminal !== null) return state;
  state = endActiveSteps(state, id, null);
  return applyV2Event(state, {
    kind: "v2",
    event: { name: "question_terminal", context: { question_id: id }, payload: terminal },
  });
}

/**
 * Fold one polled snapshot into the evidence state.
 *
 * `prev` may be null (first snapshot, e.g. after reopening the page) or belong
 * to another run, in which case evidence is rebuilt from the snapshot's
 * manifest. When nothing changed, `prev` itself is returned.
 */
export function applyRunSnapshot(
  prev: RunEvidenceState | null,
  snapshot: RunSnapshot,
): RunEvidenceState {
  let state = prev !== null
    && prev.runId === snapshot.run_id
    && snapshot.questions.every((q) => prev.questions[q.question_id] !== undefined)
    ? prev
    : evidenceFromSnapshotManifest(snapshot);

  for (const q of snapshot.questions) state = applyQuestion(state, q);

  if (snapshotEnded(snapshot) && !state.closed) {
    state = applyV2Event(state, {
      kind: "v2",
      event: { name: "done", context: {}, payload: {} },
    });
  }
  return state;
}

// ---------------------------------------------------------------------------
// Projections
// ---------------------------------------------------------------------------

/**
 * Synthetic stage events for the 生成進度列: one running stage per unfinished
 * question that reports a 生成步驟. The list is rebuilt from each snapshot
 * (replaced, never appended), so repeated polls cannot accumulate history.
 */
export function stageEventsFromSnapshot(snapshot: RunSnapshot): StageEvent[] {
  const events: StageEvent[] = [];
  const ordered = [...snapshot.questions].sort((a, b) => a.index - b.index);
  for (const q of ordered) {
    if (q.termination_reason !== null || q.current_step === null) continue;
    const mapping = STEP_STAGE[q.current_step];
    if (!mapping) continue;
    events.push({
      type: "stage",
      agent: mapping.agent,
      stage: mapping.stage,
      status: "start",
      ts: q.index,
    });
  }
  return events;
}

/** displayResults / results in manifest order, derived from evidence alone. */
export function deriveDisplay(
  evidence: RunEvidenceState,
): { displayResults: GeneratedQuestion[]; results: ExamQuestion[] } {
  const displayResults: GeneratedQuestion[] = [];
  const results: ExamQuestion[] = [];
  for (const id of evidence.order) {
    const qev = evidence.questions[id];
    if (!qev || !qev.content.question) continue;
    const isFinal = qev.content.receipt === "final";
    displayResults.push({
      index: qev.index,
      question: qev.content.question,
      phase: (qev.content.phase ?? "draft") as DraftPhase,
      isFinal,
      stableId: qev.questionId,
      contentRevision: typeof qev.content.revision === "number" && qev.content.revision > 0
        ? qev.content.revision
        : null,
      trail: qev.trail,
      figurePolicyTrail: qev.figurePolicyTrail,
      referenceExampleRecord: qev.referenceExampleRecord ?? { disabled: false, entries: [] },
    });
    if (isFinal) results.push(qev.content.question);
  }
  return { displayResults, results };
}
