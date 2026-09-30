import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, m, useReducedMotion } from "motion/react";
import { useBlocker, useLocation, useNavigate } from "react-router-dom";

import AgentStatusPanel from "../components/AgentStatusPanel";
import DestructiveConfirm from "../components/DestructiveConfirm";
import GenerationStatusBar, {
  type JumpTarget,
  type RunState,
} from "../components/GenerationStatusBar";
import ParamForm, { type FormParams } from "../components/ParamForm";
import { toGenerateParams } from "../utils/toGenerateParams";
import ProgressLog from "../components/ProgressLog";
import QuestionCard from "../components/QuestionCard";
import { useFeedbackDialog } from "../hooks/useFeedbackDialog";
import { useGenerate } from "../hooks/useGenerate";
import { useRetryableSnapshot } from "../hooks/useRetryableSnapshot";
import { useAuthStore } from "../store/authStore";
import { useT } from "../i18n/useT";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { buildOdtFromSnapshots, formatTimestamp } from "../utils/odt";
import { captureBatch, captureBatchSnapshots, batchFilename, batchOdtFilename, augmentWithDomMarkup, type QuestionSnapshot } from "../utils/exportSnapshot";
import { serializeElementToMarkup } from "../utils/domCapture";
import {
  ActionButton,
  ActionFailure,
  firstFailure,
  InlineFailureNotice,
  useActionFeedback,
} from "../motion/actionFeedback";
import { useSurfaceParticipation } from "../lib/workspace/useSurfaceParticipation";
import { useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { exportResultsWorkspace } from "../lib/workspace/adapters/resultsWorkspace";
import { projectGenerationCardEvidence, projectGenerationEvidence } from "../lib/generationStream";
import { runPhaseLabel, selectRunPhase } from "../motion/runPhase";
import MotionRoot from "../motion/MotionRoot";
import { choreography, durations, motionEase } from "../motion/tokens";
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

export interface GeneratePageProps {
  subject?: "math" | "social_studies" | "natural_sciences";
}

type PendingAction =
  | { kind: "navigate"; target: string }
  | { kind: "logout" }
  | { kind: "clearResults" }
  | { kind: "resubmit"; params: ReturnType<typeof toGenerateParams> }
  | null;

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function getOdtQuestionIndex(error: unknown): number | null {
  if (typeof error !== "object" || error === null) return null;
  const index = (error as { questionIndex?: unknown }).questionIndex;
  return typeof index === "number" && Number.isInteger(index) && index >= 0 ? index : null;
}

function AnimatedQuestionCard({
  children,
  index,
}: {
  children: ReactNode;
  index: number;
}) {
  const reducedMotion = useReducedMotion();
  const delay = reducedMotion
    ? 0
    : Math.min(index * choreography.stagger, choreography.staggerCap) / 1000;

  return (
    <m.div
      initial={reducedMotion ? false : { opacity: 0, y: choreography.travel }}
      animate={{ opacity: 1, y: 0 }}
      exit={
        reducedMotion
          ? { opacity: 0, transition: { duration: 0 } }
          : {
              opacity: 0,
              y: choreography.travel,
              transition: { duration: durations.quick / 1000, ease: motionEase.exit },
            }
      }
      transition={
        reducedMotion
          ? { duration: 0 }
          : { duration: durations.standard / 1000, ease: motionEase.signature, delay }
      }
    >
      {children}
    </m.div>
  );
}

export default function GeneratePage({ subject = "math" }: GeneratePageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const prefillParams =
    (location.state as { prefillParams?: Record<string, unknown> } | null)
      ?.prefillParams ?? null;
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const logoutExplicit = useAuthStore((s) => s.logoutExplicit);
  const {
    status,
    progressLines,
    results,
    displayResults,
    llmCalls,
    agentLanes,
    errorMessage,
    startedAt,
    finishedAt,
    generationLogId,
    subQuestionTotal,
    resultsCompletion,
    terminalEvidence,
    generate,
    restoreResults: restoreSavedResults,
    reset,
    evidence: runEvidence,
    runId,
    resume,
    pollReadFailed,
  } = useGenerate();
  // A detached run is addressed by `?run=<id>` (issue #908): closing the page
  // and reopening that URL resumes watching the same run.
  const runParam = new URLSearchParams(location.search ?? "").get("run");
  const [runNotFound, setRunNotFound] = useState(false);
  const setRunParam = useCallback((id: string | null) => {
    const next = new URLSearchParams(location.search ?? "");
    if (id === null) next.delete("run");
    else next.set("run", id);
    const search = next.toString();
    navigate({ search: search === "" ? "" : `?${search}` }, { replace: true });
  }, [navigate, location.search]);
  useEffect(() => {
    // Only ever adds the param; clearing is explicit (reset / unknown run).
    if (typeof runId === "string" && runId !== runParam) setRunParam(runId);
  }, [runId, runParam, setRunParam]);
  useEffect(() => {
    if (runParam === null) return;
    let cancelled = false;
    void resume(runParam).then((outcome) => {
      if (cancelled || outcome.outcome !== "not_found") return;
      setRunNotFound(true);
      setRunParam(null);
    });
    return () => { cancelled = true; };
    // Resume is keyed on the URL param alone; resume() is idempotent per run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runParam]);
  // Recovery must be resolved before ParamForm mounts. Otherwise its schema,
  // model, draft, and default effects can observe an empty form and replace a
  // confirmation that is still being restored. The layout gate also means a
  // store update from initRecoveryStore cannot arrive as a late prop that the
  // form has to reconcile after hydration has begun.
  const recoveryRoute = location.pathname ?? window.location.pathname;
  const recoveryBootKey = `${recoveryRoute}:${user?.id ?? ""}`;
  const [recoveryBootedKey, setRecoveryBootedKey] = useState<string | null>(null);

  // Phase 1: synchronous boot — restores pending snapshot immediately so the
  // form can render without waiting for async identity-hardening work.  This
  // keeps all rendering synchronous and avoids macro-task delays (setTimeout)
  // that would block test assertions inside act().
  useLayoutEffect(() => {
    const environment =
      typeof __BUILD_ENVIRONMENT__ === "undefined"
        ? "development"
        : __BUILD_ENVIRONMENT__;
    initRecoveryStore({
      currentRoute: recoveryRoute,
      origin: window.location.origin,
      environment,
    });
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRecoveryBootedKey(recoveryBootKey);
  }, [recoveryBootKey, recoveryRoute]);

  // Phase 2: async identity hardening (issue #776) — runs after the first
  // render.  Performs tab-collision detection, transactional snapshot claim,
  // and starts the BroadcastChannel collision listener.  If the claim is lost
  // (another tab won the race) the optimistic pending state from Phase 1 is
  // cleared so this tab does not show stale recovery content.
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
          // This tab is a duplicate — mint a fresh identity and discard the
          // Phase-1 optimistic recovery so the form starts empty.
          const freshId = resetTabIdForCollision();
          stopCollisionListener = startTabCollisionListener(freshId);
          useRecoveryStore.getState().discardRecovery();
          return;
        }
      }
      if (cancelled) return;
      // Upgrade Phase-1 pending with a transactional claim so two tabs cannot
      // both hydrate the same snapshot.
      await initRecoveryStoreAsync({
        currentRoute: recoveryRoute,
        origin: window.location.origin,
        environment,
      });
      if (cancelled) return;
      // If another tab won the claim, clear the Phase-1 optimistic state.
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
      // No claim is held, but the form is already rendered.
    });

    return () => {
      cancelled = true;
      if (stopCollisionListener) stopCollisionListener();
    };
  }, [recoveryBootKey, recoveryRoute]);
  const { enabled, open } = useFeedbackDialog();
  const formRef = useRef<HTMLElement | null>(null);
  const progressRef = useRef<HTMLElement | null>(null);
  const resultsRef = useRef<HTMLElement | null>(null);
  const handoffTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reducedMotion = useReducedMotion();
  const [handoffPending, setHandoffPending] = useState(false);
  const startHandoff = useCallback(() => {
    if (handoffTimerRef.current !== null) clearTimeout(handoffTimerRef.current);
    setHandoffPending(true);
    handoffTimerRef.current = setTimeout(() => {
      handoffTimerRef.current = null;
      setHandoffPending(false);
    }, reducedMotion ? 0 : choreography.handoffDelay);
  }, [reducedMotion]);
  useEffect(() => () => {
    if (handoffTimerRef.current !== null) clearTimeout(handoffTimerRef.current);
  }, []);
  const [requestedTotalInput, setRequestedTotal] = useState(0);
  // A reopened run has no form submission in this tab: its size is the manifest's.
  const requestedTotal = requestedTotalInput > 0 ? requestedTotalInput : (runEvidence?.total ?? 0);
  const [submittedSubQuestionCount, setSubmittedSubQuestionCount] =
    useState<number | null>(null);
  const evidence = useMemo(
    () => projectGenerationEvidence(
      llmCalls,
      submittedSubQuestionCount ?? subQuestionTotal,
      runEvidence,
    ),
    [llmCalls, runEvidence, submittedSubQuestionCount, subQuestionTotal],
  );
  const [hasUnsubmittedInput, setHasUnsubmittedInput] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const { pending: pendingRecovery, discardRecovery } = useRecoveryStore();
  const pendingRecoveryForRoute = pendingRecovery?.route === recoveryRoute &&
    pendingRecovery.subject === subject
    ? pendingRecovery
    : null;
  const recoveryResults = pendingRecoveryForRoute?.results;
  const recoverySnapshotId = pendingRecoveryForRoute?.snapshot_id ?? null;
  const [resultsRestoreError, setResultsRestoreError] = useState(false);
  const [resultsRestoreVerified, setResultsRestoreVerified] = useState(false);
  const restoredResultsKeyRef = useRef<string | null>(null);
  // Stored batch ODT snapshot for retry (#753): reuse the same captured snapshot on retry
  const { getOrCapture: getOrCaptureBatchOdtSnapshots } =
    useRetryableSnapshot<[QuestionSnapshot[], boolean]>();
  const restoreReceivedResults = useCallback((): boolean => {
    if (!recoveryResults) {
      setResultsRestoreError(false);
      setResultsRestoreVerified(true);
      return true;
    }
    const restored = restoreSavedResults(recoveryResults);
    if (!restored) {
      setResultsRestoreError(true);
      setResultsRestoreVerified(false);
      return false;
    }
    setRequestedTotal(recoveryResults.requestedTotal);
    setSubmittedSubQuestionCount(recoveryResults.submittedSubQuestionCount);
    setResultsRestoreError(false);
    setResultsRestoreVerified(true);
    return true;
  }, [recoveryResults, restoreSavedResults]);
  useLayoutEffect(() => {
    if (!recoveryResults) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- recovery has no result payload to hydrate
      setResultsRestoreVerified(true);
      restoredResultsKeyRef.current = null;
      return;
    }
    if (restoredResultsKeyRef.current === recoverySnapshotId) return;
    restoredResultsKeyRef.current = recoverySnapshotId;
    restoreReceivedResults();
  }, [recoveryResults, recoverySnapshotId, restoreReceivedResults]);
  const handleRecoveryAcknowledge = useCallback((): boolean => {
    if (recoveryResults && !resultsRestoreVerified && !restoreReceivedResults()) return false;
    discardRecovery();
    return true;
  }, [discardRecovery, recoveryResults, restoreReceivedResults, resultsRestoreVerified]);
  const handleRecoveryDiscard = useCallback((): boolean => {
    if (recoveryResults && !resultsRestoreVerified && !restoreReceivedResults()) return false;
    discardRecovery();
    return true;
  }, [discardRecovery, recoveryResults, restoreReceivedResults, resultsRestoreVerified]);
  const hasResults = displayResults.length > 0 || (runEvidence != null && runEvidence.total > 0);
  const exportWorkspace = useCallback(() => exportResultsWorkspace({
    status, results, displayResults, progressLines, errorMessage, startedAt, finishedAt,
    subQuestionTotal, requestedTotal, submittedSubQuestionCount,
    runId: generationLogId,
    terminalEvidence: terminalEvidence ?? false,
  }), [status, results, displayResults, progressLines, errorMessage, startedAt, finishedAt,
    subQuestionTotal, requestedTotal, submittedSubQuestionCount, generationLogId, terminalEvidence]);
  useSurfaceParticipation("generate.results", {
    readiness: "ready",
    hasEditableState: false,
    hasReceivedResults: hasResults,
    exportWorkspace,
  });
  // Subscribe to navigationApproved so the blocker callback sees fresh state
  // after save-and-update writes an approval. The value is read from getState()
  // inside the callback to avoid a stale closure capturing the pre-approval value.
  useWorkspaceStore((s) => s.navigationApproved);
  const blocker = useBlocker(
    ({ historyAction, nextLocation }) => {
      // Approved navigation (e.g. from save-and-update) bypasses the guard once.
      const approved = useWorkspaceStore.getState().navigationApproved;
      if (approved !== null && nextLocation.pathname === approved.target) {
        useWorkspaceStore.getState().clearNavigationApproval();
        return false;
      }
      return (hasUnsubmittedInput || hasResults) && historyAction === "POP";
    },
  );

  // Derive the effective pending action: explicit state takes priority; the
  // back guard derives directly from the live blocker so the blocker object
  // is never snapshotted and is always available when proceed/reset are called.
  const effectivePending =
    pendingAction ?? (blocker.state === "blocked" ? ({ kind: "back" } as const) : null);

  useEffect(() => {
    if (!hasUnsubmittedInput && !hasResults) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      // Approved navigation bypasses beforeunload too — read from store directly
      if (useWorkspaceStore.getState().navigationApproved !== null) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasUnsubmittedInput, hasResults]);

  const handleLogout = () => {
    logoutExplicit();
    navigate("/");
  };

  const handleSubmit = (params: FormParams) => {
    const generateParams = toGenerateParams(subject, params);
    // Dormant by design (#270): both submit buttons are disabled while
    // status === "generating" (the ParamForm `disabled` prop below), so this
    // #220 guard is unreachable from the UI. Kept as belt-and-braces for any
    // future change that re-enables mid-run submission — do not delete.
    // See docs/adr/0010-the-resubmit-guard-is-dormant-by-design.md.
    if (status === "generating") {
      setPendingAction({ kind: "resubmit", params: generateParams });
      return;
    }
    setRequestedTotal(params.count);
    setSubmittedSubQuestionCount(generateParams.sub_question_count ?? null);
    setRunNotFound(false);
    return generate(generateParams);
  };

  const handleReset = () => {
    reset();
    setRunParam(null);
    setRunNotFound(false);
    setRequestedTotal(0);
    setSubmittedSubQuestionCount(null);
  };

  const handleJump = (target: JumpTarget) => {
    const targetRef = {
      form: formRef,
      progress: progressRef,
      results: resultsRef,
    }[target];
    targetRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const jsonFeedback = useActionFeedback({
    action: async () => {
      // Atomically capture the batch snapshot at click time (issue #751)
      const exportedAt = new Date().toISOString();
      const evidenceByQuestionId = runEvidence?.questions ?? {};
      const batch = captureBatch({
        displayResults,
        evidenceByQuestionId,
        // v2 run_id is the protocol run id (RunEvidenceState.runId), not the DB log id
        runId: runEvidence?.runId ?? null,
        exportedAt,
      });
      const filename = batchFilename(batch.hasDraft);
      const operation = useWorkspaceStore.getState().beginOperation("export_json", "generate.results");
      try {
        const json = JSON.stringify(batch.exported, null, 2);
        downloadBlob(new Blob([json], { type: "application/json" }), filename);
        operation.end("completed");
        return filename;
      } catch (error: unknown) {
        operation.end("failed");
        throw error;
      }
    },
    genericError: t("generate.download_json_error"),
    getFilename: (filename) => filename,
  });

  const odtFeedback = useActionFeedback({
    action: async () => {
      const batchCapture = getOrCaptureBatchOdtSnapshots(
        odtFeedback.state === "failed",
        () => {
          // Fresh export click: capture a new snapshot at this instant.
          const exportedAt = new Date().toISOString();
          const evidenceByQuestionId = runEvidence?.questions ?? {};
          const [ss, hd] = captureBatchSnapshots({
            displayResults,
            evidenceByQuestionId,
            runId: runEvidence?.runId ?? null,
            exportedAt,
          });
          // Try to augment chart_spec_preview slots with DOM markup from mounted
          // cards (same-source capture). Requires [data-question-id] wrappers in
          // the JSX below. Falls back to offscreen FigureRenderer rendering when
          // the element is not found (e.g. during unit tests with mocked cards).
          for (const snapshot of ss) {
            const questionId = snapshot.captured.id;
            if (questionId) {
              // Use attribute-value match (no CSS.escape needed for data attribute selectors)
              const cardEl = Array.from(
                document.querySelectorAll("[data-question-id]"),
              ).find((el) => el.getAttribute("data-question-id") === questionId) ?? null;
              if (cardEl) {
                augmentWithDomMarkup(snapshot.imageSources, (slotKey) => {
                  const el = cardEl.querySelector(`[data-figure-slot="${slotKey}"]`);
                  if (!el) return null;
                  try { return serializeElementToMarkup(el); } catch { return null; }
                });
              }
            }
          }
          return [ss, hd] as [QuestionSnapshot[], boolean];
        },
      );
      if (!batchCapture) throw new Error("No snapshots captured");
      const [snapshots, hasDraft] = batchCapture;

      const filename = batchOdtFilename(hasDraft);
      const operation = useWorkspaceStore.getState().beginOperation("export_odt", "generate.results");
      try {
        const ts = formatTimestamp();
        const blob = await buildOdtFromSnapshots(`exam_${ts}`, snapshots);
        downloadBlob(blob, filename);
        operation.end("completed");
        return filename;
      } catch (error: unknown) {
        operation.end("failed");
        const questionIndex = getOdtQuestionIndex(error);
        if (questionIndex !== null && snapshots[questionIndex]) {
          const snap = snapshots[questionIndex];
          const id = snap.exported.id ?? String(questionIndex + 1);
          const detail = t("generate.download_odt_group_error")
            .replace("{n}", String(questionIndex + 1))
            .replace("{id}", id);
          throw new ActionFailure(detail);
        }
        throw error;
      }
    },
    genericError: t("generate.download_odt_error"),
    getFilename: (filename) => filename,
  });
  const exportFailure = firstFailure(jsonFeedback, odtFeedback);

  const showProgress = runEvidence !== null || !(progressLines.length === 0 && status === "idle");
  const runState: RunState =
    status === "generating" && handoffPending
      ? "idle"
      : status === "error"
      ? "error"
      : resultsCompletion === "unknown"
        ? "unknown"
      : status === "generating"
        ? "running"
        : startedAt !== null && finishedAt !== null
          ? "done"
          : "idle";
  const availableTargets: JumpTarget[] = ["form"];
  if (showProgress) availableTargets.push("progress");
  if (hasResults) availableTargets.push("results");
  const handleNavigation = (target: string) => {
    if (!hasUnsubmittedInput && !hasResults) {
      navigate(target);
      return;
    }

    setPendingAction({ kind: "navigate", target });
  };
  const navigationBodyKeys = [
    ...(hasUnsubmittedInput ? ["confirm.navigate_away_body_params"] : []),
    ...(hasResults ? ["confirm.navigate_away_body_results"] : []),
  ];

  if (recoveryBootedKey !== recoveryBootKey) {
    return <div className="min-h-screen bg-gray-50" aria-busy="true" />;
  }

  // Derive dialog props from the single effective pending action.
  const dialogProps = (() => {
    if (effectivePending === null) {
      return {
        titleKey: "" as string,
        bodyKeys: [] as string[],
        confirmKey: "" as string,
        onConfirm: () => {},
        onCancel: () => {},
      };
    }
    switch (effectivePending.kind) {
      case "navigate": {
        const target = effectivePending.target;
        return {
          titleKey: "confirm.navigate_away_title",
          bodyKeys: navigationBodyKeys,
          confirmKey: "confirm.navigate_away_confirm",
          onConfirm: () => {
            setPendingAction(null);
            navigate(target);
          },
          onCancel: () => setPendingAction(null),
        };
      }
      case "back":
        return {
          titleKey: "confirm.navigate_away_title",
          bodyKeys: navigationBodyKeys,
          confirmKey: "confirm.navigate_away_confirm",
          onConfirm: () => blocker.proceed?.(),
          onCancel: () => blocker.reset?.(),
        };
      case "logout":
        return {
          titleKey: "confirm.logout_title",
          bodyKeys: [
            "confirm.logout_body_session",
            ...((hasUnsubmittedInput || hasResults)
              ? ["confirm.logout_body_work_lost"]
              : []),
          ],
          confirmKey: "confirm.logout_confirm",
          onConfirm: handleLogout,
          onCancel: () => setPendingAction(null),
        };
      case "clearResults":
        return {
          titleKey: "confirm.clear_results_title",
          bodyKeys: [
            "confirm.clear_results_body",
            ...(status === "generating"
              ? ["confirm.clear_results_body_streaming"]
              : []),
          ],
          confirmKey: "confirm.clear_results_confirm",
          onConfirm: () => {
            setPendingAction(null);
            handleReset();
          },
          onCancel: () => setPendingAction(null),
        };
      case "resubmit": {
        const params = effectivePending.params;
        return {
          titleKey: "confirm.resubmit_title",
          bodyKeys: ["confirm.resubmit_body"],
          confirmKey: "confirm.resubmit_confirm",
          onConfirm: () => {
            setPendingAction(null);
            setRequestedTotal(params.count ?? 0);
            setSubmittedSubQuestionCount(params.sub_question_count ?? null);
            generate(params);
          },
          onCancel: () => setPendingAction(null),
        };
      }
    }
  })();

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-2 px-3 py-3 sm:px-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => handleNavigation("/generate")}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
              title={t("generate.btn_back_subjects")}
            >
              ←
            </button>
            <h1 className="text-base font-semibold sm:text-lg">
              {subject === "social_studies"
                ? t("generate.title_ss")
                : subject === "natural_sciences"
                  ? t("generate.title_ns")
                  : t("generate.title")}
            </h1>
          </div>
          <div className="flex min-w-0 items-center gap-2 text-sm sm:gap-3">
            <LanguageSwitcher />
            <button
              type="button"
              onClick={() => handleNavigation("/history")}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("history.nav_link")}
            </button>
            {user && (
              <span className="hidden max-w-[12rem] truncate text-gray-700 sm:inline">
                {user.email}
              </span>
            )}
            <button
              type="button"
              onClick={() => setPendingAction({ kind: "logout" })}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("generate.btn_logout")}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-3 pt-4 pb-20 sm:px-4 sm:pt-6">
        {runNotFound ? (
          <div role="alert" data-testid="run-not-found" className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            {t("generate.run_not_found")}
          </div>
        ) : null}
        {resultsRestoreError ? (
          <div role="alert" className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800">
            <span>{t("recovery.results_restore_failed")}</span>{" "}
            <button
              type="button"
              onClick={restoreReceivedResults}
              className="font-medium underline"
            >
              {t("recovery.retry")}
            </button>
          </div>
        ) : null}
        <section ref={formRef} className="rounded-lg border bg-white p-3 shadow-sm sm:p-4">
          <ParamForm
            subject={subject}
            onSubmit={handleSubmit}
            disabled={status === "generating"}
            initialParams={prefillParams ?? undefined}
            onUnsubmittedInput={() => setHasUnsubmittedInput(true)}
            recoveredForm={pendingRecoveryForRoute?.form}
            recoveredConfirmation={pendingRecoveryForRoute?.confirmation}
            onRecoveryAcknowledge={handleRecoveryAcknowledge}
            onRecoveryDiscard={handleRecoveryDiscard}
            onHandoffStart={startHandoff}
          />
        </section>

        {!runEvidence && agentLanes.length > 0 && (
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <AgentStatusPanel
              lanes={agentLanes}
              requestedTotal={requestedTotal}
            />
          </section>
        )}

        {showProgress && (
          <section ref={progressRef} className="rounded-lg border bg-white p-4 shadow-sm">
            <ProgressLog
              lines={progressLines}
              status={status}
              errorMessage={errorMessage}
              llmCalls={llmCalls}
              evidence={runEvidence}
              subject={subject}
              subQuestionCount={submittedSubQuestionCount ?? subQuestionTotal}
              requestedTotal={requestedTotal}
              completedCount={results.length}
            />
            {pollReadFailed && (
              <div role="status">{t("generate.run_read_unavailable")}</div>
            )}
          </section>
        )}

        {hasResults && (
          <section ref={resultsRef} className="space-y-3">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-base font-semibold">{t("generate.results")} ({displayResults.length})</h2>
                <div className="flex gap-2">
                  <ActionButton
                    feedback={jsonFeedback}
                    label={t("generate.btn_download_all")}
                    pendingLabel={t("action.downloading")}
                    doneLabel={t("action.downloaded")}
                    disabled={results.length === 0}
                    className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  />
                  <ActionButton
                    feedback={odtFeedback}
                    label={t("generate.btn_download_all_odt")}
                    pendingLabel={t("action.downloading")}
                    doneLabel={t("action.downloaded")}
                    disabled={results.length === 0}
                    className="rounded border border-blue-600 bg-white px-3 py-1.5 text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                  />
                  <button
                    type="button"
                    onClick={() => setPendingAction({ kind: "clearResults" })}
                    className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                  >
                    {t("generate.btn_clear")}
                  </button>
                </div>
              </div>
              {exportFailure && (
                <InlineFailureNotice
                  reason={exportFailure.reason}
                  onRetry={exportFailure.retry}
                  onDismiss={exportFailure.dismiss}
                />
              )}
            </div>
            <MotionRoot>
              <div className="space-y-3">
                <AnimatePresence initial={false}>
                  {runEvidence
                    ? runEvidence.order.map((qid, idx) => {
                        const qEvidence = runEvidence.questions[qid];
                        const displayItem = displayResults.find(
                          (r) => (r.question.id ?? "") === qid,
                        );
                        if (!qEvidence) return null;
                        const cardProps = displayItem
                          ? projectGenerationCardEvidence(displayItem)
                          : {};
                        const livePhaseLabel =
                          displayItem &&
                          status === "generating" &&
                          requestedTotal > 1 &&
                          !displayItem.isFinal
                            ? runPhaseLabel(
                                selectRunPhase({
                                  subject,
                                  subQuestionCount:
                                    submittedSubQuestionCount ?? subQuestionTotal,
                                  draftPhase: displayItem.phase,
                                }),
                                t,
                              )
                            : undefined;
                        return (
                          <AnimatedQuestionCard key={qid} index={idx}>
                            {/* data-question-id enables batch ODT DOM capture (#753) */}
                            <div data-question-id={qid}>
                              <QuestionCard
                                index={idx}
                                evidence={qEvidence}
                                question={displayItem?.question}
                                subject={subject}
                                livePhaseLabel={livePhaseLabel}
                                requestedTotal={requestedTotal}
                                runId={runEvidence?.runId ?? null}
                                {...cardProps}
                              />
                            </div>
                          </AnimatedQuestionCard>
                        );
                      })
                    : displayResults.map((item, idx) => (
                      <AnimatedQuestionCard
                        key={item.question.id ?? `q-${item.index}`}
                        index={idx}
                      >
                        {/* data-question-id enables batch ODT DOM capture (#753) */}
                        <div data-question-id={item.question.id ?? `q-${item.index}`}>
                          <QuestionCard
                            question={item.question}
                            subject={subject}
                            positionUnknown={item.positionUnknown}
                          livePhaseLabel={
                            status === "generating" &&
                            requestedTotal > 1 &&
                            !item.isFinal
                              ? runPhaseLabel(
                                  selectRunPhase({
                                    subject,
                                    subQuestionCount:
                                      submittedSubQuestionCount ?? subQuestionTotal,
                                    draftPhase: item.phase,
                                  }),
                                  t,
                                )
                              : undefined
                          }
                          requestedTotal={requestedTotal}
                          runId={null}
                          {...projectGenerationCardEvidence(item)}
                        />
                        </div>
                      </AnimatedQuestionCard>
                      ))}
                </AnimatePresence>
              </div>
            </MotionRoot>
          </section>
        )}
      </main>
      <DestructiveConfirm
        open={effectivePending !== null}
        titleKey={dialogProps.titleKey}
        bodyKeys={dialogProps.bodyKeys}
        confirmKey={dialogProps.confirmKey}
        onConfirm={dialogProps.onConfirm}
        onCancel={dialogProps.onCancel}
      />
      <GenerationStatusBar
        runState={runState}
        completedCount={results.length}
        requestedTotal={requestedTotal}
        subject={subject}
        evidence={evidence}
        events={llmCalls}
        startedAt={startedAt}
        finishedAt={finishedAt}
        availableTargets={availableTargets}
        onJump={handleJump}
        onFeedback={enabled ? open : null}
      />
    </div>
  );
}
