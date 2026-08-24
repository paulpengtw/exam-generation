import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import QuestionCard from "../components/QuestionCard";
import type { ExamQuestion } from "../hooks/useGenerate";
import { useT } from "../i18n/useT";
import {
  downloadHistoryJson,
  getHistoryDetail,
  type HistoryDetail as HistoryDetailPayload,
} from "../api/client";

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

export default function HistoryDetail({ recordId }: HistoryDetailProps) {
  const t = useT();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<HistoryDetailPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch on mount/param change, matches existing VerifyPage/HistoryPage pattern
    setError(null);
    setDetail(null);
    getHistoryDetail(recordId)
      .then((res) => {
        if (!cancelled) setDetail(res);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "error");
      });
    return () => {
      cancelled = true;
    };
  }, [recordId]);

  const isFailed = detail?.status === "failed";
  const isAborted = detail?.status === "aborted";
  const isInterrupted = isFailed || isAborted;
  const canDownload = detail != null && !isInterrupted;
  const showDownload = detail == null || canDownload;

  const handleDownload = async () => {
    if (!detail || !canDownload) return;
    const blob = await downloadHistoryJson(detail.id);
    saveBlob(blob, `${detail.question_id || detail.id}.json`);
  };

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
          </div>
          <div className="flex items-center gap-2">
            {showDownload && (
              <button
                type="button"
                disabled={!detail}
                onClick={handleDownload}
                className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {t("history.btn_download_json")}
              </button>
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
            </section>
          ) : (
            <QuestionCard
              key={detail.id}
              question={detail.question_json as unknown as ExamQuestion}
              recordId={detail.id}
              phase="verified"
              isFinal
              trail={detail.verification_trail}
            />
          )
        )}
      </main>
    </div>
  );
}
