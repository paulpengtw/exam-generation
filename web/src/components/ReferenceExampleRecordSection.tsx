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

export interface ReferenceExampleRecordSectionProps {
  entries?: ReferenceExampleEntryShape[] | null;
}

export default function ReferenceExampleRecordSection({
  entries,
}: ReferenceExampleRecordSectionProps) {
  const t = useT();
  const visible = entries ?? [];
  if (visible.length === 0) return null;

  return (
    <section
      aria-label={t("card.referenceExampleRecord")}
      className="rounded border border-gray-200 bg-gray-50 p-3"
    >
      <h3 className="font-semibold text-gray-800">{t("card.referenceExampleRecord")}</h3>
      <ol className="mt-3 space-y-2">
        {visible.map((entry, index) => (
          <li
            key={`${entry.timestamp}-${index}`}
            className="rounded border border-teal-200 bg-teal-50 p-3 text-sm"
          >
            <div className="font-semibold">
              {t("card.referenceExampleRecordEntry")}
              {entry.slot != null ? ` #${entry.slot}` : ""}
              {" — "}
              {entry.kind === "example" ? entry.description : entry.cognitive_process}
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
        ))}
      </ol>
    </section>
  );
}
