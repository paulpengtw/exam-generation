import { useEffect, useRef } from "react";
import { useT } from "../i18n/useT";

export interface ProgressLogProps {
  lines: string[];
  status: "idle" | "queued" | "generating" | "error";
  jobsAhead?: number;
  errorMessage?: string | null;
}

export default function ProgressLog({ lines, status, jobsAhead = 0, errorMessage }: ProgressLogProps) {
  const t = useT();
  const preRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const el = preRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  if (lines.length === 0 && status === "idle") {
    return (
      <div className="text-sm text-gray-500 italic">
        {t("progress.empty")}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        {status === "queued" && (
          <>
            <span
              className="inline-block h-3 w-3 animate-pulse rounded-full bg-yellow-400"
              aria-label={t("progress.queued")}
            />
            <span className="text-yellow-700">
              {t("progress.queued_detail").replace("{n}", String(jobsAhead))}
            </span>
          </>
        )}
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
      {status === "error" && errorMessage && (
        <pre className="max-h-64 overflow-y-auto rounded border border-red-300 bg-red-50 p-3 font-mono text-xs text-red-800 whitespace-pre-wrap">
          {errorMessage}
        </pre>
      )}
      <pre
        ref={preRef}
        className="h-64 overflow-y-auto bg-gray-900 text-gray-100 font-mono text-xs p-3 rounded whitespace-pre-wrap"
      >
        {lines.join("\n")}
      </pre>
    </div>
  );
}
