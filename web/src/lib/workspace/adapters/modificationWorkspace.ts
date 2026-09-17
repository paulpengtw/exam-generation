import type { ModificationSegmentRequest } from "../../../api/client";
import type { ModificationRunResult } from "../../../hooks/useModificationRun";
import { isRecord } from "./guards";
import type {
  ModificationAnnotationSnapshot,
  ModificationRecordStatus,
  ModificationWorkspaceSnapshot,
} from "./types";

export type ModificationWorkspaceLive = Omit<ModificationWorkspaceSnapshot, "kind" | "version">;

const NON_CONTENT_KEYS = new Set(["verification", "image_stale", "content_revision"]);

function canonicalize(value: unknown, key?: string, depth = 0): unknown {
  if (depth === 1 && key !== undefined && NON_CONTENT_KEYS.has(key)) return undefined;
  if (typeof value === "string") {
    if (key === "image_base64") {
      return value.replace(/^data:image\/png;base64,/i, "");
    }
    return value;
  }
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (Array.isArray(value)) return value.map((item) => canonicalize(item, undefined, depth + 1));
  if (isRecord(value)) {
    const output: Record<string, unknown> = {};
    for (const entryKey of Object.keys(value).sort()) {
      const entry = canonicalize(value[entryKey], entryKey, depth + 1);
      if (entry !== undefined) output[entryKey] = entry;
    }
    return output;
  }
  return null;
}

/** Stable identity for the question content used by the restore base check. */
export function canonicalQuestionIdentity(question: unknown): string {
  return JSON.stringify(canonicalize(question));
}

function isSegment(value: unknown): value is ModificationSegmentRequest {
  return isRecord(value) && typeof value.field_path === "string" && value.field_path.length > 0 &&
    typeof value.start === "number" && Number.isInteger(value.start) && value.start >= 0 &&
    typeof value.end === "number" && Number.isInteger(value.end) && value.end >= value.start &&
    typeof value.quoted_text === "string" && value.quoted_text.trim().length > 0;
}

function isAnnotation(value: unknown): value is ModificationAnnotationSnapshot {
  return isRecord(value) && Array.isArray(value.segments) && value.segments.length > 0 &&
    value.segments.every(isSegment) && typeof value.instruction === "string";
}

function isRecordStatus(value: unknown): value is ModificationRecordStatus {
  return value === "completed" || value === "failed" || value === "aborted";
}

function isEligibility(value: unknown): value is ModificationWorkspaceLive["eligibility"] {
  return isRecord(value) && isRecordStatus(value.status) &&
    typeof value.verified === "boolean" && typeof value.eligible === "boolean";
}

function isJsonValue(value: unknown): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  if (isRecord(value)) return Object.values(value).every(isJsonValue);
  return false;
}

function isReplacement(value: unknown): value is ModificationRunResult {
  return isRecord(value) &&
    (value.record_id === null || (typeof value.record_id === "string" && value.record_id.length > 0)) &&
    isRecord(value.question) &&
    Array.isArray(value.ripple_report) && value.ripple_report.every((item) => typeof item === "string") &&
    typeof value.verified === "boolean" &&
    isJsonValue(value.verification) &&
    (value.failure_details === null || typeof value.failure_details === "string");
}

export function exportModificationWorkspace(live: ModificationWorkspaceLive): ModificationWorkspaceSnapshot {
  return { ...live, kind: "modification", version: 1 };
}

export function importModificationWorkspace(raw: unknown): ModificationWorkspaceLive | null {
  if (
    !isRecord(raw) || raw.kind !== "modification" || raw.version !== 1 ||
    typeof raw.route !== "string" || raw.route.length === 0 ||
    typeof raw.subject !== "string" || raw.subject.length === 0 ||
    typeof raw.recordId !== "string" || raw.recordId.length === 0 ||
    typeof raw.questionId !== "string" || raw.questionId.length === 0 ||
    typeof raw.contentIdentity !== "string" || raw.contentIdentity.length === 0 ||
    !(raw.contentRevision === null ||
      (typeof raw.contentRevision === "number" && Number.isInteger(raw.contentRevision) && raw.contentRevision > 0)) ||
    !isEligibility(raw.eligibility) ||
    !Array.isArray(raw.annotations) || !raw.annotations.every(isAnnotation) ||
    !(raw.replacement === null || isReplacement(raw.replacement))
  ) return null;

  return {
    route: raw.route,
    subject: raw.subject,
    recordId: raw.recordId,
    questionId: raw.questionId,
    contentIdentity: raw.contentIdentity,
    contentRevision: raw.contentRevision,
    eligibility: raw.eligibility,
    annotations: raw.annotations,
    replacement: raw.replacement,
  };
}
