/**
 * Recovery storage — issue #772, hardened in issue #776.
 *
 * Keys:
 *   localStorage  `exam_recovery_<account_id>_<snapshot_id>`  — snapshot
 *   localStorage  `exam_recovery_claim_<snapshot_id>`          — transactional claim (#776)
 *   sessionStorage `exam_recovery_tab`                          — tab pointer
 *   sessionStorage `exam_tab_id`                               — stable per-tab id
 *
 * All writes use read-back verification to detect partial writes.
 * Storage failures are surfaced as typed error results so callers can decide.
 *
 * Draft / snapshot CONTENTS must never be unmasked or logged.
 * Tab IDs, account IDs, and claim nonces are structural only — never contents.
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

// ────────────────────────────────────────────────────────────────────────────
// Issue #776 — Identity hardening
// ────────────────────────────────────────────────────────────────────────────

const CLAIM_KEY_PREFIX = "exam_recovery_claim_";
const COLLISION_CHANNEL_NAME = "exam_tab_collision";

export interface RestorationClaim {
  tab_id: string;
  nonce: string;
  snapshot_id: string;
  claimed_at: string;
}

/**
 * Write a transactional restoration claim for the given snapshot.
 * Returns {won: true} only when the claim read-back confirms this tab's nonce.
 * Two tabs racing to claim the same snapshot will produce different nonces;
 * the loser reads the winner's nonce back and yields.
 * Does not log or expose snapshot contents.
 */
export async function claimSnapshot(
  tabId: string,
  snapshotId: string,
): Promise<{ won: boolean }> {
  const nonce = crypto.randomUUID();
  const claim: RestorationClaim = {
    tab_id: tabId,
    snapshot_id: snapshotId,
    nonce,
    claimed_at: new Date().toISOString(),
  };
  const key = `${CLAIM_KEY_PREFIX}${snapshotId}`;
  const serialized = JSON.stringify(claim);
  try {
    localStorage.setItem(key, serialized);
  } catch {
    return { won: false };
  }
  // Read back: confirm our nonce is in place (no other tab overwrote it)
  try {
    const readBack = localStorage.getItem(key);
    if (!readBack) return { won: false };
    const parsed = JSON.parse(readBack) as Record<string, unknown>;
    return { won: parsed.nonce === nonce && parsed.tab_id === tabId };
  } catch {
    return { won: false };
  }
}

/**
 * Release a transactional claim after the snapshot is consumed or hydration
 * fails. Best-effort: never throws.
 */
export function releaseSnapshotClaim(snapshotId: string): void {
  try {
    localStorage.removeItem(`${CLAIM_KEY_PREFIX}${snapshotId}`);
  } catch {
    // best-effort
  }
}

/**
 * Delete all recovery snapshots and stale claims for the given account.
 * Called on explicit user logout so a different account cannot see prior work.
 * Does not log or enumerate snapshot contents.
 */
export function deleteAllSnapshotsForAccount(accountId: string): void {
  const snapshotPrefix = `exam_recovery_${accountId}_`;
  try {
    const keysToDelete: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith(snapshotPrefix)) keysToDelete.push(key);
    }
    for (const key of keysToDelete) {
      try { localStorage.removeItem(key); } catch { /* best-effort per key */ }
    }
  } catch {
    // best-effort
  }
  // Clean up orphaned claims regardless of account
  try {
    const claimKeys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith(CLAIM_KEY_PREFIX)) claimKeys.push(key);
    }
    for (const key of claimKeys) {
      try { localStorage.removeItem(key); } catch { /* best-effort per key */ }
    }
  } catch {
    // best-effort
  }
}

/**
 * Start a BroadcastChannel listener that responds to probe messages sent by
 * potential duplicate tabs. A tab should call this after resolving its
 * identity so it can defend its ID against newcomers.
 *
 * Returns a cleanup function that closes the channel.
 */
export function startTabCollisionListener(myTabId: string): () => void {
  if (typeof BroadcastChannel === "undefined") return () => {};
  const channel = new BroadcastChannel(COLLISION_CHANNEL_NAME);
  channel.onmessage = (e: MessageEvent) => {
    const data = e.data as Record<string, unknown> | null;
    if (
      data !== null &&
      typeof data === "object" &&
      data.type === "probe" &&
      data.tabId === myTabId
    ) {
      channel.postMessage({ type: "alive", tabId: myTabId });
    }
  };
  return () => { try { channel.close(); } catch { /* best-effort */ } };
}

/**
 * Probe whether another tab is already live with the given tab ID.
 * Sends a "probe" message over BroadcastChannel and waits up to timeoutMs
 * for an "alive" reply.  Returns true when a collision is detected.
 *
 * In environments without BroadcastChannel (e.g. older jsdom builds), the
 * check is skipped and returns false.
 */
export async function detectTabCollision(
  tabId: string,
  timeoutMs = 500,
): Promise<boolean> {
  if (typeof BroadcastChannel === "undefined") return false;
  return new Promise<boolean>((resolve) => {
    let settled = false;
    const channel = new BroadcastChannel(COLLISION_CHANNEL_NAME);
    channel.onmessage = (e: MessageEvent) => {
      const data = e.data as Record<string, unknown> | null;
      if (
        !settled &&
        data !== null &&
        typeof data === "object" &&
        data.type === "alive" &&
        data.tabId === tabId
      ) {
        settled = true;
        try { channel.close(); } catch { /* best-effort */ }
        resolve(true);
      }
    };
    channel.postMessage({ type: "probe", tabId });
    setTimeout(() => {
      if (!settled) {
        settled = true;
        try { channel.close(); } catch { /* best-effort */ }
        resolve(false);
      }
    }, timeoutMs);
  });
}
