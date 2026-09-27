import { useEffect, useLayoutEffect, useState } from "react";
import { useRetryableSnapshot } from "../hooks/useRetryableSnapshot";
import { useLocation, useNavigate } from "react-router-dom";

import { useSurfaceParticipation } from "../lib/workspace/useSurfaceParticipation";

import QuestionCard from "../components/QuestionCard";
import FigurePolicyTrailTimeline from "../components/FigurePolicyTrailTimeline";
import ReferenceExampleRecordSection from "../components/ReferenceExampleRecordSection";
import type { ExamQuestion } from "../hooks/useGenerate";
import type { ReferenceExampleRecordShape } from "../components/ReferenceExampleRecordSection";
import { useT } from "../i18n/useT";
import {
  ActionButton,
  InlineFailureNotice,
  useActionFeedback,
} from "../motion/actionFeedback";
import {
  ApiError,
  downloadHistoryJson,
  getHistoryDetail,
  type HistoryDetail as HistoryDetailPayload,
} from "../api/client";
import { captureFromHistory, captureFromHistorySnapshot, augmentWithDomMarkup, singleQuestionOdtFilename, type QuestionSnapshot } from "../utils/exportSnapshot";
import { buildOdtFromSnapshots } from "../utils/odt";
import { serializeElementToMarkup } from "../utils/domCapture";
import { useAuthStore } from "../store/authStore";
import {
  initRecoveryStore,
  initRecoveryStoreAsync,
  useRecoveryStore,
} from "../lib/recovery/recoveryStore";
import {
  peekTabId,
  getOrCreateTabId,
  detectTabCollision,
  startTabCollisionListener,
  resetTabIdForCollision,
} from "../lib/recovery/storage";
import type { ModificationWorkspaceSnapshot } from "../lib/workspace/adapters/types";
import {
  validateModificationBase,
  type ModificationRestoreBlockReason,
} from "../lib/recovery/modificationValidation";

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export interface HistoryDetailProps {
  recordId: string;
}

interface HistoryDetailContentProps extends HistoryDetailProps {
  route: string;
  recoveredModification: ModificationWorkspaceSnapshot | null;
}

type ModificationRestoreState = "none" | "checking" | "ready" | "blocked" | "failed";
type ModificationRestoreReason = ModificationRestoreBlockReason | "unauthorized" | "restore_failed";

function getModificationRestoreReason(error: unknown): ModificationRestoreReason {
  if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
    return "unauthorized";
  }
  return "restore_failed";
}

function modificationRestoreReasonKey(reason: ModificationRestoreReason): string {
  return `recovery.modification_blocked.${reason}`;
}

