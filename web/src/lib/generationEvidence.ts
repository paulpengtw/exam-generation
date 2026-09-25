/**
 * F2: Per-question evidence reducer for generation stream v2.
 *
 * This module is pure (no React state) so it can be unit-tested without a DOM.
 */

import type {
  DraftPhase,
  ExamQuestion,
  FigurePolicyTrailEntry,
  ReferenceExampleRecordShape,
  VerificationTrailEntry,
} from "../hooks/useGenerate";
import type { RunManifest, DecodedEvent } from "./generationStream";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface QuestionTerminalPayload {
  termination_reason: "normal" | "failed" | "cancelled";
  has_final: boolean;
  final_revision: number | null;
  delivery_status: "complete" | "partial" | "none" | "unknown";
  expected: unknown[];
  delivered: unknown[];
  missing: unknown[];
  review: {
    status: "passed" | "failed" | "skipped" | "unknown";
    content_revision?: number | null;
    unknown_reason?: string;
  };
  unknown_reason?: string;
}

export type GenerationOperationStatus = "active" | "ended" | "failed" | "superseded";

export interface GenerationOperationEvidence {
  operationId: string;
  step: string;
  status: GenerationOperationStatus;
  agent: string | null;
  subquestionIndex: number | null;
  supersedesOperationId: string | null;
  callIds: string[];
}

export interface GenerationCallEvidence {
  runId: string;
  callId: string;
  operationId: string;
  purpose: string;
  agent: string;
  status: "active" | "ended" | "failed";
  retryOfCallId: string | null;
  thinking: string;
  content: string;
}

export interface QuestionActivity {
  operations: Record<string, GenerationOperationEvidence>;
  /** Keys are run/call pairs, never an agent or purpose. */
  calls: Record<string, GenerationCallEvidence>;
}

export interface QuestionEvidence {
  questionId: string;
  index: number;
  processing: "waiting" | "running" | "ended" | "unknown";
  content: {
    receipt: "none" | "draft" | "final";
    revision: number | null;
    question: ExamQuestion | null;
    phase: DraftPhase | null;
  };
  terminal: QuestionTerminalPayload | null;
  /** terminal says has_final but final_revision not yet received */
  finalPending: boolean;
  /** stream closed while finalPending was true */
  finalMissing: boolean;
  review: {
    status: "passed" | "failed" | "skipped" | "unknown";
    revision: number | null;
  };
  trail: VerificationTrailEntry[];
  figurePolicyTrail: FigurePolicyTrailEntry[];
  referenceExampleRecord: ReferenceExampleRecordShape | undefined;
  /** Present for v2 events; optional for legacy/history fixtures. */
  activity?: QuestionActivity;
}

export interface RunEvidenceState {
  runId: string;
  total: number;
  /** manifest order of question IDs */
  order: string[];
  questions: Record<string, QuestionEvidence>;
  closed: boolean;
}

// ---------------------------------------------------------------------------
// Constructors
// ---------------------------------------------------------------------------

function emptyQuestionEvidence(questionId: string, index: number): QuestionEvidence {
  return {
    questionId,
    index,
    processing: "waiting",
    content: { receipt: "none", revision: null, question: null, phase: null },
    terminal: null,
    finalPending: false,
    finalMissing: false,
    review: { status: "unknown", revision: null },
    trail: [],
    figurePolicyTrail: [],
    referenceExampleRecord: undefined,
    activity: { operations: {}, calls: {} },
  };
}

