/**
 * Per-browser "last seen" marker for the History nav badge (issue #913).
 *
 * The badge appears when a run's `completed_at` is newer than the last time
 * the teacher viewed the History page, stored in localStorage per user.
 *
 * All localStorage access is wrapped in try/catch so the page works even when
 * storage is unavailable or throws (private browsing, quota exceeded, etc.).
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
 * Initialize the marker to now if it has not been set yet, preventing the
 * badge from lighting up for all historical runs on a first visit.
 * Returns the effective lastSeenAt (either the stored value or the new one).
 */
export function initLastSeenAt(userId: string, now: string = new Date().toISOString()): string {
  const stored = getLastSeenAt(userId);
  if (stored !== null) return stored;
  setLastSeenAt(userId, now);
  return now;
}

/**
 * Return true when any run in the list has a `completed_at` that is strictly
 * newer than `lastSeenAt`, signalling that a run ended since the teacher last
 * visited History.
 *
 * When `lastSeenAt` is null the badge is never shown (marker not yet set —
 * caller should call `initLastSeenAt` first).
 */
export function computeBadge(runs: RunListItem[], lastSeenAt: string | null): boolean {
  if (lastSeenAt === null) return false;
  for (const run of runs) {
    if (run.completed_at !== null && run.completed_at > lastSeenAt) return true;
  }
  return false;
}
