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
}

export interface ModificationAnnotationSnapshot {
  segments: ModificationSegmentRequest[];
  instruction: string;
}

export interface ModificationWorkspaceSnapshot {
  kind: "modification";
  version: 1;
  recordId: string;
  questionId: string;
  annotations: ModificationAnnotationSnapshot[];
  replacement: ModificationRunResult | null;
}

export type WorkspaceSnapshot =
  | FormWorkspaceSnapshot
  | ConfirmationWorkspaceSnapshot
  | ResultsWorkspaceSnapshot
  | ModificationWorkspaceSnapshot;
