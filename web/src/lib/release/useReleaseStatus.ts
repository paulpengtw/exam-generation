/**
 * useReleaseStatus — installs the event-driven check triggers.
 *
 * Triggers: initial mount, window 'pageshow' (any persisted), 'popstate',
 * 'online', document 'visibilitychange' → visible, and a 60 s setInterval
 * that fires only while the document is visible.
 *
 * All triggers call checkNow() which coalesces concurrent calls — at most
 * one fetch is in-flight at any time.
 *
 * Issue #770.
 */
import { useEffect } from "react";
import { useReleaseStore } from "./releaseStore";

const CHECK_INTERVAL_MS = 60_000;

export function useReleaseStatus() {
  const store = useReleaseStore();

  useEffect(() => {
    const { checkNow } = useReleaseStore.getState();

    // Initial check on mount
    void checkNow();

    function handlePageShow(e: PageTransitionEvent) {
      void checkNow();
      // persisted is checked in the spec but we fire on any pageshow
      void e;
    }

    function handlePopState() {
      void checkNow();
    }

    function handleOnline() {
      void checkNow();
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        void checkNow();
      }
    }

    window.addEventListener("pageshow", handlePageShow);
    window.addEventListener("popstate", handlePopState);
    window.addEventListener("online", handleOnline);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    // 60 s interval — only fires while visible
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") {
        void checkNow();
      }
    }, CHECK_INTERVAL_MS);

    return () => {
      window.removeEventListener("pageshow", handlePageShow);
      window.removeEventListener("popstate", handlePopState);
      window.removeEventListener("online", handleOnline);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      clearInterval(interval);
    };
  }, []); // mount-only: triggers and interval manage their own deps

  return store;
}
