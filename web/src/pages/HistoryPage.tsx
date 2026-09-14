import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import LanguageSwitcher from "../components/LanguageSwitcher";
import { useT } from "../i18n/useT";
import {
  listHistory,
  type HistoryListItem,
  type HistoryListResponse,
} from "../api/client";
import { useAuthStore } from "../store/authStore";
import {
  ActionButton,
  InlineFailureNotice,
  useActionFeedback,
} from "../motion/actionFeedback";
import { canViewTransition } from "../motion/tokens";
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
  const { search } = useLocation();
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const [data, setData] = useState<HistoryListResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [subject, setSubject] = useState<string>("");
  const requestedPage = useRef({ offset: 0, subject: "" });
  const requesting = useRef(false);

  const load = useCallback(async () => {
    const request = requestedPage.current;
    const res = await listHistory({
      limit: PAGE_SIZE,
      offset: request.offset,
      subject: request.subject || undefined,
    });
    setData(res);
    setOffset(request.offset);
    setSubject(request.subject);
  }, []);
  const paging = useActionFeedback(load, t("action.history_failed"));
  const { execute } = paging;
  const isPaging = paging.state === "pending";

  const requestPage = (nextOffset: number, nextSubject = subject) => {
    if (isPaging || requesting.current) return;
    requestedPage.current = { offset: nextOffset, subject: nextSubject };
    requesting.current = true;
    void execute().finally(() => {
      requesting.current = false;
    });
  };

  useEffect(() => {
    void execute();
  }, [execute]);

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
              onClick={() => navigate(`/generate${search}`, {
                viewTransition: canViewTransition(),
              })}
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
              disabled={isPaging}
              onChange={(e) => requestPage(0, e.target.value)}
              className="ml-2 rounded border border-gray-300 bg-white px-2 py-1 text-sm disabled:opacity-50"
            >
              <option value="">{t("history.filter_subject_all")}</option>
              <option value="math">{t("history.subject_math")}</option>
              <option value="social_studies">{t("history.subject_ss")}</option>
              <option value="natural_sciences">{t("history.subject_ns")}</option>
            </select>
          </label>
        </div>

        {data && items.length === 0 && paging.state !== "failed" && (
          <div className="rounded border bg-white p-6 text-center text-sm text-gray-600 shadow-sm">
            {t("history.empty")}
          </div>
        )}

        <ul
          aria-busy={isPaging}
          className={`space-y-2 transition-opacity duration-quick ease-signature ${isPaging ? "opacity-45" : "opacity-100"}`}
        >
          {items.map((item) => {
            const hasFigurePolicyDegradation = item.figure_policy_trail?.some(
              (entry) =>
                (entry.kind === "warning" && entry.duplicate_image_shipped) ||
                entry.kind === "data_inconsistency",
            ) ?? false;

            return (
              <li key={item.id}>
              <Link
                to={`/history/${item.id}${search}`}
                viewTransition={canViewTransition()}
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

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <ActionButton
              type="button"
              state={paging.state === "done" ? "idle" : paging.state}
              label={t("history.prev_page")}
              pendingLabel={t("action.paging")}
              disabled={!hasPrev || isPaging}
              onClick={() => requestPage(Math.max(0, offset - PAGE_SIZE))}
              className="min-w-28 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            />
            <ActionButton
              type="button"
              state={paging.state === "done" ? "idle" : paging.state}
              label={t("history.next_page")}
              pendingLabel={t("action.paging")}
              disabled={!hasNext || isPaging}
              onClick={() => requestPage(offset + PAGE_SIZE)}
              className="min-w-28 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
          <InlineFailureNotice
            reason={paging.reason}
            onRetry={paging.retry}
            onDismiss={paging.reset}
          />
        </div>
      </main>
    </div>
  );
}
