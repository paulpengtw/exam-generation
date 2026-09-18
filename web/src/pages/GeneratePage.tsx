import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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
import { useAuthStore } from "../store/authStore";
import { useT } from "../i18n/useT";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { buildExamOdt, formatTimestamp } from "../utils/odt";
import { useSurfaceParticipation } from "../lib/workspace/useSurfaceParticipation";
import { useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { exportResultsWorkspace } from "../lib/workspace/adapters/resultsWorkspace";
import { initRecoveryStore, useRecoveryStore } from "../lib/recovery/recoveryStore";

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

export default function GeneratePage({ subject = "math" }: GeneratePageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const prefillParams =
    (location.state as { prefillParams?: Record<string, unknown> } | null)
      ?.prefillParams ?? null;
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
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
  } = useGenerate();
  // Recovery must be resolved before ParamForm mounts. Otherwise its schema,
  // model, draft, and default effects can observe an empty form and replace a
  // confirmation that is still being restored. The layout gate also means a
  // store update from initRecoveryStore cannot arrive as a late prop that the
  // form has to reconcile after hydration has begun.
  const recoveryRoute = location.pathname ?? window.location.pathname;
  const recoveryBootKey = `${recoveryRoute}:${user?.id ?? ""}`;
  const [recoveryBootedKey, setRecoveryBootedKey] = useState<string | null>(null);
  useLayoutEffect(() => {
    initRecoveryStore({
      currentRoute: recoveryRoute,
      origin: window.location.origin,
      environment:
        typeof __BUILD_ENVIRONMENT__ === "undefined"
          ? "development"
          : __BUILD_ENVIRONMENT__,
    });
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the gate deliberately waits for synchronous recovery-store hydration before mounting the form
    setRecoveryBootedKey(recoveryBootKey);
  }, [recoveryBootKey, recoveryRoute]);
  const { enabled, open } = useFeedbackDialog();
  const formRef = useRef<HTMLElement | null>(null);
  const progressRef = useRef<HTMLElement | null>(null);
  const resultsRef = useRef<HTMLElement | null>(null);
  const [requestedTotal, setRequestedTotal] = useState(0);
  const [submittedSubQuestionCount, setSubmittedSubQuestionCount] =
    useState<number | null>(null);
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
  const hasResults = displayResults.length > 0;
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
    logout();
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
    return generate(generateParams);
  };

  const handleReset = () => {
    reset();
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

  const handleDownloadAll = () => {
    const op = useWorkspaceStore.getState().beginOperation("export_json", "generate.results");
    const json = JSON.stringify(results, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    downloadBlob(blob, `batch_${ts}.json`);
    op.end("completed");
  };

  const handleDownloadAllOdt = () => {
    const op = useWorkspaceStore.getState().beginOperation("export_odt", "generate.results");
    const ts = formatTimestamp();
    buildExamOdt(`exam_${ts}`, results).then((blob) => {
      downloadBlob(blob, `exam_${ts}.odt`);
      op.end("completed");
    }).catch(() => op.end("failed"));
  };

  const showProgress = !(progressLines.length === 0 && status === "idle");
  const runState: RunState =
    status === "error"
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
          />
        </section>

        {agentLanes.length > 0 && (
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <AgentStatusPanel
              lanes={agentLanes}
              requestedTotal={requestedTotal}
            />
          </section>
        )}

        {showProgress && (
          <section ref={progressRef} className="rounded-lg border bg-white p-4 shadow-sm">
            <ProgressLog lines={progressLines} status={status} errorMessage={errorMessage} llmCalls={llmCalls} />
          </section>
        )}

        {hasResults && (
          <section ref={resultsRef} className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold">{t("generate.results")} ({displayResults.length})</h2>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleDownloadAll}
                  disabled={results.length === 0}
                  className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("generate.btn_download_all")}
                </button>
                <button
                  type="button"
                  onClick={handleDownloadAllOdt}
                  disabled={results.length === 0}
                  className="rounded border border-blue-600 bg-white px-3 py-1.5 text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("generate.btn_download_all_odt")}
                </button>
                <button
                  type="button"
                  onClick={() => setPendingAction({ kind: "clearResults" })}
                  className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  {t("generate.btn_clear")}
                </button>
              </div>
            </div>
            <div className="space-y-3">
              {displayResults.map((item) => (
                <QuestionCard
                  key={item.question.id ?? `q-${item.index}`}
                  question={item.question}
                  phase={item.phase}
                  isFinal={item.isFinal}
                  trail={item.trail}
                  figurePolicyTrail={item.figurePolicyTrail}
                  referenceExampleRecord={item.referenceExampleRecord}
                />
              ))}
            </div>
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
        stageEvents={llmCalls}
        subQuestionCount={submittedSubQuestionCount ?? subQuestionTotal}
        startedAt={startedAt}
        finishedAt={finishedAt}
        availableTargets={availableTargets}
        onJump={handleJump}
        onFeedback={enabled ? open : null}
      />
    </div>
  );
}