export function createRunEvidence(run: RunManifest): RunEvidenceState {
  const order = run.manifest.map((m) => m.questionId);
  const questions: Record<string, QuestionEvidence> = {};
  for (const m of run.manifest) {
    questions[m.questionId] = emptyQuestionEvidence(m.questionId, m.index);
  }
  return { runId: run.runId, total: run.total, order, questions, closed: false };
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

export function applyV2Event(state: RunEvidenceState, decodedEvent: DecodedEvent): RunEvidenceState {
  if (decodedEvent.kind !== "v2") return state;
  const { name, context, payload } = decodedEvent.event;
  const ctx = context as Record<string, unknown>;

  // Done event closes the run
  if (name === "done") {
    return closeRun(state);
  }

  // Question-scoped events
  const questionId = typeof ctx.question_id === "string" ? ctx.question_id : null;
  if (!questionId) return state;

  let qev = state.questions[questionId];
  if (!qev) return state; // unknown question id

  const p = payload as Record<string, unknown>;

  const activity = applyActivity(
    qev.activity ?? { operations: {}, calls: {} },
    name,
    ctx,
    p,
    state.runId,
  );
  if (activity !== qev.activity) {
    state = updateQuestion(state, questionId, { activity });
    qev = state.questions[questionId];
  }

  switch (name) {
    case "pipeline": {
      const eventName = p.event_name as string | undefined;
      if (eventName === "question_start" && qev.processing !== "ended") {
        return updateQuestion(state, questionId, { processing: "running" });
      }
      return state;
    }

    case "stage":
    case "llm_request":
    case "llm_response":
    case "llm_thinking":
    case "llm_content": {
      // These signal running if not ended
      if (qev.processing !== "ended") {
        return updateQuestion(state, questionId, { processing: "running" });
      }
      return state;
    }

    case "llm_failure": {
      if (qev.processing !== "ended") {
        return updateQuestion(state, questionId, { processing: "running" });
      }
      return state;
    }

    case "question_update": {
      const contentRevision = typeof ctx.content_revision === "number" ? ctx.content_revision : null;
      if (contentRevision === null) return state;
      // Ignore older revisions
      if (qev.content.revision !== null && contentRevision < qev.content.revision) return state;
      // Only update if this is not a final receipt, or if revision is higher
      if (qev.content.receipt === "final" && qev.content.revision !== null && contentRevision <= qev.content.revision) {
        return state;
      }
      const question = p.question as ExamQuestion | null | undefined;
      const phase = p.phase as DraftPhase | null | undefined;
      return updateQuestion(state, questionId, {
        content: {
          receipt: qev.content.receipt === "final" ? "final" : "draft",
          revision: contentRevision,
          question: question ?? qev.content.question,
          phase: phase ?? qev.content.phase,
        },
      });
    }

    case "result": {
      const contentRevision = typeof ctx.content_revision === "number" ? ctx.content_revision : null;
      if (contentRevision === null) return state;
      // Ignore lower revisions than already-received final
      if (qev.content.receipt === "final" && qev.content.revision !== null && contentRevision < qev.content.revision) {
        return state;
      }
      const question = payload as ExamQuestion;
      // Clear finalPending if this matches the expected final_revision
      const newFinalPending = qev.finalPending && qev.terminal !== null
        ? qev.terminal.final_revision !== contentRevision
        : false;
      return updateQuestion(state, questionId, {
        content: { receipt: "final", revision: contentRevision, question, phase: "verified" },
        finalPending: newFinalPending,
      });
    }

    case "question_terminal": {
      // A second terminal for the same question is ignored
      if (qev.terminal !== null) return state;
      const terminal = payload as QuestionTerminalPayload;
      const review = terminal.review ?? {};
      const reviewStatus = (review.status ?? "unknown") as QuestionEvidence["review"]["status"];
      const reviewRevision = typeof review.content_revision === "number" ? review.content_revision : null;
      // finalPending: terminal says has_final but we haven't received the final_revision yet
      const finalPending = terminal.has_final &&
        terminal.final_revision !== null &&
        !(qev.content.receipt === "final" && qev.content.revision === terminal.final_revision);
      return updateQuestion(state, questionId, {
        processing: "ended",
        terminal,
        review: { status: reviewStatus, revision: reviewRevision },
        finalPending,
      });
    }

    default:
      return state;
  }
}

function activityRunId(context: Record<string, unknown>, fallback: string): string {
  return typeof context.run_id === "string" && context.run_id
    ? context.run_id
    : fallback;
}

function activityStep(payload: Record<string, unknown>): string {
  const stage = typeof payload.stage === "string" ? payload.stage : "";
  const agent = typeof payload.agent === "string" ? payload.agent : "";
  if (agent.startsWith("sub_generator#")) return "subquestions";
  if (agent === "image_agent" || stage.includes("image")) return "image";
  if (agent === "verifier" || stage === "verify") return "verify";
  if (agent === "corrector" || stage === "correct") return "correct";
  if (agent === "planner" || stage === "batch_briefs") return "planner";
  if (stage === "llm_generate" || agent === "generator") return "text";
  return stage || agent || "unknown";
}

function applyActivity(
  previous: QuestionActivity,
  eventName: string,
  context: Record<string, unknown>,
  payload: Record<string, unknown>,
  fallbackRunId: string,
): QuestionActivity {
  const operationId = typeof context.operation_id === "string" ? context.operation_id : null;
  const callId = typeof context.call_id === "string" ? context.call_id : null;
  if (!operationId && !callId) return previous;

  const runId = activityRunId(context, fallbackRunId);
  const operations = { ...previous.operations };
  const calls = { ...previous.calls };
  const effectiveOperationId = operationId ?? (callId ? `${runId}/call/${callId}` : "");
  const existingOperation = operations[effectiveOperationId];
  const operation: GenerationOperationEvidence = existingOperation ?? {
    operationId: effectiveOperationId,
    step: activityStep(payload),
    status: "active",
    agent: typeof payload.agent === "string" ? payload.agent : null,
    subquestionIndex: typeof context.subquestion_index === "number"
      ? context.subquestion_index
      : null,
    supersedesOperationId: null,
    callIds: [],
  };
  const updatedOperation: GenerationOperationEvidence = {
    ...operation,
    step: operation.step === "unknown" ? activityStep(payload) : operation.step,
    agent: operation.agent ?? (typeof payload.agent === "string" ? payload.agent : null),
    subquestionIndex: operation.subquestionIndex ?? (
      typeof context.subquestion_index === "number" ? context.subquestion_index : null
    ),
    callIds: [...operation.callIds],
  };

  if (eventName === "stage") {
    const status = payload.status;
    if (status === "start") {
      updatedOperation.status = "active";
      if (typeof payload.supersedes_operation_id === "string") {
        updatedOperation.supersedesOperationId = payload.supersedes_operation_id;
        const superseded = operations[payload.supersedes_operation_id];
        if (superseded) {
          operations[payload.supersedes_operation_id] = { ...superseded, status: "superseded" };
        }
      }
    } else if (status === "error") {
      if (updatedOperation.status !== "superseded") updatedOperation.status = "failed";
    } else if (updatedOperation.status !== "superseded") {
      updatedOperation.status = "ended";
    }
  }
  operations[effectiveOperationId] = updatedOperation;

  if (callId && operationId) {
    const callKey = `${runId}/${callId}`;
    const existingCall = calls[callKey];
    const call: GenerationCallEvidence = existingCall ?? {
      runId,
      callId,
      operationId,
      purpose: typeof payload.purpose === "string" ? payload.purpose : "",
      agent: typeof payload.agent === "string" ? payload.agent : "",
      status: "active",
      retryOfCallId: typeof payload.retry_of_call_id === "string"
        ? payload.retry_of_call_id
        : null,
      thinking: "",
      content: "",
    };
    const updatedCall: GenerationCallEvidence = {
      ...call,
      purpose: call.purpose || (typeof payload.purpose === "string" ? payload.purpose : ""),
      agent: call.agent || (typeof payload.agent === "string" ? payload.agent : ""),
      retryOfCallId: call.retryOfCallId ?? (
        typeof payload.retry_of_call_id === "string" ? payload.retry_of_call_id : null
      ),
    };
    if (!updatedOperation.callIds.includes(callId)) {
      updatedOperation.callIds = [...updatedOperation.callIds, callId];
      operations[effectiveOperationId] = updatedOperation;
    }
    if (eventName === "llm_thinking") updatedCall.thinking += typeof payload.text === "string" ? payload.text : "";
    if (eventName === "llm_content") updatedCall.content += typeof payload.text === "string" ? payload.text : "";
    if (eventName === "llm_response") updatedCall.status = "ended";
    if (eventName === "llm_failure") updatedCall.status = "failed";
    calls[callKey] = updatedCall;
  }

  return { operations, calls };
}

function updateQuestion(
  state: RunEvidenceState,
  questionId: string,
  updates: Partial<QuestionEvidence>,
): RunEvidenceState {
  return {
    ...state,
    questions: {
      ...state.questions,
      [questionId]: { ...state.questions[questionId], ...updates },
    },
  };
}

export function closeRun(state: RunEvidenceState): RunEvidenceState {
  const questions: Record<string, QuestionEvidence> = {};
  for (const [qid, qev] of Object.entries(state.questions)) {
    const noTerminal = qev.terminal === null;
    const hadFinalPending = qev.finalPending;
    questions[qid] = {
      ...qev,
      processing: noTerminal ? "unknown" : qev.processing,
      finalPending: false,
      finalMissing: hadFinalPending,
    };
  }
  return { ...state, questions, closed: true };
}

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

/** Number of unique questions that have received a question_terminal event. */
export function selectEndedCount(state: RunEvidenceState): number {
  return Object.values(state.questions).filter((q) => q.terminal !== null).length;
}

/** Number of unique questions whose content.receipt === 'final'. */
export function selectFinalReceivedCount(state: RunEvidenceState): number {
  return Object.values(state.questions).filter((q) => q.content.receipt === "final").length;
}

/** Operations whose own lifecycle is still active for one question. */
export function selectActiveOperations(question: QuestionEvidence): GenerationOperationEvidence[] {
  return Object.values(question.activity?.operations ?? {}).filter(
    (operation) => operation.status === "active",
  );
}

/** Aggregate operation activity by the actual generation step, not agent name. */
export function selectGenerationSteps(
  question: QuestionEvidence,
): Array<{ step: string; active: number; total: number }> {
  const byStep = new Map<string, { step: string; active: number; total: number }>();
  for (const operation of Object.values(question.activity?.operations ?? {})) {
    const current = byStep.get(operation.step) ?? { step: operation.step, active: 0, total: 0 };
    current.total += 1;
    if (operation.status === "active") current.active += 1;
    byStep.set(operation.step, current);
  }
  return [...byStep.values()];
}
