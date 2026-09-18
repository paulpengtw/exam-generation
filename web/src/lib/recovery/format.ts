/**
 * Recovery snapshot format definitions — issue #772.
 */
import type { FormWorkspaceSnapshot } from "../workspace/adapters/types";
import { importConfirmationWorkspace } from "../workspace/adapters/confirmationWorkspace";
import type { ConfirmationWorkspaceSnapshot } from "../workspace/adapters/types";
import { importResultsWorkspace } from "../workspace/adapters/resultsWorkspace";
import type { ResultsWorkspaceSnapshot } from "../workspace/adapters/types";
import {
  exportModificationWorkspace,
  importModificationWorkspace,
} from "../workspace/adapters/modificationWorkspace";
import type { ModificationWorkspaceSnapshot } from "../workspace/adapters/types";

export const RECOVERY_FORMAT_V1 = "exam-generation.recovery/1" as const;
export type RecoveryFormatV1 = typeof RECOVERY_FORMAT_V1;

export interface RecoverySnapshotV1 {
  schema: RecoveryFormatV1;
  snapshot_id: string;
  tab_id: string;
  route: string;
  subject: string;
  account_id: string;
  origin: string;
  environment: string;
  source_build_id: string;
  target_build_id: string;
  source_release_revision: number | null;
  target_release_revision: number;
  saved_at: string; // ISO
  workspace_revision: number;
  form: FormWorkspaceSnapshot;
  /** Optional so snapshots written by #772 remain readable. */
  confirmation?: ConfirmationWorkspaceSnapshot;
  /** Optional so snapshots written by #772/#773 remain readable. */
  results?: ResultsWorkspaceSnapshot;
  /** Optional so snapshots written by #772/#773/#774 remain readable. */
  modification?: ModificationWorkspaceSnapshot;
}

export type ParseRecoveryResult =
  | { ok: true; snapshot: RecoverySnapshotV1 }
  | {
      ok: false;
      reason:
        | "malformed"
        | "unknown_schema"
        | "wrong_account"
        | "wrong_origin"
        | "environment_mismatch"
        | "invalid_form";
    };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function parseRecoverySnapshot(
  raw: unknown,
  opts: {
    expectedAccountId: string;
    expectedOrigin: string;
    expectedEnvironment: string;
  },
): ParseRecoveryResult {
  if (!isRecord(raw)) {
    return { ok: false, reason: "malformed" };
  }

  // Schema check first
  if (raw.schema !== RECOVERY_FORMAT_V1) {
    if (typeof raw.schema === "string" && raw.schema.length > 0) {
      return { ok: false, reason: "unknown_schema" };
    }
    return { ok: false, reason: "malformed" };
  }

  // Required string fields
  const requiredStrings: Array<keyof RecoverySnapshotV1> = [
    "snapshot_id",
    "tab_id",
    "route",
    "subject",
    "account_id",
    "origin",
    "environment",
    "source_build_id",
    "target_build_id",
    "saved_at",
  ];
  for (const field of requiredStrings) {
    if (typeof raw[field] !== "string") {
      return { ok: false, reason: "malformed" };
    }
  }

  // Numeric fields
  if (
    typeof raw.target_release_revision !== "number" ||
    typeof raw.workspace_revision !== "number"
  ) {
    return { ok: false, reason: "malformed" };
  }

  // source_release_revision can be null or number
  if (raw.source_release_revision !== null && typeof raw.source_release_revision !== "number") {
    return { ok: false, reason: "malformed" };
  }

  // Account check
  if (raw.account_id !== opts.expectedAccountId) {
    return { ok: false, reason: "wrong_account" };
  }

  // Origin check
  if (raw.origin !== opts.expectedOrigin) {
    return { ok: false, reason: "wrong_origin" };
  }

  // Environment check
  if (raw.environment !== opts.expectedEnvironment) {
    return { ok: false, reason: "environment_mismatch" };
  }

  // Form validation: must be { kind: "form", version: 1 }
  if (!isRecord(raw.form) || raw.form.kind !== "form" || raw.form.version !== 1) {
    return { ok: false, reason: "invalid_form" };
  }

  // Confirmation is an optional v1 extension. Validate it through the same
  // adapter used by the live workspace so malformed pending state never wins
  // over normal form hydration.
  if (Object.hasOwn(raw, "confirmation") && !importConfirmationWorkspace(raw.confirmation)) {
    return { ok: false, reason: "invalid_form" };
  }

  // Received results are an optional member of the same v1 envelope. They
  // must pass the workspace adapter before the page is allowed to hydrate;
  // otherwise a half-written result could replace the original workspace.
  const resultsSnapshot = Object.hasOwn(raw, "results")
    ? importResultsWorkspace(raw.results)
    : undefined;
  if (Object.hasOwn(raw, "results") && !resultsSnapshot) {
    return { ok: false, reason: "invalid_form" };
  }

  // Manual-review drafts are an optional v1 extension. They are validated
  // through the same adapter used by the live History card.
  const modificationSnapshot = Object.hasOwn(raw, "modification")
    ? importModificationWorkspace(raw.modification)
    : undefined;
  if (Object.hasOwn(raw, "modification") && !modificationSnapshot) {
    return { ok: false, reason: "invalid_form" };
  }

  return {
    ok: true,
    snapshot: {
      ...(raw as unknown as RecoverySnapshotV1),
      ...(resultsSnapshot ? { results: resultsSnapshot } : {}),
      ...(modificationSnapshot
        ? { modification: exportModificationWorkspace(modificationSnapshot) }
        : {}),
    },
  };
}
