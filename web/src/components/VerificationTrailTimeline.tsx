import { useId, useState } from "react";

import type { VerificationTrailEntry } from "../hooks/useGenerate";
import { useT } from "../i18n/useT";

export interface VerificationTrailTimelineProps {
  entries: VerificationTrailEntry[];
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap gap-x-2 gap-y-0.5">
      <dt className="font-medium text-gray-600">{label}</dt>
      <dd className="whitespace-pre-wrap text-gray-800">{value}</dd>
    </div>
  );
}

export default function VerificationTrailTimeline({
  entries,
}: VerificationTrailTimelineProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const generatedId = useId();

  if (entries.length === 0) return null;

  const sectionLabel = t("card.verificationTrail");
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
