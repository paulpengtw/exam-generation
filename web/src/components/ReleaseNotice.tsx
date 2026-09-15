/**
 * ReleaseNotice — persistent bar showing the current release-check state.
 *
 * Mounted in RootLayout under StagingBanner (issue #770).
 * Issue #772: adds Save Draft & Update button when update is required.
 *
 * ARIA:
 *   checking / current / unavailable → role="status" aria-live="polite"
 *   update-required / paused         → role="alert"  (assertive by default)
 *
 * Focus is never moved by state changes.
 * Reduced-motion: no transition/animation classes when
 *   matchMedia('(prefers-reduced-motion: reduce)') matches.
 */
import { useState } from "react";
import { useReleaseStore } from "../lib/release/releaseStore";
import { useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { useAuthStore } from "../store/authStore";
import { evaluateSaveAndUpdate, runSaveAndUpdate } from "../lib/recovery/saveAndUpdate";
import { useT } from "../i18n/useT";

function useReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** Map a denied reason to its i18n key */
function reasonKey(reason: string): string {
  return `recovery.disabled.${reason}`;
}

export default function ReleaseNotice() {
  const { status, checkNow, requiredBuildId, releaseRevision, supportedRecoveryFormats } =
    useReleaseStore();
  const t = useT();
  const reducedMotion = useReducedMotion();
  const { surfaces, operations } = useWorkspaceStore();
  const user = useAuthStore((s) => s.user);
  const setFreezeInput = useWorkspaceStore((s) => s.setFreezeInput);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const isAlert = status === "update-required" || status === "paused";
  const role = isAlert ? "alert" : "status";
  const ariaLive = isAlert ? undefined : "polite";

  const baseClass =
    "sentry-unmask w-full px-3 py-1 text-sm text-center" +
    (reducedMotion ? "" : "");

  function handleCheckAgain() {
    void checkNow();
  }

  async function handleSaveAndUpdate() {
    setSaving(true);
    setSaveError(null);
    setFreezeInput(true);
    try {
      const result = await runSaveAndUpdate({ navigate: () => window.location.reload() });
      if (!result.ok) {
        setSaveError(t("recovery.error.generic"));
        setFreezeInput(false);
      }
      // On success, navigation will happen — freezeInput stays true
    } catch {
      setSaveError(t("recovery.error.generic"));
      setFreezeInput(false);
    } finally {
      setSaving(false);
    }
  }

  // Evaluate save-and-update eligibility
  const evalResult = status === "update-required"
    ? evaluateSaveAndUpdate({
        surfaces,
        operations,
        releaseStatus: status,
        requiredBuildId,
        releaseRevision,
        supportedRecoveryFormats: supportedRecoveryFormats ?? [],
        user,
      })
    : null;

  const showSaveAndUpdate = status === "update-required";

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

  const showCheckButton =
    status === "update-required" || status === "paused" || status === "unavailable";

  const saveButtonDisabled =
    saving || !evalResult || !evalResult.allowed;

  const saveButtonTitle =
    saving
      ? t("recovery.saving")
      : evalResult && !evalResult.allowed
        ? t(reasonKey(evalResult.reason))
        : undefined;

  return (
    <div role={role} aria-live={ariaLive} className={baseClass}>
      <span className="sentry-unmask">{message}</span>
      {showSaveAndUpdate && (
        <>
          <button
            type="button"
            onClick={() => { void handleSaveAndUpdate(); }}
            disabled={saveButtonDisabled}
            title={saveButtonTitle}
            className="ml-2 underline cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span className="sentry-unmask">
              {saving ? t("recovery.saving") : t("recovery.saveAndUpdate")}
            </span>
          </button>
          {saveError && (
            <>
              <span className="sentry-unmask ml-2 text-red-600">{saveError}</span>
              <button
                type="button"
                onClick={() => { void handleSaveAndUpdate(); }}
                className="ml-1 underline cursor-pointer"
              >
                <span className="sentry-unmask">{t("recovery.retry")}</span>
              </button>
            </>
          )}
        </>
      )}
      {showCheckButton && (
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
