/**
 * Save-and-update eligibility + controller — issue #772.
 */
import type { SurfaceParticipation, ActiveOperation } from "../workspace/workspaceStore";
import type { SurfaceId } from "../workspace/workspaceStore";
import type { AuthUser } from "../../store/authStore";
import type { ReleaseStatus } from "../release/releaseStore";
import { RECOVERY_FORMAT_V1 } from "./format";
import { importConfirmationWorkspace } from "../workspace/adapters/confirmationWorkspace";
import type { ConfirmationWorkspaceSnapshot } from "../workspace/adapters/types";

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

function readConfirmationSnapshot(
  surface: SurfaceParticipation | undefined,
): ConfirmationWorkspaceSnapshot | null {
  if (!surface?.exportWorkspace) return null;
  try {
    const raw = surface.exportWorkspace();
    if (!importConfirmationWorkspace(raw)) return null;
    return raw as ConfirmationWorkspaceSnapshot;
  } catch {
    return null;
  }
}

function jsonClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function sameJsonValue(left: unknown, right: unknown): boolean {
  try {
    return JSON.stringify(left) === JSON.stringify(right);
  } catch {
    return false;
  }
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

  // A confirmation may be carried only after its own async work has settled.
  // The export seam is the source of truth; registration alone is not enough.
  const confirmationSurface = state.surfaces["generate.confirmation"];
  if (confirmationSurface) {
    const confirmation = readConfirmationSnapshot(confirmationSurface);
    if (!confirmation || confirmation.coreQuestionResolution === "loading") {
      return { allowed: false, reason: "confirmation_open" };
    }
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

import {
  saveSnapshotTransactionally,
  persistTabPointer,
  getOrCreateTabId,
} from "./storage";
import type { RecoverySnapshotV1 } from "./format";
import type { FormWorkspaceSnapshot } from "../workspace/adapters/types";
import { useWorkspaceStore } from "../workspace/workspaceStore";
import { useReleaseStore } from "../release/releaseStore";
import { useAuthStore } from "../../store/authStore";

export type RunResult =
  | { ok: true; snapshot_id: string }
  | { ok: false; reason: string; retryable: boolean };

/**
 * Execute the save-and-update flow (issues #772/#773).
 *
 * deps are injectable for testing; all have sensible production defaults.
 */
export async function runSaveAndUpdate(
  deps?: {
    navigate?: () => void;
    now?: () => number;
    origin?: string;
    environment?: string;
    buildId?: string;
  },
): Promise<RunResult> {
  const navigate = deps?.navigate ?? (() => window.location.reload());
  const now = deps?.now ?? (() => Date.now());
  const origin = deps?.origin ?? window.location.origin;
  const environment = deps?.environment ?? __BUILD_ENVIRONMENT__;
  const buildId = deps?.buildId ?? __BUILD_ID__;

  // (a) evaluateSaveAndUpdate must allow
  const wsState = useWorkspaceStore.getState();
  const releaseState = useReleaseStore.getState();
  const authState = useAuthStore.getState();

  const evalResult = evaluateSaveAndUpdate({
    surfaces: wsState.surfaces,
    operations: wsState.operations,
    releaseStatus: releaseState.status,
    requiredBuildId: releaseState.requiredBuildId,
    releaseRevision: releaseState.releaseRevision,
    supportedRecoveryFormats: releaseState.supportedRecoveryFormats,
    user: authState.user,
  });

  if (!evalResult.allowed) {
    return { ok: false, reason: evalResult.reason, retryable: false };
  }

  // (b) record workspace_revision and auth user id
  const workspaceRevisionAtSave = wsState.workspace_revision;
  const userId = authState.user!.id; // safe: evalResult.allowed implies user is set
  const requiredBuildIdAtEval = releaseState.requiredBuildId!;

  // (c) export the form via the 'generate.form' surface's exportWorkspace
  const formSurface = wsState.surfaces["generate.form"];
  const formSnapshot = formSurface?.exportWorkspace?.();
  if (
    !formSnapshot ||
    formSnapshot.kind !== "form" ||
    formSnapshot.version !== 1
  ) {
    return { ok: false, reason: "export_failed", retryable: true };
  }

  // Confirmation is an independent workspace. Capture and clone both seams
  // before the awaited release recheck so late callbacks cannot overwrite the
  // settled state that the teacher saw.
  const confirmationSurface = wsState.surfaces["generate.confirmation"];
  const confirmationSnapshot = confirmationSurface
    ? readConfirmationSnapshot(confirmationSurface)
    : null;
  if (confirmationSurface && !confirmationSnapshot) {
    return { ok: false, reason: "export_failed", retryable: true };
  }
  let capturedFormSnapshot: FormWorkspaceSnapshot;
  let capturedConfirmationSnapshot: ConfirmationWorkspaceSnapshot | undefined;
  try {
    capturedFormSnapshot = jsonClone(formSnapshot as FormWorkspaceSnapshot);
    capturedConfirmationSnapshot = confirmationSnapshot
      ? jsonClone(confirmationSnapshot)
      : undefined;
  } catch {
    return { ok: false, reason: "export_failed", retryable: true };
  }

  // (d) setFreezeInput true
  useWorkspaceStore.getState().setFreezeInput(true);

  const cleanup = () => {
    useWorkspaceStore.getState().setFreezeInput(false);
    useWorkspaceStore.getState().clearNavigationApproval();
  };

  // (e) await checkNow() (one bounded recheck) and revalidate conditions
  await useReleaseStore.getState().checkNow();

  const recheckRelease = useReleaseStore.getState();
  const recheckAuth = useAuthStore.getState();
  const recheckWs = useWorkspaceStore.getState();

  if (recheckWs.operations.length > 0) {
    cleanup();
    return { ok: false, reason: "operation_active", retryable: true };
  }
  const recheckSurfaces = Object.values(recheckWs.surfaces).filter(Boolean) as SurfaceParticipation[];
  if (recheckSurfaces.some((surface) => surface.hasReceivedResults)) {
    cleanup();
    return { ok: false, reason: "results_present", retryable: false };
  }
  if (recheckWs.surfaces["history.modification"]) {
    cleanup();
    return { ok: false, reason: "modification_draft", retryable: false };
  }

  if (
    recheckRelease.status !== "update-required" ||
    recheckRelease.requiredBuildId === null
  ) {
    cleanup();
    return { ok: false, reason: "target_changed", retryable: false };
  }
  if (recheckRelease.requiredBuildId !== requiredBuildIdAtEval) {
    cleanup();
    return { ok: false, reason: "target_changed", retryable: false };
  }
  if (!recheckRelease.supportedRecoveryFormats.includes(RECOVERY_FORMAT_V1)) {
    cleanup();
    return { ok: false, reason: "unsupported_target_reader", retryable: false };
  }
  if (recheckAuth.user?.id !== userId) {
    cleanup();
    return { ok: false, reason: "account_changed", retryable: false };
  }
  if (recheckWs.workspace_revision !== workspaceRevisionAtSave) {
    cleanup();
    return { ok: false, reason: "workspace_changed", retryable: true };
  }

  // A callback can mutate a captured object without going through the store's
  // revision counter. Compare fresh exports as a second, content-level guard.
  const currentFormSnapshot = recheckWs.surfaces["generate.form"]?.exportWorkspace?.();
  const currentConfirmationSnapshot = recheckWs.surfaces["generate.confirmation"]
    ? readConfirmationSnapshot(recheckWs.surfaces["generate.confirmation"])
    : null;
  if (
    !currentFormSnapshot ||
    currentFormSnapshot.kind !== "form" ||
    currentFormSnapshot.version !== 1 ||
    !sameJsonValue(currentFormSnapshot, capturedFormSnapshot) ||
    !sameJsonValue(currentConfirmationSnapshot, capturedConfirmationSnapshot ?? null) ||
    (currentConfirmationSnapshot?.coreQuestionResolution === "loading")
  ) {
    cleanup();
    return { ok: false, reason: "workspace_changed", retryable: true };
  }

  // (f) build RecoverySnapshotV1
  const snapshotId = crypto.randomUUID();
  const tabId = getOrCreateTabId();
  const route = window.location.pathname;
  // subject is the second path segment: /generate/math → "math"
  const subject = route.split("/").filter(Boolean)[1] ?? "math";

  const targetBuildId = recheckRelease.requiredBuildId;
  const targetReleaseRevision = recheckRelease.releaseRevision!;
  const sourceReleaseRevision = releaseState.releaseRevision;

  const recoverySnapshot: RecoverySnapshotV1 = {
    schema: RECOVERY_FORMAT_V1,
    snapshot_id: snapshotId,
    tab_id: tabId,
    route,
    subject,
    account_id: userId,
    origin,
    environment,
    source_build_id: buildId,
    target_build_id: targetBuildId,
    source_release_revision: sourceReleaseRevision,
    target_release_revision: targetReleaseRevision,
    saved_at: new Date(now()).toISOString(),
    workspace_revision: workspaceRevisionAtSave,
    form: capturedFormSnapshot,
    ...(capturedConfirmationSnapshot
      ? { confirmation: capturedConfirmationSnapshot }
      : {}),
  };

  // (g) saveSnapshotTransactionally
  const saveResult = await saveSnapshotTransactionally(recoverySnapshot);
  if (!saveResult.ok) {
    cleanup();
    return {
      ok: false,
      reason: saveResult.reason,
      retryable: saveResult.reason === "quota" || saveResult.reason === "readback_mismatch",
    };
  }

  // (h) persistTabPointer → on failure: leave snapshot, no navigate, return pointer_failed
  const pointerResult = await persistTabPointer({
    tab_id: tabId,
    snapshot_id: snapshotId,
    account_id: userId,
    route,
    attempted_target_build_id: targetBuildId,
    attempted_target_release_revision: targetReleaseRevision,
  });
  if (!pointerResult.ok) {
    cleanup();
    return { ok: false, reason: "pointer_failed", retryable: true };
  }

  // (i) approveNavigation on workspace store
  useWorkspaceStore.getState().approveNavigation(route);

  // (j) navigate — do not reset freezeInput on success (page is reloading)
  navigate();

  return { ok: true, snapshot_id: snapshotId };
}
