/**
 * ReleaseNotice — persistent bar showing the current release-check state.
 *
 * Mounted in RootLayout under StagingBanner (issue #770).
 *
 * ARIA:
 *   checking / current / unavailable → role="status" aria-live="polite"
 *   update-required / paused         → role="alert"  (assertive by default)
 *
 * Focus is never moved by state changes.
 * Reduced-motion: no transition/animation classes when
 *   matchMedia('(prefers-reduced-motion: reduce)') matches.
 */
import { useReleaseStore } from "../lib/release/releaseStore";
import { useT } from "../i18n/useT";

function useReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export default function ReleaseNotice() {
  const { status, checkNow } = useReleaseStore();
  const t = useT();
  const reducedMotion = useReducedMotion();

  const isAlert = status === "update-required" || status === "paused";
  const role = isAlert ? "alert" : "status";
  const ariaLive = isAlert ? undefined : "polite";

  const baseClass =
    "sentry-unmask w-full px-3 py-1 text-sm text-center" +
    (reducedMotion ? "" : "");

  function handleCheckAgain() {
    void checkNow();
  }

  if (status === "current") {
    // Keep in DOM for assistive tech but visually minimal (sr-only for the
    // text so the bar takes no space when everything is fine).
    return (
      <div role="status" aria-live="polite" className={baseClass}>
        <span className="sentry-unmask sr-only">{t("release.current")}</span>
      </div>
    );
  }

  const message = (() => {
    switch (status) {
      case "checking":
        return t("release.checking");
      case "update-required":
        return t("release.update_required");
      case "paused":
        return t("release.paused");
      case "unavailable":
        return t("release.unavailable");
      default:
        return "";
    }
  })();

  const showButton =
    status === "update-required" || status === "paused" || status === "unavailable";

  return (
    <div role={role} aria-live={ariaLive} className={baseClass}>
      <span className="sentry-unmask">{message}</span>
      {showButton && (
        <button
          type="button"
          onClick={handleCheckAgain}
          className="ml-2 underline cursor-pointer"
        >
          <span className="sentry-unmask">{t("release.check_again")}</span>
        </button>
      )}
    </div>
  );
}
