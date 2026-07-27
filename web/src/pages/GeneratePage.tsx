import { useLocation, useNavigate } from "react-router-dom";

import AgentStatusPanel from "../components/AgentStatusPanel";
import ParamForm, { type GenerateParams as FormParams } from "../components/ParamForm";
import ProgressLog from "../components/ProgressLog";
import QuestionCard from "../components/QuestionCard";
import { useGenerate } from "../hooks/useGenerate";
import { useAuthStore } from "../store/authStore";
import { useT } from "../i18n/useT";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { buildExamOdt, formatTimestamp } from "../utils/odt";

export interface GeneratePageProps {
  subject?: string;
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
  const { status, progressLines, results, displayResults, llmCalls, agentLanes, errorMessage, generate, reset } = useGenerate();

  const handleLogout = () => {
    logout();
    navigate("/");
  };

  const handleSubmit = (params: FormParams) => {
    generate({
      subject,
      grade: params.grade,
      style: subject === "math" && params.style ? [params.style] : [],
      content_type:
        subject === "social_studies" || subject === "math" || subject === "natural_sciences"
          ? params.content_type
          : undefined,
      context: subject === "math" || subject === "natural_sciences" ? params.context : [],
      set_type: params.set_type,
      q_type: params.q_type,
      count: params.count,
      skip_verify: params.skip_verify,
      disable_reference_fewshot:
        subject === "social_studies" || subject === "natural_sciences"
          ? params.disable_reference_fewshot
          : undefined,
      image_generation_mode:
        subject === "social_studies" || subject === "math" || subject === "natural_sciences"
          ? params.image_generation_mode
          : undefined,
      subject_filter:
        subject === "social_studies" || subject === "math"
          ? (params.subject_filter ? [params.subject_filter] : undefined)
          : undefined,
      topic:
        subject === "social_studies" || subject === "math" || subject === "natural_sciences"
          ? params.topic
          : undefined,
      core_question:
        subject === "social_studies" || subject === "math" || subject === "natural_sciences"
          ? params.core_question
          : undefined,
      passage:
        subject === "social_studies" || subject === "math" || subject === "natural_sciences"
          ? params.passage
          : undefined,
      options:
        subject === "social_studies" || subject === "math" || subject === "natural_sciences"
          ? params.options
          : undefined,
      sub_context: subject === "natural_sciences" ? params.sub_context : undefined,
      science_competency:
        subject === "natural_sciences" ? params.science_competency : undefined,
      learning_performance:
        subject === "social_studies" || subject === "math" || subject === "natural_sciences"
          ? params.learning_performance
          : undefined,
      learning_content:
        subject === "social_studies" || subject === "natural_sciences"
          ? params.learning_content
          : undefined,
      sub_question_count:
        subject === "social_studies" || subject === "natural_sciences" ? params.sub_question_count : undefined,
      subquestion_configs:
        subject === "social_studies" || subject === "natural_sciences" ? params.subquestion_configs : undefined,
      model_plan: params.model_plan,
      model_execute: params.model_execute,
      difficulty: params.difficulty,
      coverage_mode: subject === "social_studies" ? params.coverage_mode : undefined,
      text_word_limit: params.text_word_limit,
    });
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
  const hasResults = displayResults.length > 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-2 px-3 py-3 sm:px-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate("/generate")}
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
              onClick={() => navigate("/history")}
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
              onClick={handleLogout}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 font-medium text-gray-700 hover:bg-gray-50"
            >
              {t("generate.btn_logout")}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-3 py-4 sm:px-4 sm:py-6">
        <section className="rounded-lg border bg-white p-3 shadow-sm sm:p-4">
          <ParamForm
            subject={subject}
            onSubmit={handleSubmit}
            disabled={status === "generating"}
            initialParams={prefillParams ?? undefined}
          />
        </section>

        {agentLanes.length > 0 && (
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <AgentStatusPanel lanes={agentLanes} />
          </section>
        )}

        {showProgress && (
          <section className="rounded-lg border bg-white p-4 shadow-sm">
            <ProgressLog lines={progressLines} status={status} errorMessage={errorMessage} llmCalls={llmCalls} />
          </section>
        )}

        {hasResults && (
          <section className="space-y-3">
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
                  onClick={reset}
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
    </div>
  );
}
