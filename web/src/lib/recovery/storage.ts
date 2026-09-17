/**
 * Recovery storage — issue #772.
 *
 * Keys:
 *   localStorage  `exam_recovery_<account_id>_<snapshot_id>`  — snapshot
 *   sessionStorage `exam_recovery_tab`                          — tab pointer
 *   sessionStorage `exam_tab_id`                               — stable per-tab id
 *
 * All writes use read-back verification to detect partial writes.
 * Storage failures are surfaced as typed error results so callers can decide.
 *
 * Draft / snapshot CONTENTS must never be unmasked or logged.
 */
import type { RecoverySnapshotV1 } from "./format";

export interface TabPointer {
  account_id: string;
  snapshot_id: string;
  route: string;
  /** Present when pointer was saved by runSaveAndUpdate (issue #772). */
  tab_id?: string;
  attempted_target_build_id?: string;
  attempted_target_release_revision?: number;
}

export type SaveResult =
  | { ok: true }
  | { ok: false; reason: "storage_denied" | "quota" | "serialize" | "readback_mismatch" };

const TAB_ID_KEY = "exam_tab_id";
const TAB_POINTER_KEY = "exam_recovery_tab";

function snapshotKey(accountId: string, snapshotId: string): string {
  return `exam_recovery_${accountId}_${snapshotId}`;
}

/**
 * Returns the stable per-tab id, creating and persisting one if absent.
 */
export function getOrCreateTabId(): string {
  try {
    const existing = sessionStorage.getItem(TAB_ID_KEY);
    if (existing !== null) return existing;
    const id = crypto.randomUUID();
    sessionStorage.setItem(TAB_ID_KEY, id);
    return id;
  } catch {
    // Fallback: generate but don't persist
    return crypto.randomUUID();
  }
}

/**
 * Save a recovery snapshot transactionally.
 * Writes to localStorage and immediately reads back to verify integrity.
 */
export async function saveSnapshotTransactionally(
  snapshot: RecoverySnapshotV1,
): Promise<SaveResult> {
  const key = snapshotKey(snapshot.account_id, snapshot.snapshot_id);
  let serialized: string;
  try {
    serialized = JSON.stringify(snapshot);
  } catch {
    return { ok: false, reason: "serialize" };
  }

  try {
    localStorage.setItem(key, serialized);
  } catch (e) {
    if (
      e instanceof DOMException &&
      (e.name === "QuotaExceededError" || e.code === 22)
    ) {
      // Some storage implementations can commit part of a write before
      // reporting quota. Remove that candidate so a later boot cannot mistake
      // it for a verified snapshot.
      try { localStorage.removeItem(key); } catch { /* best effort */ }
      return { ok: false, reason: "quota" };
    }
    try { localStorage.removeItem(key); } catch { /* best effort */ }
    return { ok: false, reason: "storage_denied" };
  }

  // Read back and verify
  try {
    const readBack = localStorage.getItem(key);
    if (readBack === null) {
      localStorage.removeItem(key);
      return { ok: false, reason: "readback_mismatch" };
    }
    const parsed = JSON.parse(readBack) as unknown;
    if (JSON.stringify(parsed) !== serialized) {
      localStorage.removeItem(key);
      return { ok: false, reason: "readback_mismatch" };
    }
  } catch {
    localStorage.removeItem(key);
    return { ok: false, reason: "readback_mismatch" };
  }

  return { ok: true };
}

/**
 * Persist the tab pointer to sessionStorage with read-back verification.
 */
export async function persistTabPointer(pointer: TabPointer): Promise<SaveResult> {
  let serialized: string;
  try {
    serialized = JSON.stringify(pointer);
  } catch {
    return { ok: false, reason: "serialize" };
  }

  try {
    sessionStorage.setItem(TAB_POINTER_KEY, serialized);
  } catch (e) {
    if (
      e instanceof DOMException &&
      (e.name === "QuotaExceededError" || e.code === 22)
    ) {
      try { sessionStorage.removeItem(TAB_POINTER_KEY); } catch { /* best effort */ }
      return { ok: false, reason: "quota" };
    }
    try { sessionStorage.removeItem(TAB_POINTER_KEY); } catch { /* best effort */ }
    return { ok: false, reason: "storage_denied" };
  }

  // Read back and verify
  try {
    const readBack = sessionStorage.getItem(TAB_POINTER_KEY);
    if (readBack === null) {
      sessionStorage.removeItem(TAB_POINTER_KEY);
      return { ok: false, reason: "readback_mismatch" };
    }
    const parsed = JSON.parse(readBack) as unknown;
    if (JSON.stringify(parsed) !== serialized) {
      sessionStorage.removeItem(TAB_POINTER_KEY);
      return { ok: false, reason: "readback_mismatch" };
    }
  } catch {
    sessionStorage.removeItem(TAB_POINTER_KEY);
    return { ok: false, reason: "readback_mismatch" };
  }

  return { ok: true };
}

export function loadTabPointer(): TabPointer | null {
  try {
    const raw = sessionStorage.getItem(TAB_POINTER_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      typeof (parsed as Record<string, unknown>).account_id !== "string" ||
      typeof (parsed as Record<string, unknown>).snapshot_id !== "string" ||
      typeof (parsed as Record<string, unknown>).route !== "string"
    ) {
      return null;
    }
    return parsed as TabPointer;
  } catch {
    return null;
  }
}

export function loadSnapshot(
  accountId: string,
  snapshotId: string,
): RecoverySnapshotV1 | null {
  try {
    const raw = localStorage.getItem(snapshotKey(accountId, snapshotId));
    if (raw === null) return null;
    return JSON.parse(raw) as RecoverySnapshotV1;
  } catch {
    return null;
  }
}

export function deleteSnapshot(accountId: string, snapshotId: string): void {
  try {
    localStorage.removeItem(snapshotKey(accountId, snapshotId));
  } catch {
    // Best-effort
  }
}

export function clearTabPointer(): void {
  try {
    sessionStorage.removeItem(TAB_POINTER_KEY);
  } catch {
    // Best-effort
  }
}
