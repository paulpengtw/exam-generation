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

  const qev = state.questions[questionId];
  if (!qev) return state; // unknown question id

  const p = payload as Record<string, unknown>;

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
