import type { ExamQuestion, GeneratedQuestion, GenerateStatus } from "../../../hooks/useGenerate";
import { isFiniteNumber, isNullableNumber, isRecord, isStringArray } from "./guards";
import type { ResultsWorkspaceSnapshot } from "./types";

export interface ResultsWorkspaceLive extends Omit<ResultsWorkspaceSnapshot, "kind" | "version" | "completion"> {
  status: GenerateStatus;
}

// Select workspace data explicitly so spreading a hook's state cannot retain llmCalls.
function resultFields(live: Omit<ResultsWorkspaceSnapshot, "kind" | "version" | "completion">) {
  return {
    results: live.results,
    displayResults: live.displayResults,
    progressLines: live.progressLines,
    errorMessage: live.errorMessage,
    startedAt: live.startedAt,
    finishedAt: live.finishedAt,
    subQuestionTotal: live.subQuestionTotal,
    requestedTotal: live.requestedTotal,
    submittedSubQuestionCount: live.submittedSubQuestionCount,
  };
}

export function exportResultsWorkspace(live: ResultsWorkspaceLive): ResultsWorkspaceSnapshot {
  return {
    kind: "results",
    version: 1,
    ...resultFields(live),
    completion: live.status === "error" ? "error"
      : live.finishedAt !== null && live.status === "idle" ? "settled" : "unknown",
  };
}

export function importResultsWorkspace(raw: unknown): ResultsWorkspaceSnapshot | null {
  if (
    !isRecord(raw) || raw.kind !== "results" || raw.version !== 1 ||
    !Array.isArray(raw.results) || !raw.results.every(isRecord) ||
    !Array.isArray(raw.displayResults) || !raw.displayResults.every((item) =>
      isRecord(item) && Number.isInteger(item.index) && isRecord(item.question) && typeof item.isFinal === "boolean") ||
    !isStringArray(raw.progressLines) ||
    !(raw.errorMessage === null || typeof raw.errorMessage === "string") ||
    !isNullableNumber(raw.startedAt) || !isNullableNumber(raw.finishedAt) ||
    !isNullableNumber(raw.subQuestionTotal) || !isFiniteNumber(raw.requestedTotal) ||
    !isNullableNumber(raw.submittedSubQuestionCount) ||
    !(raw.completion === "settled" || raw.completion === "error" || raw.completion === "unknown")
  ) return null;

  return {
    kind: "results",
    version: 1,
    results: raw.results as unknown as ExamQuestion[],
    displayResults: raw.displayResults as unknown as GeneratedQuestion[],
    progressLines: raw.progressLines,
    errorMessage: raw.errorMessage,
    startedAt: raw.startedAt,
    finishedAt: raw.finishedAt,
    subQuestionTotal: raw.subQuestionTotal,
    requestedTotal: raw.requestedTotal,
    submittedSubQuestionCount: raw.submittedSubQuestionCount,
    completion: raw.completion,
  };
}
