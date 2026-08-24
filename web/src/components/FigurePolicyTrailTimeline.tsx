import type { FigurePolicyTrailEntry } from "../hooks/useGenerate";
import { useT } from "../i18n/useT";

export interface FigurePolicyTrailTimelineProps {
  entries: FigurePolicyTrailEntry[] | null;
}

export default function FigurePolicyTrailTimeline({
  entries,
}: FigurePolicyTrailTimelineProps) {
  const t = useT();
  if (entries === null) {
    return (
      <section
        aria-label={t("card.figurePolicyTrail")}
        className="rounded border border-gray-200 bg-gray-50 p-3"
      >
        <h3 className="font-semibold text-gray-800">{t("card.figurePolicyTrail")}</h3>
        <p className="mt-2 text-sm text-gray-600">{t("card.noFigurePolicyTrail")}</p>
      </section>
    );
  }

  if (entries.length === 0) return null;

  return (
    <section
      aria-label={t("card.figurePolicyTrail")}
      className="rounded border border-gray-200 bg-gray-50 p-3"
    >
      <h3 className="font-semibold text-gray-800">{t("card.figurePolicyTrail")}</h3>
      <ol className="mt-3 space-y-2">
        {entries.map((entry, index) => (
          <li
            key={`${entry.timestamp}-${index}`}
            className="rounded border border-purple-200 bg-purple-50 p-3 text-sm"
          >
            <div className="font-semibold">
              {entry.kind === "spec" && `${t("card.figurePolicySpec")}：${entry.label}`}
              {entry.kind === "collision" && t("card.figurePolicyCollision")}
              {entry.kind === "repair" && t("card.figurePolicyRepair")}
              {entry.kind === "warning" && t("card.figurePolicyWarning")}
            </div>
            {entry.kind === "spec" && (
              <p className="mt-1">
                {t("card.figurePolicyEffectiveKind")}：{entry.effective_figure_kind || "—"}
              </p>
            )}
            {entry.kind === "collision" && (
              <p className="mt-1">
                {entry.left} × {entry.right}：{entry.effective_figure_kind}
              </p>
            )}
            {entry.kind === "repair" && (
              <p className="mt-1">
                {entry.target}：{entry.before_effective_figure_kind} → {entry.after_effective_figure_kind}
              </p>
            )}
            {entry.kind === "warning" && (
              <p className="mt-1 whitespace-pre-wrap text-amber-800">{entry.message}</p>
            )}
            <time dateTime={entry.timestamp} className="mt-1 block text-xs text-gray-500">
              {entry.timestamp}
            </time>
          </li>
        ))}
      </ol>
    </section>
  );
}
