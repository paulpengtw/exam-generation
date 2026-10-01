/**
 * Per-browser "last seen" marker for the History nav badge (issue #913).
 *
 * The badge appears when a run's `completed_at` is newer than the last time
 * the teacher viewed the History page, stored in localStorage per user.
 *
 * All localStorage access is wrapped in try/catch so the page works even when
 * storage is unavailable or throws (private browsing, quota exceeded, etc.).
 *
 * fix(913): computeBadge uses Date.parse() to avoid format-mismatch false
 * positives (+00:00 vs Z, microseconds vs milliseconds).  initLastSeenAt
 * accepts an optional serverTimestamp so callers can pass server-derived time
 * rather than the potentially-skewed client clock.
 */

import type { RunListItem } from "../api/client";

function storageKey(userId: string): string {
  return `exam_history_last_seen_${userId}`;
}

/**
 * Read the stored last-seen timestamp for a user.
 * Returns null when not found or when localStorage is unavailable.
 */
export function getLastSeenAt(userId: string): string | null {
  try {
    return localStorage.getItem(storageKey(userId));
  } catch {
    return null;
  }
}

/**
 * Persist a new last-seen timestamp for a user.
 * Silently ignores storage errors.
 */
export function setLastSeenAt(userId: string, isoTimestamp: string): void {
  try {
    localStorage.setItem(storageKey(userId), isoTimestamp);
  } catch {
    // Silently ignore quota / unavailable errors.
  }
}

/**
 * Initialize the marker on first visit using a server-derived timestamp (the
 * newest `completed_at` among listed runs), preventing the badge from lighting
 * up for all historical runs on a first visit.
 *
 * - When a marker is already stored: returns the stored value unchanged.
 * - When no marker is stored and `serverTimestamp` is provided: stores and
 *   returns `serverTimestamp`.
 * - When no marker is stored and `serverTimestamp` is null/undefined: returns
 *   null without writing anything (no badge can fire while no completed runs
 *   exist, so there is nothing to initialize against).
 *
 * The second parameter is intentionally server-time, NOT `new Date()`, to
 * avoid client-clock-skew bugs: a client clock that is ahead would set a
 * marker in the "future", causing completed runs to be silently missed.
 */
export function initLastSeenAt(
  userId: string,
  serverTimestamp?: string | null,
): string | null {
  const stored = getLastSeenAt(userId);
  if (stored !== null) return stored;
  if (!serverTimestamp) return null;
  setLastSeenAt(userId, serverTimestamp);
  return serverTimestamp;
}

/**
 * Return the newest `completed_at` timestamp among the given runs, or null
 * when no run has a `completed_at` value.  Uses Date.parse for reliable
 * cross-format comparison.
 */
export function findNewestCompletedAt(runs: RunListItem[]): string | null {
  return runs.reduce<string | null>((best, run) => {
    if (run.completed_at === null) return best;
    if (best === null || Date.parse(run.completed_at) > Date.parse(best)) {
      return run.completed_at;
    }
    return best;
  }, null);
}

/**
 * Return true when any run in the list has a `completed_at` that is strictly
 * newer than `lastSeenAt`, signalling that a run ended since the teacher last
 * visited History.
 *
 * Uses Date.parse() to avoid format-mismatch false positives that arise from
 * raw string comparison when the server returns `+00:00` offsets or
 * microsecond precision while the client stores a `Z`-suffix millisecond
 * timestamp.
 *
 * When `lastSeenAt` is null the badge is never shown (marker not yet set —
 * caller should call `initLastSeenAt` first).
 */
export function computeBadge(runs: RunListItem[], lastSeenAt: string | null): boolean {
  if (lastSeenAt === null) return false;
  const lastSeenMs = Date.parse(lastSeenAt);
  for (const run of runs) {
    if (run.completed_at !== null && Date.parse(run.completed_at) > lastSeenMs) {
      return true;
    }
  }
  return false;
}
