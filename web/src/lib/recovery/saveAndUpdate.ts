/**
 * Save-and-update eligibility + controller — issue #772.
 */
import type { SurfaceParticipation, ActiveOperation } from "../workspace/workspaceStore";
import type { SurfaceId } from "../workspace/workspaceStore";
import type { AuthUser } from "../../store/authStore";
import type { ReleaseStatus } from "../release/releaseStore";
import { RECOVERY_FORMAT_V1 } from "./format";

export type SaveAndUpdateDeniedReason =
  | "no_surface"
  | "hydrating"
  | "restoring"
  | "operation_active"
  | "results_present"
  | "confirmation_open"
  | "modification_draft"
  | "not_signed_in"
  | "no_update"
  | "unsupported_target_reader"
  | "account_changed"
  | "target_changed"
  | "workspace_changed";

export type EvaluateResult =
  | { allowed: true }
  | { allowed: false; reason: SaveAndUpdateDeniedReason };

export interface EvaluateInput {
  surfaces: Partial<Record<SurfaceId, SurfaceParticipation>>;
  operations: ActiveOperation[];
  releaseStatus: ReleaseStatus;
  requiredBuildId: string | null;
  releaseRevision: number | null;
  supportedRecoveryFormats: string[];
  user: AuthUser | null;
}

export function evaluateSaveAndUpdate(state: EvaluateInput): EvaluateResult {
  const surfaceList = Object.values(state.surfaces).filter(Boolean) as SurfaceParticipation[];

  // Must have at least one surface
  if (surfaceList.length === 0) {
    return { allowed: false, reason: "no_surface" };
  }

  // All surfaces must be ready
  for (const surface of surfaceList) {
    if (surface.readiness === "hydrating") {
      return { allowed: false, reason: "hydrating" };
    }
    if (surface.readiness === "restoring") {
      return { allowed: false, reason: "restoring" };
    }
  }

  // No active operations
  if (state.operations.length > 0) {
    return { allowed: false, reason: "operation_active" };
  }

  // No surface has received results
  for (const surface of surfaceList) {
    if (surface.hasReceivedResults) {
      return { allowed: false, reason: "results_present" };
    }
  }

  // Confirmation must not be open
  if (state.surfaces["generate.confirmation"]) {
    return { allowed: false, reason: "confirmation_open" };
  }

  // Modification draft must not be open
  if (state.surfaces["history.modification"]) {
    return { allowed: false, reason: "modification_draft" };
  }

  // User must be signed in
  if (!state.user) {
    return { allowed: false, reason: "not_signed_in" };
  }

  // Release must be update-required with known ids
  if (
    state.releaseStatus !== "update-required" ||
    state.requiredBuildId === null ||
    state.releaseRevision === null
  ) {
    return { allowed: false, reason: "no_update" };
  }

  // Recovery format must be supported by the target reader
  const formSurface = state.surfaces["generate.form"];
  const targetSupportsFormat = state.supportedRecoveryFormats.includes(RECOVERY_FORMAT_V1);
  const hasExportSeam = formSurface?.exportWorkspace !== undefined;

  if (!targetSupportsFormat || !hasExportSeam) {
    return { allowed: false, reason: "unsupported_target_reader" };
  }

  return { allowed: true };
}

export interface RunSaveAndUpdateOptions {
  navigate: (path: string) => void;
  now?: () => string;
}

export type RunResult =
  | { ok: true }
  | { ok: false; reason: string };

/**
 * Execute the save-and-update flow.
 * Exported so callers can use it; real implementation will be fleshed out in S3.
 */
export async function runSaveAndUpdate(
  _opts: RunSaveAndUpdateOptions,
): Promise<RunResult> {
  return { ok: false, reason: "not_implemented" };
}
