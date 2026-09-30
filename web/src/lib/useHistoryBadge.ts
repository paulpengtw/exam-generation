/**
 * `useHistoryBadge` — polls GET /api/runs every ~30 s (slower when tab is
 * hidden) and returns `true` when any run's `completed_at` is newer than the
 * per-browser "last seen" marker, signalling that a run ended since the
 * teacher last visited History.
 *
 * fix(913):
 * - Accepts a `disabled` flag; when true the hook is idled (no polling, badge
 *   stays false) so pages that already poll /api/runs don't double up.
 * - Initialises the last-seen marker with server-derived time (the newest
 *   completed_at in the fetched run list) rather than the client clock.
 *   A client clock that is ahead would mask legitimate badge events.
 * - Re-reads the marker from localStorage on every poll so that a HistoryPage
 *   visit (which updates the marker) is reflected without a remount.
 *
 * Issue #913.
 */
import { useEffect, useRef, useState } from "react";
import { listRuns } from "../api/client";
import {
  computeBadge,
  findNewestCompletedAt,
  getLastSeenAt,
  initLastSeenAt,
} from "./historyBadge";

const BADGE_POLL_VISIBLE_MS = 30_000;
const BADGE_POLL_HIDDEN_MS = 60_000;

export function useHistoryBadge(
  userId: string | undefined,
  disabled = false,
): boolean {
  const [badge, setBadge] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!userId || disabled) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- early reset when hook is idled or userId clears, same pattern as HistoryPage
      setBadge(false);
      return;
    }

    let initialized = false;
    let aborted = false;

    async function pollOnce() {
      try {
        const runs = await listRuns();
        if (aborted) return;

        let currentLastSeen: string | null = null;

        if (!initialized) {
          initialized = true;
          // Initialise the marker with the server's newest completed_at so we
          // don't badge for pre-existing historical runs.
          const newest = findNewestCompletedAt(runs);
          try {
            currentLastSeen = initLastSeenAt(userId!, newest);
          } catch {
            // Storage unavailable — badge stays false.
          }
        } else {
          // Re-read the marker in case HistoryPage updated it since last poll.
          try {
            currentLastSeen = getLastSeenAt(userId!);
          } catch {
            // ignore
          }
        }

        setBadge(computeBadge(runs, currentLastSeen));
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
  }, [userId, disabled]);

  return badge;
}
