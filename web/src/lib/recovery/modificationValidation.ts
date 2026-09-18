import type { HistoryDetail } from "../../api/client";
import {
  canonicalQuestionIdentity,
} from "../workspace/adapters/modificationWorkspace";
import type { ModificationWorkspaceSnapshot } from "../workspace/adapters/types";

export type ModificationRestoreBlockReason =
  | "route_changed"
  | "record_changed"
  | "question_changed"
  | "subject_changed"
  | "content_changed"
  | "ineligible";

export type ModificationBaseValidation =
  | { valid: true }
  | { valid: false; reason: ModificationRestoreBlockReason };

function contentRevision(question: Record<string, unknown>): number | null {
  const revision = question.content_revision;
  return typeof revision === "number" && Number.isInteger(revision) && revision > 0
    ? revision
    : null;
}

function isVerified(question: Record<string, unknown>): boolean {
  const verification = question.verification;
  return verification !== null && typeof verification === "object" &&
    (verification as Record<string, unknown>).passed === true;
}

/**
 * Compare a restored manual-review draft with the exact History version that
 * the current route authorized. The History endpoint may follow a version
 * chain, so an id mismatch is deliberately a hard block instead of a
 * retarget to the newest descendant.
 */
export function validateModificationBase(
  snapshot: ModificationWorkspaceSnapshot,
  detail: HistoryDetail,
  currentRoute: string,
): ModificationBaseValidation {
  if (snapshot.route !== currentRoute) return { valid: false, reason: "route_changed" };
  if (detail.id !== snapshot.recordId) return { valid: false, reason: "record_changed" };
  if (detail.question_id !== snapshot.questionId) {
    return { valid: false, reason: "question_changed" };
  }
  if (detail.subject !== snapshot.subject) return { valid: false, reason: "subject_changed" };
  if (detail.question_json === null) return { valid: false, reason: "ineligible" };

  if (canonicalQuestionIdentity(detail.question_json) !== snapshot.contentIdentity) {
    return { valid: false, reason: "content_changed" };
  }
  if (contentRevision(detail.question_json) !== snapshot.contentRevision) {
    return { valid: false, reason: "content_changed" };
  }

  if (
    !snapshot.eligibility.eligible ||
    snapshot.eligibility.status !== detail.status ||
    detail.status !== "completed"
  ) {
    return { valid: false, reason: "ineligible" };
  }

  // A settled replacement is itself a valid next modification base even if
  // its verifier verdict is negative; the existing card deliberately keeps
  // selection enabled after every settled replacement for another review
  // round. An original record still requires its verified verdict.
  if (!isVerified(detail.question_json) && snapshot.replacement === null) {
    return { valid: false, reason: "ineligible" };
  }

  return { valid: true };
}
