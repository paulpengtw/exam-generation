import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n/useT";
import type { LlmCallEvent } from "../hooks/useGenerate";
import { Spinner } from "../motion/Indicators";
import { runPhaseLabel, selectRunPhase, type RunPhaseInput } from "../motion/runPhase";

export interface ProgressLogProps extends Omit<RunPhaseInput, "events"> {
  lines: string[];
  status: "idle" | "generating" | "error";
  errorMessage?: string | null;
  llmCalls?: LlmCallEvent[];
}

export default function ProgressLog({ lines, status, errorMessage, llmCalls = [], ...phaseInput }: ProgressLogProps) {
  const t = useT();
  const phase = selectRunPhase({ events: llmCalls, ...phaseInput });
  const fixedPhaseLabel = phase.batch
    ? `${t("statusbar.running")} · ${t("statusbar.completed_prefix")}`
    : t(phase.labelKey);
  const phaseSuffix = runPhaseLabel(phase, t).slice(fixedPhaseLabel.length);
  const preRef = useRef<HTMLPreElement>(null);
  const traceRef = useRef<HTMLDivElement>(null);
  const [showTrace, setShowTrace] = useState(false);

  useEffect(() => {
    const el = preRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  useEffect(() => {
    if (showTrace && traceRef.current) {
      traceRef.current.scrollTop = traceRef.current.scrollHeight;
    }
  }, [llmCalls, showTrace]);

  if (lines.length === 0 && status === "idle" && llmCalls.length === 0) {
    return (
      <div className="text-sm text-gray-500 italic">
        {t("progress.empty")}
      </div>
    );
  }

  // Group llm events into request blocks for display
  type RequestBlock = {
    request: Extract<LlmCallEvent, { type: "request" }>;
    thinking: string;
    content: string;
    response: Extract<LlmCallEvent, { type: "response" }> | null;
  };

  const blocks: RequestBlock[] = [];
  for (const ev of llmCalls) {
    if (ev.type === "request") {
      blocks.push({ request: ev, thinking: "", content: "", response: null });
    } else if (blocks.length > 0) {
      const b = blocks[blocks.length - 1];
      if (ev.type === "thinking" && ev.purpose === b.request.purpose) {
        b.thinking += ev.text;
      } else if (ev.type === "content" && ev.purpose === b.request.purpose) {
        b.content += ev.text;
      } else if (ev.type === "response" && ev.purpose === b.request.purpose) {
        b.response = ev;
      }
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm" role="status">
        {status === "generating" && (
          <>
            <Spinner className="h-3 w-3" />
            <span className="text-gray-600">
              <span className="sentry-unmask">{fixedPhaseLabel}</span>{phaseSuffix}
            </span>
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

      {/* LLM Trace section */}
      {llmCalls.length > 0 && (
        <div className="rounded border border-gray-200 bg-gray-50">
          <button
            className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-gray-600 hover:bg-gray-100"
            onClick={() => setShowTrace((v) => !v)}
          >
            <span>{t("progress.llm_trace")} ({blocks.length} {t("progress.llm_trace_calls")})</span>
            <span>{showTrace ? "▲" : "▼"}</span>
          </button>

          {showTrace && (
            <div
              ref={traceRef}
              className="max-h-[32rem] overflow-y-auto divide-y divide-gray-200"
            >
              {blocks.map((b, i) => {
                const usage = b.response?.usage as Record<string, number> | undefined;
                return (
                  <div key={i} className="p-3 space-y-2">
                    {/* Header */}
                    <div className="flex flex-wrap gap-2 text-xs">
                      <span className="rounded bg-blue-100 px-2 py-0.5 font-mono font-medium text-blue-700">
                        {b.request.purpose}
                      </span>
                      <span className="rounded bg-gray-200 px-2 py-0.5 font-mono text-gray-600">
                        {b.request.model}
                      </span>
                      {usage && (
                        <span className="rounded bg-green-100 px-2 py-0.5 font-mono text-green-700">
                          in={usage.input ?? "?"} out={usage.output ?? "?"}
                        </span>
                      )}
                    </div>

                    {/* Payload */}
                    <details className="text-xs">
                      <summary className="cursor-pointer select-none text-gray-500 hover:text-gray-700">
                        {t("progress.llm_trace_payload")}
                      </summary>
                      <pre className="mt-1 max-h-48 overflow-y-auto rounded bg-gray-800 p-2 font-mono text-xs text-gray-200 whitespace-pre-wrap">
                        {JSON.stringify(b.request.messages, null, 2)}
                      </pre>
                    </details>

                    {/* Thinking */}
                    {b.thinking && (
                      <div>
                        <div className="mb-1 text-xs font-medium text-yellow-600">[thinking]</div>
                        <pre className="max-h-32 overflow-y-auto rounded bg-yellow-50 p-2 font-mono text-xs text-yellow-800 whitespace-pre-wrap">
                          {b.thinking}
                        </pre>
                      </div>
                    )}

                    {/* Content */}
                    {b.content && (
                      <div>
                        <div className="mb-1 text-xs font-medium text-green-600">[response]</div>
                        <pre className="max-h-32 overflow-y-auto rounded bg-green-50 p-2 font-mono text-xs text-green-800 whitespace-pre-wrap">
                          {b.content}
                        </pre>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
