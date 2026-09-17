import type { FormFields, FormParams } from "../../../components/ParamForm";
import type { ExamQuestion, GeneratedQuestion } from "../../../hooks/useGenerate";
import type { ModificationSegmentRequest } from "../../../api/client";
import type { ModificationRunResult } from "../../../hooks/useModificationRun";

export interface FormWorkspaceSnapshot {
  kind: "form";
  version: 1;
  fields: FormFields;
}

export type CoreQuestionResolution = "idle" | "loading" | "generated" | "failed";
export type HistoryDraftChoice = "draft" | "history" | "defaults" | null;

export interface ConfirmationWorkspaceSnapshot {
  kind: "confirmation";
  version: 1;
  pendingParams: FormParams;
  pendingPerQuestionParams: Record<string, unknown>[] | null;
  /** The exact form/history prefill that produced this confirmation, if any. */
  pendingPrefill?: Record<string, unknown> | null;
  clearedPaths: string[];
  redraws: Record<string, number>;
  hasPendingConfirmationEdits: boolean;
  coreQuestionResolution: CoreQuestionResolution;
  historyDraftChoice: HistoryDraftChoice;
}

export type ResultsCompletion = "settled" | "error" | "unknown";

export type ResultsProcessing = "settled" | "interrupted" | "unknown";
export type ResultsReceipt = "none" | "draft" | "final";
export type ResultsReview = "passed" | "failed" | "skipped" | "unknown";

export interface ResultsEvidenceSnapshot {
  stableId: string;
  index: number;
  receipt: ResultsReceipt;
  processing: ResultsProcessing;
  contentRevision: number | null;
  terminal: "normal" | "failed" | "cancelled" | "unknown";
  review: {
    status: ResultsReview;
    contentRevision: number | null;
  };
}

export interface DurableImageSnapshot {
  base64: string;
  mimeType: "image/png";
  location: "question" | "subquestion";
}

export interface ResultsWorkspaceSnapshot {
  kind: "results";
  version: 1;
  results: ExamQuestion[];
  displayResults: GeneratedQuestion[];
  progressLines: string[];
  errorMessage: string | null;
  startedAt: number | null;
  finishedAt: number | null;
  subQuestionTotal: number | null;
  requestedTotal: number;
  submittedSubQuestionCount: number | null;
  completion: ResultsCompletion;
  /** Optional #774 evidence; omitted by older live adapters and snapshots. */
  processing?: ResultsProcessing;
  /** False means the stream ended without authoritative terminal evidence. */
  terminalEvidence?: boolean;
  runId?: string | null;
  evidence?: ResultsEvidenceSnapshot[];
  /** Durable raw PNG bytes keyed by stable question/sub-question identity. */
  images?: Record<string, DurableImageSnapshot>;
}

export interface ModificationAnnotationSnapshot {
  segments: ModificationSegmentRequest[];
  instruction: string;
}

export type ModificationRecordStatus = "completed" | "failed" | "aborted";

/**
 * Evidence captured from the History detail that makes a manual-review base
 * eligible. The record id is the immutable version anchor; contentRevision
 * is retained when a producer exposes one.
 */
export interface ModificationEligibilityEvidence {
  status: ModificationRecordStatus;
  verified: boolean;
  eligible: boolean;
}

export interface ModificationWorkspaceSnapshot {
  kind: "modification";
  version: 1;
  route: string;
  subject: string;
  recordId: string;
  questionId: string;
  contentIdentity: string;
  contentRevision: number | null;
  eligibility: ModificationEligibilityEvidence;
  annotations: ModificationAnnotationSnapshot[];
  replacement: ModificationRunResult | null;
}

export type WorkspaceSnapshot =
  | FormWorkspaceSnapshot
  | ConfirmationWorkspaceSnapshot
  | ResultsWorkspaceSnapshot
  | ModificationWorkspaceSnapshot;