function HistoryDetailContent({
  recordId,
  route,
  recoveredModification: recoveredModificationProp,
}: HistoryDetailContentProps) {
  const t = useT();
  const navigate = useNavigate();
  const [recoveredModification] = useState(recoveredModificationProp);
  const [detail, setDetail] = useState<HistoryDetailPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restoreState, setRestoreState] = useState<ModificationRestoreState>(
    recoveredModification === null ? "none" : "checking",
  );
  const [restoreReason, setRestoreReason] = useState<ModificationRestoreReason | null>(null);
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [recoveryDismissed, setRecoveryDismissed] = useState(false);
  const discardRecovery = useRecoveryStore((state) => state.discardRecovery);
  // Stored ODT snapshot for retry (#753): reuse the same captured snapshot on retry
  const { getOrCapture: getOrCaptureHistoryOdtSnapshot } =
    useRetryableSnapshot<QuestionSnapshot>();

  useSurfaceParticipation("history.detail", {
    readiness: detail !== null || error !== null ||
      (recoveredModification !== null && restoreState !== "checking")
      ? "ready"
      : "hydrating",
    hasEditableState: false,
    hasReceivedResults: false,
  });

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch on mount/param change, matches existing VerifyPage/HistoryPage pattern
    setError(null);
    setDetail(null);
    getHistoryDetail(recordId)
      .then((res) => {
        if (cancelled) return;
        setDetail(res);
        if (recoveredModification !== null) {
          const validation = validateModificationBase(recoveredModification, res, route);
          if (validation.valid) {
            setRestoreReason(null);
            setRestoreState("ready");
          } else {
            setRestoreReason(validation.reason);
            setRestoreState("blocked");
          }
        }
      })
      .catch((err) => {
        if (cancelled) return;
        if (recoveredModification !== null) {
          const reason = getModificationRestoreReason(err);
          setRestoreReason(reason);
          setRestoreState(reason === "restore_failed" ? "failed" : "blocked");
          return;
        }
        setError(err instanceof Error ? err.message : "error");
      });
    return () => {
      cancelled = true;
    };
  }, [recordId, recoveredModification, restoreAttempt, route]);

  const showRecovery = recoveredModification !== null && !recoveryDismissed;
  const recoveryCanAcknowledge = restoreState === "ready";
  const recoveryMessage = (() => {
    if (restoreState === "checking") return t("recovery.modification_checking");
    if (restoreState === "ready") return t("recovery.modification_restored");
    if (restoreState === "failed") return t("recovery.modification_restore_failed");
    if (restoreReason !== null) return t(modificationRestoreReasonKey(restoreReason));
    return "";
  })();

  const handleAcknowledgeRecovery = () => {
    if (!recoveryCanAcknowledge) return;
    discardRecovery();
    setRecoveryDismissed(true);
  };

  const handleDiscardRecovery = () => {
    discardRecovery();
    setRecoveryDismissed(true);
  };

  const handleRetryRecovery = () => {
    setRestoreReason(null);
    setRestoreState("checking");
    setRestoreAttempt((attempt) => attempt + 1);
  };

  const isFailed = detail?.status === "failed";
  const isAborted = detail?.status === "aborted";
  const isInterrupted = isFailed || isAborted;
  const hasFigurePolicyDegradation = detail?.figure_policy_trail?.some(
    (entry) =>
      (entry.kind === "warning" && entry.duplicate_image_shipped) ||
      entry.kind === "data_inconsistency",
  ) ?? false;
  const canDownload = detail != null && !isInterrupted;
  const showDownload = detail == null || canDownload;

  const downloadFeedback = useActionFeedback({
    action: async (signal) => {
      if (!detail || !canDownload) throw new Error("History record is not available");
      const filename = `${detail.question_id || detail.id}.json`;
      // Use snapshot when question_json is available so the downloaded copy
      // gets _export metadata (issue #751). Fall back to the server endpoint
      // for records where question_json is absent (rare legacy edge case).
      if (detail.question_json) {
        const exportedAt = new Date().toISOString();
        const exported = captureFromHistory(detail, exportedAt);
        if (exported) {
          const json = JSON.stringify(exported, null, 2);
          saveBlob(new Blob([json], { type: "application/json" }), filename);
          return filename;
        }
      }
      const blob = await downloadHistoryJson(detail.id, signal);
      saveBlob(blob, filename);
      return filename;
    },
    genericError: t("history.download_json_error"),
    getFilename: (filename) => filename,
  });

  const odtFeedback = useActionFeedback({
    action: async () => {
      if (!detail || !canDownload) throw new Error("History record is not available");
      if (!detail.question_json) throw new Error("ODT unavailable: no question_json");

      // Retry (#753): reuse the same captured snapshot so the ODT image is
      // identical to what the user saw at click time, even if the record changed.
      const snapshot = getOrCaptureHistoryOdtSnapshot(
        odtFeedback.state === "failed",
        () => {
          // Fresh export click: capture a new snapshot at this instant.
          const exportedAt = new Date().toISOString();
          const captured = captureFromHistorySnapshot(detail, exportedAt);
          if (!captured) return null;
          // Try to augment chart_spec_preview slots with DOM markup from the mounted QuestionCard.
          // The card's [data-figure-slot] elements are searched relative to the card root.
          const cardEl = document.querySelector("[data-testid='question-card-content']");
          if (cardEl) {
            augmentWithDomMarkup(captured.imageSources, (slotKey) => {
              const el = cardEl.querySelector(`[data-figure-slot="${slotKey}"]`);
              if (!el) return null;
              try { return serializeElementToMarkup(el); } catch { return null; }
            });
          }
          return captured;
        },
      );
      if (!snapshot) throw new Error("ODT unavailable: snapshot capture failed");

      const questionId = detail.question_id || detail.id;
      const filename = singleQuestionOdtFilename(questionId, false);
      const blob = await buildOdtFromSnapshots(questionId, [snapshot]);
      saveBlob(blob, filename);
      return filename;
    },
    genericError: t("history.download_odt_error"),
    getFilename: (filename) => filename,
  });

  const handleRegenerate = () => {
    if (!detail) return;
    navigate(`/generate/${detail.subject}`, {
      state: { prefillParams: detail.params_json },
    });
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-2 px-3 py-3 sm:px-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate("/history")}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              ← {t("history.btn_back_list")}
            </button>
            {hasFigurePolicyDegradation && (
              <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                {t("history.figure_policy_degraded_badge")}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {showDownload && (
              <>
                <ActionButton
                  feedback={downloadFeedback}
                  label={t("history.btn_download_json")}
                  pendingLabel={t("action.downloading")}
                  doneLabel={t("action.downloaded")}
                  disabled={!detail}
                  className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                />
                {detail?.question_json && (
                  <ActionButton
                    feedback={odtFeedback}
                    label={t("history.btn_download_odt")}
                    pendingLabel={t("action.downloading")}
                    doneLabel={t("action.downloaded")}
                    disabled={!detail}
                    className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  />
                )}
              </>
            )}
            <button
              type="button"
              disabled={!detail}
              onClick={handleRegenerate}
              className="rounded border border-blue-600 bg-white px-3 py-1.5 text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-50"
            >
              {t("history.btn_regenerate")}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-4 px-3 py-4 sm:px-4 sm:py-6">
        <InlineFailureNotice
          reason={downloadFeedback.reason}
          onRetry={downloadFeedback.retry}
          onDismiss={downloadFeedback.dismiss}
        />
        <InlineFailureNotice
          reason={odtFeedback.reason}
          onRetry={odtFeedback.retry}
          onDismiss={odtFeedback.dismiss}
        />
        {showRecovery && (
          <section
            role={restoreState === "blocked" || restoreState === "failed" ? "alert" : "status"}
            className="sentry-unmask rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900"
          >
            <h2 className="font-semibold">{t("recovery.banner.modification_title")}</h2>
            <p className="mt-1">{recoveryMessage}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {recoveryCanAcknowledge && (
                <button
                  type="button"
                  onClick={handleAcknowledgeRecovery}
                  className="rounded border border-blue-700 px-2 py-1 text-xs font-medium text-blue-800 hover:bg-blue-100"
                >
                  {t("recovery.banner.acknowledge")}
                </button>
              )}
              {(restoreState === "blocked" || restoreState === "failed") && (
                <button
                  type="button"
                  onClick={handleRetryRecovery}
                  className="rounded border border-blue-700 px-2 py-1 text-xs font-medium text-blue-800 hover:bg-blue-100"
                >
                  {t("recovery.modification_retry")}
                </button>
              )}
              <button
                type="button"
                onClick={handleDiscardRecovery}
                className="rounded border border-gray-400 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100"
              >
                {t("recovery.banner.discard")}
              </button>
            </div>
          </section>
        )}
        {error && (
          <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {t("history.detail_error")} {error}
          </div>
        )}
        {!detail && !error && (
          <div className="text-sm text-gray-500">{t("history.detail_loading")}</div>
        )}
        {detail && (
          isInterrupted ? (
            <section className="space-y-4 rounded border bg-white p-4 shadow-sm">
              <h2
                className={`text-base font-semibold ${
                  isAborted ? "text-amber-800" : "text-red-700"
                }`}
              >
                {t(
                  isAborted
                    ? "history.aborted_detail_title"
                    : "history.failed_detail_title",
                )}
              </h2>
              {isAborted ? (
                <p className="text-sm text-amber-800">
                  {t("history.aborted_explanation")}
                </p>
              ) : (
                <div>
                  <h3 className="text-sm font-medium text-gray-700">
                    {t("history.error_label")}
                  </h3>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-red-700">
                    {detail.error || t("history.error_unknown")}
                  </p>
                </div>
              )}
              <div>
                <h3 className="text-sm font-medium text-gray-700">
                  {t("history.params_label")}
                </h3>
                <pre className="mt-1 overflow-x-auto rounded bg-gray-50 p-3 text-xs text-gray-800">
                  {JSON.stringify(detail.params_json, null, 2)}
                </pre>
              </div>
              <FigurePolicyTrailTimeline entries={detail.figure_policy_trail} />
              <ReferenceExampleRecordSection
                record={detail.reference_example_record as ReferenceExampleRecordShape | null}
              />
            </section>
          ) : (
            <QuestionCard
              key={detail.id}
              question={detail.question_json as unknown as ExamQuestion}
              recordId={detail.id}
              route={route}
              subject={detail.subject}
              phase="verified"
              isFinal
              trail={detail.verification_trail}
              figurePolicyTrail={detail.figure_policy_trail}
              referenceExampleRecord={detail.reference_example_record as ReferenceExampleRecordShape | null}
              recoveredModification={recoveredModification ?? undefined}
              modificationRestoreEligible={recoveredModification === null || restoreState === "ready"}
            />
          )
        )}
      </main>
    </div>
  );
}

