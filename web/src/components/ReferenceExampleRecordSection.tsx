import { useState } from "react";
import { useT } from "../i18n/useT";

export interface ReferenceExampleEntryShape {
  code: "reference_example";
  kind: "example" | "process_exemplar";
  question_id: string;
  stage: string;
  slot?: number | null;
  description?: string;
  source: string;
  content?: unknown;
  images?: Array<{ path: string; description?: string }>;
  cognitive_process?: string;
  timestamp: string;
}

export interface ReferenceExampleRecordShape {
  disabled?: boolean;
  entries: ReferenceExampleEntryShape[];
}

export interface ReferenceExampleRecordSectionProps {
  record?: ReferenceExampleRecordShape | null;
  inProgress?: boolean;
}

export default function ReferenceExampleRecordSection({
  record,
  inProgress = false,
}: ReferenceExampleRecordSectionProps) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);

  if (record === undefined) return null;

  const isDisabled = record?.disabled === true;
  const entries = record?.entries ?? [];

  // Build a map from source → first slot that used it (for duplicate badge)
  const sourceToFirstSlot = new Map<string, number | null>();
  for (const entry of entries) {
    if (!sourceToFirstSlot.has(entry.source)) {
      sourceToFirstSlot.set(entry.source, entry.slot ?? null);
    }
  }

  return (
    <section
      aria-label={t("card.referenceExampleRecord")}
      className="rounded border border-gray-200 bg-gray-50 p-3"
    >
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-800">{t("card.referenceExampleRecord")}</h3>
        {entries.length > 0 && !isDisabled && (
          <button
            type="button"
            aria-label={
              expanded
                ? t("card.hideReferenceExampleRecord")
                : t("card.showReferenceExampleRecord")
            }
            onClick={() => setExpanded((prev) => !prev)}
            className="rounded border border-gray-300 bg-white px-2 py-0.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
          >
            {expanded
              ? t("card.hideReferenceExampleRecord")
              : `${entries.length}`}
          </button>
        )}
      </div>

      {isDisabled ? (
        <p className="mt-2 text-sm text-gray-500">
          {t("card.referenceExampleRecordDisabled")}
        </p>
      ) : entries.length === 0 ? (
        <p className="mt-2 text-sm text-gray-500">
          {inProgress
            ? t("card.referenceExampleRecordInProgress")
            : t("card.noReferenceExampleRecord")}
        </p>
      ) : expanded ? (
        <ol className="mt-3 space-y-2">
          {entries.map((entry, index) => {
            const firstSlot = sourceToFirstSlot.get(entry.source);
            const isDuplicate =
              firstSlot !== (entry.slot ?? null) &&
              entries.findIndex((e) => e.source === entry.source) < index;
            return (
              <li
                key={`${entry.timestamp}-${index}`}
                className="rounded border border-teal-200 bg-teal-50 p-3 text-sm"
              >
                <div className="flex flex-wrap items-baseline gap-2 font-semibold">
                  <span>
                    {t("card.referenceExampleRecordEntry")}
                    {entry.slot != null ? ` #${entry.slot}` : ""}
                    {" — "}
                    {entry.kind === "example" ? entry.description : entry.cognitive_process}
                  </span>
                  {isDuplicate && firstSlot != null && (
                    <span
                      aria-label="duplicate"
                      className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800"
                    >
                      {t("card.referenceExampleRecordSameAsPrefix")}
                      {firstSlot}
                      {t("card.referenceExampleRecordSameAsSuffix")}
                    </span>
                  )}
                </div>
                <p className="mt-1">
                  {t("card.referenceExampleRecordStage")}：{entry.stage}
                </p>
                <p className="mt-1">
                  {t("card.referenceExampleRecordSource")}：{entry.source}
                </p>
                <time dateTime={entry.timestamp} className="mt-1 block text-xs text-gray-500">
                  {entry.timestamp}
                </time>
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}
