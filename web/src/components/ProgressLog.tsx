import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n/useT";
import type { LlmCallEvent } from "../hooks/useGenerate";
import {
  selectEndedCount,
  selectFinalReceivedCount,
  type RunEvidenceState,
} from "../lib/generationEvidence";

export interface ProgressLogProps {
  lines: string[];
  status: "idle" | "generating" | "error";
  errorMessage?: string | null;
  llmCalls?: LlmCallEvent[];
  evidence?: RunEvidenceState | null;
}

export default function ProgressLog({
  lines,
  status,
  errorMessage,
  llmCalls = [],
  evidence = null,
}: ProgressLogProps) {
  const t = useT();
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

  if (lines.length === 0 && status === "idle" && llmCalls.length === 0 && evidence === null) {
    return (
      <div className="text-sm text-gray-500 italic">
        {t("progress.empty")}
      </div>
    );
  }

  // Group llm events into request blocks for display
  type RequestBlock = {
    key: string;
    request: Extract<LlmCallEvent, { type: "request" }>;
    thinking: string;
    content: string;
    response: Extract<LlmCallEvent, { type: "response" }> | null;
    failure: Extract<LlmCallEvent, { type: "failure" }> | null;
  };

  const blocks: RequestBlock[] = [];
  const blockByCall = new Map<string, RequestBlock>();
  const identityKey = (event: LlmCallEvent): string | null => (
    event.callId ? `${event.runId ?? ""}/${event.callId}` : null
  );
  const findBlock = (event: LlmCallEvent): RequestBlock | undefined => {
    const key = identityKey(event);
    if (key) return blockByCall.get(key);
    const purpose = "purpose" in event ? event.purpose : null;
    if (purpose === null) return undefined;
    for (let index = blocks.length - 1; index >= 0; index -= 1) {
      if (blocks[index].request.purpose === purpose) return blocks[index];
    }
    return undefined;
  };
  for (const ev of llmCalls) {
    if (ev.type === "request") {
      const key = identityKey(ev) ?? `legacy/${blocks.length}`;
      const block: RequestBlock = {
        key,
        request: ev,
        thinking: "",
        content: "",
        response: null,
        failure: null,
      };
      blocks.push(block);
      blockByCall.set(key, block);
    } else if (blocks.length > 0) {
      const b = findBlock(ev);
      if (!b) continue;
      if (ev.type === "thinking") {
        b.thinking += ev.text;
      } else if (ev.type === "content") {
        b.content += ev.text;
      } else if (ev.type === "response") {
        b.response = ev;
      } else if (ev.type === "failure") {
        b.failure = ev;
      }
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        {evidence && (
          <div data-testid="progress-v2-counts" role="status" className="sentry-unmask">
            <span data-testid="progress-v2-ended">
              {t("statusbar.v2_ended")
                .replace("{x}", String(selectEndedCount(evidence)))
                .replace("{n}", String(evidence.total))}
            </span>
            <span aria-hidden="true"> · </span>
            <span data-testid="progress-v2-final">
              {t("statusbar.v2_final_received")
                .replace("{y}", String(selectFinalReceivedCount(evidence)))}
            </span>
          </div>
        )}
        {status === "generating" && !evidence?.closed && (
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
              {blocks.map((b) => {
                const usage = b.response?.usage as Record<string, number> | undefined;
                return (
                  <div key={b.key} className="p-3 space-y-2">
                    {/* Header */}
                    <div className="flex flex-wrap gap-2 text-xs">
                      <span className="rounded bg-blue-100 px-2 py-0.5 font-mono font-medium text-blue-700">
                        {b.request.purpose}
                      </span>
                      <span className="rounded bg-gray-200 px-2 py-0.5 font-mono text-gray-600">
                        {b.request.model}
                      </span>
                      {b.request.callId && (
                        <span className="rounded bg-gray-100 px-2 py-0.5 font-mono text-gray-500">
                          {b.request.callId}
                        </span>
                      )}
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
                    {b.failure && (
                      <div className="text-xs text-red-600">
                        {t("progress.error")} {b.failure.errorType ?? "unknown"}
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