export default function HistoryDetail({ recordId }: HistoryDetailProps) {
  const location = useLocation();
  const userId = useAuthStore((state) => state.user?.id ?? "");
  const route = location.pathname;
  const recoveryBootKey = `${route}:${userId}`;
  const [recoveryBootedKey, setRecoveryBootedKey] = useState<string | null>(null);

  // Phase 1: synchronous boot — restores pending snapshot immediately so the
  // page can render without waiting for async identity-hardening work.
  useLayoutEffect(() => {
    const environment =
      typeof __BUILD_ENVIRONMENT__ === "undefined"
        ? "development"
        : __BUILD_ENVIRONMENT__;
    initRecoveryStore({
      currentRoute: route,
      origin: window.location.origin,
      environment,
    });
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRecoveryBootedKey(recoveryBootKey);
  }, [recoveryBootKey, route]);

  // Phase 2: async identity hardening (issue #776) — runs after first render.
  useEffect(() => {
    let cancelled = false;
    let stopCollisionListener: (() => void) | null = null;
    const environment =
      typeof __BUILD_ENVIRONMENT__ === "undefined"
        ? "development"
        : __BUILD_ENVIRONMENT__;

    async function hardenIdentity(): Promise<void> {
      const existingTabId = peekTabId();
      if (existingTabId !== null) {
        const isDuplicate = await detectTabCollision(existingTabId, 100);
        if (cancelled) return;
        if (isDuplicate) {
          const freshId = resetTabIdForCollision();
          stopCollisionListener = startTabCollisionListener(freshId);
          useRecoveryStore.getState().discardRecovery();
          return;
        }
      }
      if (cancelled) return;
      await initRecoveryStoreAsync({
        currentRoute: route,
        origin: window.location.origin,
        environment,
      });
      if (cancelled) return;
      if (
        useRecoveryStore.getState().claimedSnapshotId === null &&
        useRecoveryStore.getState().pending !== null
      ) {
        useRecoveryStore.setState({ pending: null, blocked: null });
      }
      const tabId = getOrCreateTabId();
      stopCollisionListener = startTabCollisionListener(tabId);
    }

    hardenIdentity().catch(() => {
      // Hardening failed: Phase-1 sync state remains in effect.
    });

    return () => {
      cancelled = true;
      if (stopCollisionListener) stopCollisionListener();
    };
  }, [recoveryBootKey, route]);

  const pendingRecovery = useRecoveryStore((state) => state.pending);
  const recoveredModification = pendingRecovery?.route === route
    ? pendingRecovery.modification ?? null
    : null;

  if (recoveryBootedKey !== recoveryBootKey) {
    return <div className="min-h-screen bg-gray-50" aria-busy="true" />;
  }

  return (
    <HistoryDetailContent
      recordId={recordId}
      route={route}
      recoveredModification={recoveredModification}
    />
  );
}
