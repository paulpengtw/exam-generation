import type { ModificationSegmentRequest } from "../../../api/client";
import type { ModificationRunResult } from "../../../hooks/useModificationRun";
import { isRecord } from "./guards";
import type { ModificationAnnotationSnapshot, ModificationWorkspaceSnapshot } from "./types";

type ModificationWorkspaceLive = Omit<ModificationWorkspaceSnapshot, "kind" | "version">;

function isSegment(value: unknown): value is ModificationSegmentRequest {
  return isRecord(value) && typeof value.field_path === "string" &&
    Number.isInteger(value.start) && Number.isInteger(value.end) && typeof value.quoted_text === "string";
}

function isAnnotation(value: unknown): value is ModificationAnnotationSnapshot {
  return isRecord(value) && Array.isArray(value.segments) &&
    value.segments.every(isSegment) && typeof value.instruction === "string";
}

export function exportModificationWorkspace(live: ModificationWorkspaceLive): ModificationWorkspaceSnapshot {
  return { ...live, kind: "modification", version: 1 };
}

export function importModificationWorkspace(raw: unknown): ModificationWorkspaceLive | null {
  if (
    !isRecord(raw) || raw.kind !== "modification" || raw.version !== 1 ||
    typeof raw.recordId !== "string" || raw.recordId.length === 0 ||
    typeof raw.questionId !== "string" || raw.questionId.length === 0 ||
    !Array.isArray(raw.annotations) || !raw.annotations.every(isAnnotation) ||
    !(raw.replacement === null || (isRecord(raw.replacement) && isRecord(raw.replacement.question)))
  ) return null;

  return {
    recordId: raw.recordId,
    questionId: raw.questionId,
    annotations: raw.annotations,
    replacement: raw.replacement as unknown as ModificationRunResult | null,
  };
}
