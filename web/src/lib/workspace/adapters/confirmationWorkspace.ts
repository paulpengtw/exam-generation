import type { FormParams } from "../../../components/ParamForm";
import { isFiniteNumber, isRecord, isStringArray } from "./guards";
import type { ConfirmationWorkspaceSnapshot } from "./types";

type ConfirmationWorkspaceLive = Omit<ConfirmationWorkspaceSnapshot, "kind" | "version">;

export function exportConfirmationWorkspace(live: ConfirmationWorkspaceLive): ConfirmationWorkspaceSnapshot {
  return { ...live, kind: "confirmation", version: 1 };
}

export function importConfirmationWorkspace(raw: unknown): ConfirmationWorkspaceLive | null {
  if (
    !isRecord(raw) || raw.kind !== "confirmation" || raw.version !== 1 ||
    !isRecord(raw.pendingParams) || typeof raw.pendingParams.subject !== "string" ||
    !(raw.pendingPerQuestionParams === null ||
      (Array.isArray(raw.pendingPerQuestionParams) && raw.pendingPerQuestionParams.every(isRecord))) ||
    !isStringArray(raw.clearedPaths) ||
    !isRecord(raw.redraws) || !Object.values(raw.redraws).every(isFiniteNumber) ||
    typeof raw.hasPendingConfirmationEdits !== "boolean" ||
    !(raw.coreQuestionResolution === "idle" || raw.coreQuestionResolution === "loading" ||
      raw.coreQuestionResolution === "generated" || raw.coreQuestionResolution === "failed") ||
    !(raw.historyDraftChoice === null || raw.historyDraftChoice === "draft" ||
      raw.historyDraftChoice === "history" || raw.historyDraftChoice === "defaults")
  ) return null;

  return {
    // The resolver carries subject at runtime even though FormParams omits it.
    pendingParams: raw.pendingParams as unknown as FormParams,
    pendingPerQuestionParams: raw.pendingPerQuestionParams,
    clearedPaths: raw.clearedPaths,
    redraws: raw.redraws as Record<string, number>,
    hasPendingConfirmationEdits: raw.hasPendingConfirmationEdits,
    coreQuestionResolution: raw.coreQuestionResolution,
    historyDraftChoice: raw.historyDraftChoice,
  };
}
