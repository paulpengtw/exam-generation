import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import LanguageSwitcher from "../components/LanguageSwitcher";
import { useT } from "../i18n/useT";
import {
  listHistory,
  type HistoryListItem,
  type HistoryListResponse,
} from "../api/client";
import { useAuthStore } from "../store/authStore";
import HistoryDetail from "./HistoryDetail";

const PAGE_SIZE = 20;

function subjectLabel(t: (k: string) => string, subject: string): string {
  if (subject === "math") return t("history.subject_math");
  if (subject === "social_studies") return t("history.subject_ss");
  if (subject === "natural_sciences") return t("history.subject_ns");
  return subject;
}

export default function HistoryPage() {
  const params = useParams<{ id?: string }>();
  if (params.id) {
    return <HistoryDetail recordId={params.id} />;
  }
  return <HistoryList />;
}

function HistoryList() {
  const navigate = useNavigate();
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const [data, setData] = useState<HistoryListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [subject, setSubject] = useState<string>("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await listHistory({
        limit: PAGE_SIZE,
        offset,
        subject: subject || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "error");
    }
  }, [offset, subject]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch on mount/param change, matches existing VerifyPage/ParamForm pattern
    void load();
  }, [load]);

  const items: HistoryListItem[] = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total ?? 0;
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-2 px-3 py-3 sm:px-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate("/generate")}
              className="rounded border border-gray-300 bg-white px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
            >
              ←
            </button>
            <h1 className="text-base font-semibold sm:text-lg">
              {t("history.title")}
            </h1>
          </div>
          <div className="flex items-center gap-2 text-sm sm:gap-3">
            <LanguageSwitcher />
            {user && (
              <span className="hidden max-w-[12rem] truncate text-gray-700 sm:inline">
                {user.email}
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-4 px-3 py-4 sm:px-4 sm:py-6">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-700">
            <select
              value={subject}
              onChange={(e) => {
                setSubject(e.target.value);
                setOffset(0);
              }}
              className="ml-2 rounded border border-gray-300 bg-white px-2 py-1 text-sm"
            >
              <option value="">{t("history.filter_subject_all")}</option>
              <option value="math">{t("history.subject_math")}</option>
              <option value="social_studies">{t("history.subject_ss")}</option>
              <option value="natural_sciences">{t("history.subject_ns")}</option>
            </select>
          </label>
        </div>

        {error && (
          <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {data && items.length === 0 && !error && (
          <div className="rounded border bg-white p-6 text-center text-sm text-gray-600 shadow-sm">
            {t("history.empty")}
          </div>
        )}

        <ul className="space-y-2">
          {items.map((item) => {
            const hasFigurePolicyDegradation = item.figure_policy_trail?.some(
              (entry) => entry.kind === "warning" && entry.duplicate_image_shipped,
            ) ?? false;

            return (
              <li key={item.id}>
              <Link
                to={`/history/${item.id}`}
                className="flex flex-col gap-1 rounded border bg-white p-3 shadow-sm hover:border-blue-400"
              >
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span className="rounded bg-gray-100 px-2 py-0.5 font-medium text-gray-700">
                    {subjectLabel(t, item.subject)}
                  </span>
                  {item.status === "failed" && (
                    <span className="rounded bg-red-100 px-2 py-0.5 font-medium text-red-700">
                      {t("history.failed_badge")}
                    </span>
                  )}
                  {item.status === "aborted" && (
                    <span className="rounded bg-amber-100 px-2 py-0.5 font-medium text-amber-800">
                      {t("history.aborted_badge")}
                    </span>
                  )}
                  {hasFigurePolicyDegradation && (
                    <span className="rounded bg-amber-100 px-2 py-0.5 font-medium text-amber-800">
                      {t("history.figure_policy_degraded_badge")}
                    </span>
                  )}
                  <span>{new Date(item.created_at).toLocaleString()}</span>
                </div>
                <div className="text-sm text-gray-800">
                  {item.status === "failed"
                    ? item.error || item.preview
                    : item.status === "aborted"
                      ? t("history.aborted_preview")
                      : item.preview}
                </div>
                <div className="flex items-center gap-2 text-xs">
                  {item.status !== "failed" && item.status !== "aborted" && (
                    <span className="text-gray-500">{item.question_id}</span>
                  )}
                  {item.status !== "failed" &&
                    item.status !== "aborted" &&
                    item.verified && (
                    <span className="rounded bg-green-100 px-1.5 py-0.5 font-medium text-green-700">
                      {t("history.verified_badge")}
                    </span>
                  )}
                </div>
              </Link>
              </li>
            );
          })}
        </ul>

        <div className="flex items-center justify-between">
          <button
            type="button"
            disabled={!hasPrev}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("history.prev_page")}
          </button>
          <button
            type="button"
            disabled={!hasNext}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("history.next_page")}
          </button>
        </div>
      </main>
    </div>
  );
}
