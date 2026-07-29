import { useEffect, useRef, useState } from "react";
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

export interface GeneratePageProps {
  subject?: "math" | "social_studies" | "natural_sciences";
}

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
    generate,
    reset,
  } = useGenerate();
  const { enabled, open } = useFeedbackDialog();
  const formRef = useRef<HTMLElement | null>(null);
  const progressRef = useRef<HTMLElement | null>(null);
  const resultsRef = useRef<HTMLElement | null>(null);
  const [requestedTotal, setRequestedTotal] = useState(0);
  const [subQuestionCount, setSubQuestionCount] = useState<number | null>(null);
  const [hasUnsubmittedInput, setHasUnsubmittedInput] = useState(false);
  const [isLogoutConfirmOpen, setIsLogoutConfirmOpen] = useState(false);
  const [isClearResultsConfirmOpen, setIsClearResultsConfirmOpen] =
    useState(false);
  const [pendingResubmitParams, setPendingResubmitParams] = useState<
    ReturnType<typeof toGenerateParams> | null
  >(null);
  const [pendingNavigationTarget, setPendingNavigationTarget] = useState<
    string | null
  >(null);
  const hasResults = displayResults.length > 0;
  const blocker = useBlocker(
    ({ historyAction }) =>
      (hasUnsubmittedInput || hasResults) && historyAction === "POP",
  );

  useEffect(() => {
    if (!hasUnsubmittedInput && !hasResults) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
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
    if (status === "generating") {
      setPendingResubmitParams(generateParams);
      return;
    }
    setRequestedTotal(params.count);
    setSubQuestionCount(generateParams.sub_question_count ?? null);
    generate(generateParams);
  };

  const handleReset = () => {
    reset();
    setRequestedTotal(0);
    setSubQuestionCount(null);
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
    const json = JSON.stringify(results, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    downloadBlob(blob, `batch_${ts}.json`);
  };

  const handleDownloadAllOdt = () => {
    const ts = formatTimestamp();
    buildExamOdt(`exam_${ts}`, results).then((blob) => {
      downloadBlob(blob, `exam_${ts}.odt`);
    });
  };

  const showProgress = !(progressLines.length === 0 && status === "idle");
  const runState: RunState =
    status === "error"
      ? "error"
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

    setPendingNavigationTarget(target);
  };
  const handleNavigationConfirm = () => {
    if (pendingNavigationTarget === null) return;

    const target = pendingNavigationTarget;
    setPendingNavigationTarget(null);
    navigate(target);
  };
  const navigationBodyKeys = [
    ...(hasUnsubmittedInput ? ["confirm.navigate_away_body_params"] : []),
    ...(hasResults ? ["confirm.navigate_away_body_results"] : []),
  ];

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
              onClick={() => setIsLogoutConfirmOpen(true)}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("generate.btn_logout")}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-3 pt-4 pb-20 sm:px-4 sm:pt-6">
        <section ref={formRef} className="rounded-lg border bg-white p-3 shadow-sm sm:p-4">
          <ParamForm
            subject={subject}
            onSubmit={handleSubmit}
            disabled={status === "generating"}
            initialParams={prefillParams ?? undefined}
            onUnsubmittedInput={() => setHasUnsubmittedInput(true)}
          />
        </section>

        {agentLanes.length > 0 && (
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <AgentStatusPanel lanes={agentLanes} />
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
                  onClick={() => setIsClearResultsConfirmOpen(true)}
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
                />
              ))}
            </div>
          </section>
        )}
      </main>
      <DestructiveConfirm
        open={pendingNavigationTarget !== null}
        titleKey="confirm.navigate_away_title"
        bodyKeys={navigationBodyKeys}
        confirmKey="confirm.navigate_away_confirm"
        onConfirm={handleNavigationConfirm}
        onCancel={() => setPendingNavigationTarget(null)}
      />
      <DestructiveConfirm
        open={blocker.state === "blocked"}
        titleKey="confirm.navigate_away_title"
        bodyKeys={navigationBodyKeys}
        confirmKey="confirm.navigate_away_confirm"
        onConfirm={() => blocker.proceed?.()}
        onCancel={() => blocker.reset?.()}
      />
      <DestructiveConfirm
        open={isLogoutConfirmOpen}
        titleKey="confirm.logout_title"
        bodyKeys={[
          "confirm.logout_body_session",
          ...((hasUnsubmittedInput || hasResults)
            ? ["confirm.logout_body_work_lost"]
            : []),
        ]}
        confirmKey="confirm.logout_confirm"
        onConfirm={handleLogout}
        onCancel={() => setIsLogoutConfirmOpen(false)}
      />
      <DestructiveConfirm
        open={isClearResultsConfirmOpen}
        titleKey="confirm.clear_results_title"
        bodyKeys={[
          "confirm.clear_results_body",
          ...(status === "generating"
            ? ["confirm.clear_results_body_streaming"]
            : []),
        ]}
        confirmKey="confirm.clear_results_confirm"
        onConfirm={() => {
          setIsClearResultsConfirmOpen(false);
          handleReset();
        }}
        onCancel={() => setIsClearResultsConfirmOpen(false)}
      />
      <DestructiveConfirm
        open={pendingResubmitParams !== null}
        titleKey="confirm.resubmit_title"
        bodyKeys={["confirm.resubmit_body"]}
        confirmKey="confirm.resubmit_confirm"
        onConfirm={() => {
          if (pendingResubmitParams === null) return;
          const params = pendingResubmitParams;
          setPendingResubmitParams(null);
          setRequestedTotal(params.count ?? 0);
          setSubQuestionCount(params.sub_question_count ?? null);
          generate(params);
        }}
        onCancel={() => setPendingResubmitParams(null)}
      />
      <GenerationStatusBar
        runState={runState}
        completedCount={results.length}
        requestedTotal={requestedTotal}
        subject={subject}
        stageEvents={llmCalls}
        subQuestionCount={subQuestionCount}
        startedAt={startedAt}
        finishedAt={finishedAt}
        availableTargets={availableTargets}
        onJump={handleJump}
        onFeedback={enabled ? open : null}
      />
    </div>
  );
}
