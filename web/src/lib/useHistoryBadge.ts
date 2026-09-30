/**
 * `useHistoryBadge` — polls GET /api/runs every ~30 s (slower when tab is
 * hidden) and returns `true` when any run's `completed_at` is newer than the
 * per-browser "last seen" marker, signalling that a run ended since the
 * teacher last visited History.
 *
 * Issue #913.
 */
import { useEffect, useRef, useState } from "react";
import { listRuns } from "../api/client";
import { computeBadge, initLastSeenAt } from "./historyBadge";

const BADGE_POLL_VISIBLE_MS = 30_000;
const BADGE_POLL_HIDDEN_MS = 60_000;

export function useHistoryBadge(userId: string | undefined): boolean {
  const [badge, setBadge] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!userId) return;

    // Ensure the first-visit marker is set so we don't badge for old runs.
    // Wrapped in try/catch so storage errors (quota, private browsing) are silent.
    let currentLastSeen: string | null = null;
    try {
      currentLastSeen = initLastSeenAt(userId);
    } catch {
      // Storage unavailable — badge stays false.
    }
    let aborted = false;

    async function pollOnce() {
      try {
        const runs = await listRuns();
        if (aborted) return;
        const hasBadge = computeBadge(runs, currentLastSeen);
        setBadge(hasBadge);
      } catch {
        // Polling failure is silently ignored — badge stays as-is.
      }
    }

    function schedule() {
      if (aborted) return;
      const delay =
        document.visibilityState === "hidden"
          ? BADGE_POLL_HIDDEN_MS
          : BADGE_POLL_VISIBLE_MS;
      timerRef.current = setTimeout(() => {
        void pollOnce().then(() => { schedule(); });
      }, delay);
    }

    void pollOnce().then(() => { schedule(); });

    // Recheck immediately when tab becomes visible again.
    function onVisibility() {
      if (document.visibilityState === "visible") {
        if (timerRef.current !== null) {
          clearTimeout(timerRef.current);
          timerRef.current = null;
        }
        void pollOnce().then(() => { schedule(); });
      }
    }
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      aborted = true;
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [userId]);

  return badge;
}
