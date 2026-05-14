import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

export interface ProgressLogProps {
  lines: string[];
  status: "idle" | "generating" | "error";
}

export default function ProgressLog({ lines, status }: ProgressLogProps) {
  const { t } = useTranslation();
  const preRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const el = preRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  if (lines.length === 0 && status === "idle") {
    return (
      <div className="text-sm text-gray-500 italic">
        {t("progress.placeholder")}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        {status === "generating" && (
          <>
            <span
              className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-gray-300 border-t-blue-500"
              aria-label={t("progress.generating")}
            />
            <span className="text-gray-600">{t("progress.generating")}</span>
          </>
        )}
        {status === "idle" && lines.length > 0 && (
          <span className="text-green-600 font-medium">{t("progress.done")}</span>
        )}
        {status === "error" && (
          <span className="text-red-600 font-medium">{t("progress.error")}</span>
        )}
      </div>
      <pre
        ref={preRef}
        className="h-64 overflow-y-auto bg-gray-900 text-gray-100 font-mono text-xs p-3 rounded whitespace-pre-wrap"
      >
        {lines.join("\n")}
      </pre>
    </div>
  );
}
