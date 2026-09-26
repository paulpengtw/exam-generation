import { useEffect, useRef } from "react";
import { useT } from "../i18n/useT";
import type { AgentLane, AgentStatus } from "../hooks/useGenerate";
import { Spinner } from "../motion/Indicators";

interface Props {
  lanes: AgentLane[];
  requestedTotal: number;
}

function StatusDot({ status }: { status: AgentStatus }) {
  if (status === "running") {
    return <Spinner className="h-2.5 w-2.5 text-blue-500 flex-shrink-0" />;
  }
  if (status === "done") {
    return <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-500 flex-shrink-0" />;
  }
  if (status === "error") {
    return <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-500 flex-shrink-0" />;
  }
  return <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-300 flex-shrink-0" />;
}

function ElapsedTimer({ startedAt }: { startedAt: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const secs = ((Date.now() / 1000) - startedAt).toFixed(1);
      el.textContent = `${secs}s`;
    };
    update();
    const id = setInterval(update, 100);
    return () => clearInterval(id);
  }, [startedAt]);
  return <span ref={ref} className="font-mono text-xs text-gray-400" />;
}

interface LaneCardProps {
  lane: AgentLane;
  aggregateMode: boolean;
}

function LaneCard({ lane, aggregateMode }: LaneCardProps) {
  const t = useT();
  const contentRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [lane.streamingThinking, lane.streamingContent]);

  const [baseAgent, instanceIdx] = lane.agent.split("#");
  const baseAgentLabel = t(`agent.${baseAgent}` as Parameters<typeof t>[0]) || baseAgent;
  const agentLabel = instanceIdx ? `${baseAgentLabel} #${instanceIdx}` : baseAgentLabel;
  const stageLabel = lane.currentStage
    ? (t(`stage.${lane.currentStage}` as Parameters<typeof t>[0]) || lane.currentStage)
    : null;

  const activeHistory = lane.stageHistory.filter((h) => h.endedAt !== undefined);
  const activeCount = lane.stageHistory.filter(
    (h) => h.endedAt === undefined,
  ).length;
  const completedCount = activeHistory.length;
  const currentEntry = lane.stageHistory.find((h) => h.endedAt === undefined);
  const aggregateStatus: AgentStatus =
    activeCount > 0
      ? "running"
      : lane.status === "error"
      ? "error"
      : completedCount > 0
        ? "done"
        : "idle";
  const effectiveStatus = aggregateMode ? aggregateStatus : lane.status;
  const activeStreamingPane = lane.streamingContent
    ? "content"
    : lane.streamingThinking
      ? "thinking"
      : null;

  return (
    <div className={`rounded-lg border p-3 space-y-2 transition-colors duration-quick ease-signature ${
      effectiveStatus === "running"
        ? "border-blue-300 bg-blue-50"
        : effectiveStatus === "done"
        ? "border-green-200 bg-green-50"
        : effectiveStatus === "error"
        ? "border-red-300 bg-red-50"
        : "border-gray-200 bg-gray-50"
    }`}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <StatusDot status={effectiveStatus} />
        <span className="sentry-unmask text-sm font-semibold text-gray-800">{agentLabel}</span>
        {aggregateMode ? (
          <span
            data-testid="agent-aggregate-counts"
            className="text-xs text-gray-500"
          >
            {t("agent_panel.aggregate_counts")
              .replace("{running}", String(activeCount))
              .replace("{done}", String(completedCount))}
          </span>
        ) : (
          <>
            {stageLabel && (
              <span className="sentry-unmask text-xs text-gray-500 truncate">{stageLabel}</span>
            )}
            {currentEntry && lane.status === "running" && (
              <span className="ml-auto">
                <ElapsedTimer startedAt={currentEntry.startedAt} />
              </span>
            )}
          </>
        )}
      </div>

      {/* Live streaming content */}
      {lane.status === "running" && (lane.streamingThinking || lane.streamingContent) && (
        <div className="space-y-1">
          {lane.streamingThinking && (
            <div>
              <div className="sentry-unmask text-[10px] font-medium text-yellow-600 uppercase tracking-wide mb-0.5">
                {t("agent_panel.thinking")}
              </div>
              <pre
                ref={contentRef}
                data-testid="agent-streaming-thinking"
                className="max-h-24 overflow-y-auto rounded bg-yellow-50 border border-yellow-200 p-1.5 font-mono text-[10px] text-yellow-900 whitespace-pre-wrap"
              >
                {lane.streamingThinking}
                {activeStreamingPane === "thinking" ? (
                  <span className="streaming-caret" aria-hidden="true" />
                ) : null}
              </pre>
            </div>
          )}
          {lane.streamingContent && (
            <div>
              <div className="sentry-unmask text-[10px] font-medium text-green-600 uppercase tracking-wide mb-0.5">
                {t("agent_panel.response")}
              </div>
              <pre
                ref={contentRef}
                data-testid="agent-streaming-content"
                className="max-h-24 overflow-y-auto rounded bg-green-50 border border-green-200 p-1.5 font-mono text-[10px] text-green-900 whitespace-pre-wrap"
              >
                {lane.streamingContent}
                {activeStreamingPane === "content" ? (
                  <span className="streaming-caret" aria-hidden="true" />
                ) : null}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Stage history (completed) */}
      {activeHistory.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer select-none text-gray-400 hover:text-gray-600">
            {t("agent_panel.history")} ({activeHistory.length})
          </summary>
          <div className="mt-1 space-y-0.5">
            {activeHistory.map((h, i) => {
              const dur = h.endedAt ? ((h.endedAt - h.startedAt) * 1000).toFixed(0) : "—";
              const label = t(`stage.${h.stage}` as Parameters<typeof t>[0]) || h.stage;
              return (
                <div key={i} className="flex items-center gap-2 text-gray-500">
                  <span className="text-green-500">✓</span>
                  <span>{label}</span>
                  {h.retry !== undefined && (
                    <span className="text-gray-400">
                      ({t("agent_panel.retry").replace("{n}", String(h.retry))})
                    </span>
                  )}
                  <span className="ml-auto font-mono">{dur}ms</span>
                </div>
              );
            })}
          </div>
        </details>
      )}

      {/* Error message from failed stage */}
      {lane.errorMessage && (
        <div data-testid="stage-error-message" className="rounded border border-red-200 bg-red-50 p-2 text-xs space-y-1">
          <p className="sentry-unmask text-red-700 font-medium">{t("agent_panel.stage_error")}</p>
          <p className="sentry-unmask text-red-600 font-semibold text-[10px]">{t("agent_panel.stage_error_message_label")}</p>
          <pre className="whitespace-pre-wrap text-red-800 font-mono text-[10px] break-all">{lane.errorMessage}</pre>
        </div>
      )}
    </div>
  );
}

export default function AgentStatusPanel({
  lanes,
  requestedTotal,
}: Props) {
  const t = useT();
  const aggregateMode = requestedTotal > 1;

  if (lanes.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-gray-700">{t("agent_panel.title")}</h3>
        {aggregateMode && (
          <span
            data-testid="agent-panel-aggregate-label"
            className="text-xs text-gray-500"
          >
            {t("agent_panel.aggregate_label").replace(
              "{n}",
              String(requestedTotal),
            )}
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {lanes.map((lane) => (
          <LaneCard
            key={lane.agent}
            lane={lane}
            aggregateMode={aggregateMode}
          />
        ))}
      </div>
    </div>
  );
}
