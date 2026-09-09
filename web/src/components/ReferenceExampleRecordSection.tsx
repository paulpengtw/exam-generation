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
}

export default function ReferenceExampleRecordSection({
  record,
}: ReferenceExampleRecordSectionProps) {
  const t = useT();

  if (record === undefined) return null;

  if (record === null) {
    return (
      <section
        aria-label={t("card.referenceExampleRecord")}
        className="rounded border border-gray-200 bg-gray-50 p-3"
      >
        <h3 className="font-semibold text-gray-800">{t("card.referenceExampleRecord")}</h3>
        <p className="mt-2 text-sm text-gray-500">{t("card.noReferenceExampleRecord")}</p>
      </section>
    );
  }

  const entries = record.entries ?? [];

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
      <h3 className="font-semibold text-gray-800">{t("card.referenceExampleRecord")}</h3>
      {entries.length === 0 ? (
        <p className="mt-2 text-sm text-gray-500">{t("card.noReferenceExampleRecord")}</p>
      ) : (
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
      )}
    </section>
  );
}
