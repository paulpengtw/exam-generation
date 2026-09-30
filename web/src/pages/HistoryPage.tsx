import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import LanguageSwitcher from "../components/LanguageSwitcher";
import {
  ActionButton,
  firstFailure,
  InlineFailureNotice,
  useActionFeedback,
} from "../motion/actionFeedback";
import { useT } from "../i18n/useT";
import {
  listHistory,
  listRuns,
  type HistoryListItem,
  type HistoryListResponse,
  type RunListItem,
} from "../api/client";
import { useAuthStore } from "../store/authStore";
import HistoryDetail from "./HistoryDetail";
import { useSurfaceParticipation } from "../lib/workspace/useSurfaceParticipation";
import {
  findNewestCompletedAt,
  getLastSeenAt,
  initLastSeenAt,
  setLastSeenAt,
} from "../lib/historyBadge";

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

/** Interval for polling unfinished runs (ms). Slower when tab is hidden. */
const UNFINISHED_POLL_VISIBLE_MS = 4_000;
const UNFINISHED_POLL_HIDDEN_MS = 20_000;

/** True when the run is still active (queued or running). */
function isActiveStatus(status: string): boolean {
  return status === "queued" || status === "running";
}

function HistoryList() {
  const navigate = useNavigate();
  const t = useT();
  const user = useAuthStore((s) => s.user);
  const [data, setData] = useState<HistoryListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [subject, setSubject] = useState<string>("");

  // Unfinished runs section state
  const [unfinishedRuns, setUnfinishedRuns] = useState<RunListItem[]>([]);
  const [unfinishedError, setUnfinishedError] = useState<string | null>(null);
  // Track which run IDs were active in the previous poll so we can detect transitions.
  const prevActiveIdsRef = useRef<Set<string> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useSurfaceParticipation("history.list", {
    readiness: data !== null || error !== null ? "ready" : "hydrating",
    hasEditableState: false,
    hasReceivedResults: false,
  });

  // Badge marker is updated inside pollOnce (see below) using the server's
  // newest completed_at rather than the client clock (fix(913) issue #2).

  const loadInitial = useCallback(async () => {
    setError(null);
    try {
      const res = await listHistory({
        limit: PAGE_SIZE,
        offset: 0,
        subject: subject || undefined,
      });
      setOffset(0);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "error");
    }
  }, [subject]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch on mount/param change, matches existing VerifyPage/ParamForm pattern
    void loadInitial();
  }, [loadInitial]);

  // Polling for unfinished runs.
  useEffect(() => {
    let aborted = false;

    async function pollOnce() {
      try {
        const runs = await listRuns();
        if (aborted) return;
        const active = runs.filter((r) => isActiveStatus(r.status));
        setUnfinishedRuns(active);
        setUnfinishedError(null);

        // Detect runs that transitioned out of active (ended since last poll).
        const prev = prevActiveIdsRef.current;
        if (prev !== null && prev.size > 0) {
          const activeNow = new Set(active.map((r) => r.run_id));
          let anyEnded = false;
          for (const id of prev) {
            if (!activeNow.has(id)) { anyEnded = true; break; }
          }
          if (anyEnded) {
            // Refetch the ordinary history list so the ended run appears.
            void loadInitial();
          }
        }
        prevActiveIdsRef.current = new Set(active.map((r) => r.run_id));

        // Update the badge last-seen marker with the server's newest
        // completed_at so HistoryPage clears the badge using server time,
        // not the potentially-skewed client clock (fix(913) issue #2).
        if (user) {
          const newest = findNewestCompletedAt(runs);
          if (newest !== null) {
            const current = getLastSeenAt(user.id);
            if (current === null || Date.parse(newest) > Date.parse(current)) {
              setLastSeenAt(user.id, newest);
            }
          } else if (getLastSeenAt(user.id) === null) {
            // No completed runs yet — initialize to avoid retroactive badge
            // when first run completes.  initLastSeenAt with null is a no-op
            // here; badge will be false until a run completes regardless.
            initLastSeenAt(user.id, null);
          }
        }
      } catch {
        if (!aborted) {
          setUnfinishedError("error");
        }
      }
    }

    function schedule() {
      if (aborted) return;
      const delay =
        document.visibilityState === "hidden"
          ? UNFINISHED_POLL_HIDDEN_MS
          : UNFINISHED_POLL_VISIBLE_MS;
      pollTimerRef.current = setTimeout(() => {
        void pollOnce().then(() => { schedule(); });
      }, delay);
    }

    // Run immediately, then schedule repeats.
    void pollOnce().then(() => { schedule(); });

    return () => {
      aborted = true;
      if (pollTimerRef.current !== null) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- user?.id (primitive) is the stable dependency; the full `user` object reference changes on every render from the zustand selector
  }, [loadInitial, user?.id]);

  const previousFeedback = useActionFeedback<HistoryListResponse>({
    action: (signal) => listHistory({
      limit: PAGE_SIZE,
      offset: Math.max(0, offset - PAGE_SIZE),
      subject: subject || undefined,
      signal,
    }),
    genericError: t("history.page_error"),
    onSuccess: (res) => {
      setOffset(Math.max(0, offset - PAGE_SIZE));
      setData(res);
    },
  });

  const nextFeedback = useActionFeedback<HistoryListResponse>({
    action: (signal) => listHistory({
      limit: PAGE_SIZE,
      offset: offset + PAGE_SIZE,
      subject: subject || undefined,
      signal,
    }),
    genericError: t("history.page_error"),
    onSuccess: (res) => {
      setOffset(offset + PAGE_SIZE);
      setData(res);
    },
  });

  const items: HistoryListItem[] = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total ?? 0;
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;
  const paging = previousFeedback.state === "pending" || nextFeedback.state === "pending";
  const pagingFailure = firstFailure(previousFeedback, nextFeedback);

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

        {/* 尚未結束 (unfinished) section — queued + running runs */}
        {(unfinishedRuns.length > 0 || unfinishedError) && (
          <section
            aria-label={t("history.unfinished_title")}
            className="rounded border bg-white p-3 shadow-sm"
          >
            <h2 className="mb-2 text-sm font-semibold text-gray-700">
              {t("history.unfinished_title")}
            </h2>
            {unfinishedError && (
              <p className="text-sm text-red-600">{t("history.unfinished_error")}</p>
            )}
            <ul className="space-y-1">
              {unfinishedRuns.map((run) => {
                const label = run.cancel_requested
                  ? t("history.run_cancelling")
                  : run.status === "queued"
                    ? t("history.run_queued").replace(
                        "{k}",
                        String(run.queue_position ?? 0),
                      )
                    : t("history.run_running");
                const VALID_SUBJECTS = ["math", "social_studies", "natural_sciences"] as const;
                const subjectPath =
                  run.subject != null &&
                  (VALID_SUBJECTS as readonly string[]).includes(run.subject)
                    ? `/generate/${run.subject}?run=${run.run_id}`
                    : "/generate";
                return (
                  <li key={run.run_id}>
                    <Link
                      to={subjectPath}
                      className="flex items-center gap-2 rounded px-2 py-1 text-sm text-blue-700 hover:bg-blue-50"
                    >
                      <span className="truncate font-medium">
                        {run.subject ?? run.run_id}
                      </span>
                      <span className="ml-auto whitespace-nowrap rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700">
                        {label}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

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

        <ul
          className={`space-y-2 transition-opacity duration-quick ease-signature ${paging ? "opacity-50" : ""}`}
          aria-busy={paging}
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

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <ActionButton
              feedback={previousFeedback}
              label={t("history.prev_page")}
              pendingLabel={t("action.loading")}
              doneLabel={t("history.prev_page")}
              disabled={!hasPrev}
              className="min-w-28 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            />
            <ActionButton
              feedback={nextFeedback}
              label={t("history.next_page")}
              pendingLabel={t("action.loading")}
              doneLabel={t("history.next_page")}
              disabled={!hasNext}
              className="min-w-28 rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
          {pagingFailure && (
            <InlineFailureNotice
              reason={pagingFailure.reason}
              onRetry={pagingFailure.retry}
              onDismiss={pagingFailure.dismiss}
            />
          )}
        </div>
      </main>
    </div>
  );
}
