/**
 * Auto-refresh eligibility and per-tab marker — issue #777.
 *
 * Automatic page reload is allowed ONLY for a fully hydrated, visible, empty
 * page with no input, results, dialog/editor, callback, pending restoration,
 * or active operation. Enforces at most one automatic reload per
 * target/release revision per tab. If the marker cannot be stored, automation
 * is disabled for this tab.
 */
import type { WorkspaceState } from "../workspace/workspaceStore";
import { isRefreshSafe } from "../workspace/workspaceStore";
import type { ReleaseStatus } from "../release/releaseStore";

export type AutoRefreshIneligibleReason =
  | "no_update"
  | "not_visible"
  | "not_safe"
  | "pending_recovery"
  | "already_reloaded"
  | "marker_storage_denied";

export type AutoRefreshEligibility =
  | { eligible: true }
  | { eligible: false; reason: AutoRefreshIneligibleReason };

function autoReloadMarkerKey(targetBuildId: string, releaseRevision: number): string {
  return `exam_auto_reload_${targetBuildId}_${releaseRevision}`;
}

export function hasAutoReloadBeenAttempted(
  targetBuildId: string,
  releaseRevision: number,
): boolean {
  try {
    return sessionStorage.getItem(autoReloadMarkerKey(targetBuildId, releaseRevision)) !== null;
  } catch {
    return false;
  }
}

/**
 * Persists the auto-reload marker. Returns false if storage is denied
 * (automation should be disabled for this tab).
 */
export function markAutoReloadAttempted(
  targetBuildId: string,
  releaseRevision: number,
): boolean {
  const key = autoReloadMarkerKey(targetBuildId, releaseRevision);
  try {
    sessionStorage.setItem(key, "1");
    return sessionStorage.getItem(key) !== null;
  } catch {
    return false;
  }
}

export function checkAutoRefreshEligible(params: {
  workspaceState: Pick<WorkspaceState, "surfaces" | "operations">;
  recoveryPending: boolean;
  pageVisible: boolean;
  targetBuildId: string | null;
  releaseRevision: number | null;
  releaseStatus: ReleaseStatus;
}): AutoRefreshEligibility {
  const {
    workspaceState,
    recoveryPending,
    pageVisible,
    targetBuildId,
    releaseRevision,
    releaseStatus,
  } = params;

  if (
    releaseStatus !== "update-required" ||
    targetBuildId === null ||
    releaseRevision === null
  ) {
    return { eligible: false, reason: "no_update" };
  }

  if (!pageVisible) {
    return { eligible: false, reason: "not_visible" };
  }

  const { safe } = isRefreshSafe(workspaceState);
  if (!safe) {
    return { eligible: false, reason: "not_safe" };
  }

  if (recoveryPending) {
    return { eligible: false, reason: "pending_recovery" };
  }

  if (hasAutoReloadBeenAttempted(targetBuildId, releaseRevision)) {
    return { eligible: false, reason: "already_reloaded" };
  }

  return { eligible: true };
}
