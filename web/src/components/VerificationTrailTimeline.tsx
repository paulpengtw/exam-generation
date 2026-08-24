import { useId, useState } from "react";

import type {
  VerificationTrailCorrectionEntry,
  VerificationTrailEntry,
  VerificationTrailInitialEntry,
} from "../hooks/useGenerate";
import { useT } from "../i18n/useT";
import { diffSnapshots } from "../lib/snapshotDiff";

export interface VerificationTrailTimelineProps {
  entries: VerificationTrailEntry[] | null;
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap gap-x-2 gap-y-0.5">
      <dt className="font-medium text-gray-600">{label}</dt>
      <dd className="whitespace-pre-wrap text-gray-800">{value}</dd>
    </div>
  );
}

function formatSnapshotValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined) return "—";
  return JSON.stringify(value) ?? String(value);
}

function previousSnapshotFor(
  entries: VerificationTrailEntry[],
  currentIndex: number,
  questionId: string,
): Record<string, unknown> | undefined {
  for (let index = currentIndex - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (
      entry.question_id === questionId &&
      (entry.kind === "initial" || entry.kind === "correction")
    ) {
      return entry.snapshot;
    }
  }
  return undefined;
}

function SnapshotTrailItem({
  entry,
  beforeSnapshot,
  snapshotOpen,
  snapshotId,
  onToggle,
  t,
}: {
  entry: VerificationTrailInitialEntry | VerificationTrailCorrectionEntry;
  beforeSnapshot?: Record<string, unknown>;
  snapshotOpen: boolean;
  snapshotId: string;
  onToggle: () => void;
  t: (key: string) => string;
}) {
  const isCorrection = entry.kind === "correction";
  const changes = isCorrection
    ? diffSnapshots(beforeSnapshot ?? {}, entry.snapshot)
    : [];

  return (
    <li
      data-trail-kind={entry.kind}
      className="rounded border border-blue-200 bg-blue-50 p-3 text-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">
          {t(isCorrection ? "card.trailCorrection" : "card.trailInitialVersion")}
        </span>
        <time dateTime={entry.timestamp} className="text-xs text-gray-500">
          {entry.timestamp}
        </time>
      </div>
      {isCorrection && (
        <dl className="mt-2 space-y-1">
          <DetailRow
            label={t("card.trailRetryIndex")}
            value={String(entry.retry_index)}
          />
          <DetailRow
            label={t("card.trailCorrectorModel")}
            value={entry.model}
          />
        </dl>
      )}
      {isCorrection && (
        <div className="mt-2 rounded border border-blue-100 bg-white p-2">
          <div className="font-medium text-gray-700">
            {t("card.trailChangedFields")}
          </div>
          {changes.length > 0 ? (
            <dl className="mt-1 space-y-1">
              {changes.map((change) => (
                <DetailRow
                  key={change.path}
                  label={change.path}
                  value={`${formatSnapshotValue(change.before)} → ${formatSnapshotValue(change.after)}`}
                />
              ))}
            </dl>
          ) : (
            <p className="mt-1 text-gray-600">{t("card.trailNoChanges")}</p>
          )}
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-gray-700">{t("card.trailSnapshot")}</span>
        <button
          type="button"
          aria-controls={snapshotId}
          aria-expanded={snapshotOpen}
          onClick={onToggle}
          className="text-sm font-medium text-blue-700 hover:text-blue-800"
        >
          {t(snapshotOpen ? "card.trailHideSnapshot" : "card.trailShowSnapshot")}
        </button>
      </div>
      {snapshotOpen && (
        <pre
          id={snapshotId}
          className="mt-2 overflow-x-auto rounded bg-white p-2 text-xs text-gray-800"
        >
          {JSON.stringify(entry.snapshot, null, 2)}
        </pre>
      )}
    </li>
  );
}

export default function VerificationTrailTimeline({
  entries,
}: VerificationTrailTimelineProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [openSnapshots, setOpenSnapshots] = useState<Record<number, boolean>>({});
  const generatedId = useId();

  const sectionLabel = t("card.verificationTrail");

  if (entries === null) {
    return (
      <section
        aria-label={sectionLabel}
        className="rounded border border-gray-200 bg-gray-50 p-3"
      >
        <h3 className="font-semibold text-gray-800">{sectionLabel}</h3>
        <p className="mt-2 text-sm text-gray-600">
          {t("card.noVerificationTrail")}
        </p>
      </section>
    );
  }

  if (entries.length === 0) return null;

  const contentId = `verification-trail-timeline-${generatedId}`;

  return (
    <section
      aria-label={sectionLabel}
      className="rounded border border-gray-200 bg-gray-50 p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-gray-800">{sectionLabel}</h3>
        <button
          type="button"
          aria-controls={contentId}
          aria-expanded={open}
          onClick={() => setOpen((previous) => !previous)}
          className="text-sm font-medium text-blue-600 hover:text-blue-700"
        >
          {t(open ? "card.hideVerificationTrail" : "card.showVerificationTrail")}
        </button>
      </div>

      {open && (
        <ol id={contentId} className="mt-3 space-y-2">
          {entries.map((entry, index) => {
            if (entry.kind !== "verification") {
              const snapshotId = `${contentId}-snapshot-${index}`;
              return (
                <SnapshotTrailItem
                  key={`${entry.timestamp}-${index}`}
                  entry={entry}
                  beforeSnapshot={
                    entry.kind === "correction"
                      ? previousSnapshotFor(entries, index, entry.question_id)
                      : undefined
                  }
                  snapshotOpen={openSnapshots[index] ?? false}
                  snapshotId={snapshotId}
                  onToggle={() => setOpenSnapshots((previous) => ({
                    ...previous,
                    [index]: !(previous[index] ?? false),
                  }))}
                  t={t}
                />
              );
            }

            const passedClass = entry.passed
              ? "border-green-200 bg-green-50"
              : "border-red-200 bg-red-50";
            const statusLabel = entry.passed
              ? t("card.verificationTrailPassed")
              : t("card.verificationTrailFailed");
            return (
              <li
                key={`${entry.timestamp}-${index}`}
                data-verdict={entry.passed ? "passed" : "failed"}
                data-trail-kind={entry.kind}
                className={`rounded border p-3 text-sm ${passedClass}`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold">{statusLabel}</span>
                  <time dateTime={entry.timestamp} className="text-xs text-gray-500">
                    {entry.timestamp}
                  </time>
                </div>
                <p className="mt-2 whitespace-pre-wrap">{entry.details}</p>
                <dl className="mt-2 space-y-1">
                  <DetailRow label={t("card.trailMyAnswer")} value={entry.my_answer} />
                  <DetailRow
                    label={t("card.trailProvidedAnswer")}
                    value={entry.provided_answer}
                  />
                  <DetailRow
                    label={t("card.trailAnswerMatch")}
                    value={entry.answer_match ? t("card.trailYes") : t("card.trailNo")}
                  />
                  <DetailRow label={t("card.trailModel")} value={entry.model} />
                </dl>
                {entry.chart_verification && (
                  <div className="mt-2 rounded border border-gray-200 bg-white p-2">
                    <div className="font-medium text-gray-700">
                      {t("card.trailChartVerification")}
                    </div>
                    <dl className="mt-1 space-y-1">
                      <DetailRow
                        label={t("card.trailChartDataMatch")}
                        value={entry.chart_verification.chart_data_match ? t("card.trailYes") : t("card.trailNo")}
                      />
                      <DetailRow
                        label={t("card.trailChartLabelsCorrect")}
                        value={entry.chart_verification.chart_labels_correct ? t("card.trailYes") : t("card.trailNo")}
                      />
                      <DetailRow
                        label={t("card.trailChartDetails")}
                        value={entry.chart_verification.chart_details}
                      />
                    </dl>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
