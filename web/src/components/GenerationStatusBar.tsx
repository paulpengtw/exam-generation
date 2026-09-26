import { useEffect, useState } from "react";
import { useT } from "../i18n/useT";
import type { LlmCallEvent } from "../hooks/useGenerate";
import type { GenerationV2Evidence, RunEvidence } from "../lib/runEvidence";
import { Shimmer } from "../motion/Indicators";
import {
  runPhaseLabel,
  selectRunPhase,
  type RunPhaseSelection,
} from "../motion/runPhase";

function formatDuration(
  durationMs: number,
  minuteUnit: string,
  secondUnit: string,
) {
  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes > 0 ? `${minutes}${minuteUnit}` : ""}${seconds}${secondUnit}`;
}

function ElapsedTime({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(startedAt);
  const t = useT();

  useEffect(() => {
    const intervalId = setInterval(() => {
      setNow(Date.now());
    }, 1000);

    return () => clearInterval(intervalId);
  }, []);

  return (
    <span
      data-testid="statusbar-elapsed"
      className="shrink-0 whitespace-nowrap tabular-nums"
    >
      {formatDuration(
        now - startedAt,
        t("statusbar.unit_minute"),
        t("statusbar.unit_second"),
      )}
    </span>
  );
}

export type RunState = "idle" | "running" | "done" | "error" | "unknown";
export type JumpTarget = "form" | "progress" | "results";
type Subject = "math" | "social_studies" | "natural_sciences";

function stateClass(
  state: RunPhaseSelection["steps"][number]["state"],
  dim: boolean,
): string {
  if (state === "live") return "font-semibold text-blue-600";
  if (state === "complete") return "text-green-600";
  if (state === "error") return "font-semibold text-red-600";
  return dim ? "text-gray-300" : "text-gray-400";
}

function PhaseBreadcrumb({
  phase,
  modification,
}: {
  phase: RunPhaseSelection;
  modification: boolean;
}) {
  const t = useT();
  const testPrefix = modification ? "modification-step" : "generation-step";
  const breadcrumbTestId = modification
    ? "modification-step-breadcrumb"
    : "generation-step-breadcrumb";

  return (
    <span data-testid={breadcrumbTestId} className="sentry-unmask">
      {phase.steps.map((step, index) => {
        const live = step.state === "live";
        const label = live ? t(step.liveLabelKey) : t(step.labelKey);
        const count = live && step.id === "subquestions"
          ? ` ${phase.completedSubQuestions}${phase.subQuestionCount === null ? "" : `/${phase.subQuestionCount}`}`
          : "";
        const visibleClass = modification || live ? "" : " hidden sm:inline";
        return (
          <span key={`${step.id}-${index}`}>
            {index > 0 ? (
              <span className="hidden text-gray-300 sm:inline"> › </span>
            ) : null}
            <span
              data-testid={`${testPrefix}-${modification ? index : step.id}`}
              data-state={step.state}
              data-dim={step.dim}
              title={step.state === "error" ? step.message : undefined}
              className={`${stateClass(step.state, step.dim)}${visibleClass}`}
            >
              {live ? (
                <Shimmer>
                  <span className="sentry-unmask">{label}</span>
                  {count}
                </Shimmer>
              ) : (
                <span className="sentry-unmask">{label}{count}</span>
              )}
            </span>
          </span>
        );
      })}
    </span>
  );
}

function RunningLabel({ phase }: { phase: RunPhaseSelection }) {
  const t = useT();
  return (
    <Shimmer>
      <span className="sentry-unmask">{runPhaseLabel(phase, t)}</span>
    </Shimmer>
  );
}

function BatchRunningLabel({ phase }: { phase: RunPhaseSelection }) {
  const t = useT();
  const batch = phase.batch;
  if (batch === null) return <RunningLabel phase={phase} />;
  return (
    <Shimmer>
      <span className="sentry-unmask">
        {t("statusbar.running")} · {t("statusbar.completed_prefix")}
      </span>{" "}
      {batch.completed} / {batch.total}
    </Shimmer>
  );
}

function GenerationV2StatusLine({ evidence }: { evidence: GenerationV2Evidence }) {
  const t = useT();
  const endedLabel = (t("statusbar.v2_ended") as string)
    .replace("{x}", String(evidence.endedCount))
    .replace("{n}", String(evidence.total));
  const finalLabel = (t("statusbar.v2_final_received") as string)
    .replace("{y}", String(evidence.finalReceivedCount));
  return (
    <span className="sentry-unmask">
      <span data-testid="statusbar-v2-ended">{endedLabel}</span>
      {" · "}
      <span data-testid="statusbar-v2-final">{finalLabel}</span>
    </span>
  );
}

const JUMP_BUTTONS: readonly {
  target: JumpTarget;
  labelKey: string;
}[] = [
  { target: "form", labelKey: "statusbar.jump_form" },
  { target: "progress", labelKey: "statusbar.jump_progress" },
  { target: "results", labelKey: "statusbar.jump_results" },
];

export interface GenerationStatusBarProps {
  runState: RunState;
  completedCount: number;
  requestedTotal: number;
  subject?: Subject;
  evidence: RunEvidence;
  /** Raw stage events are also available for the v2 transport projection. */
  events?: readonly LlmCallEvent[];
  startedAt: number | null;
  finishedAt: number | null;
  availableTargets: readonly JumpTarget[];
  onJump: (target: JumpTarget) => void;
  onFeedback: (() => void) | null;
}

export default function GenerationStatusBar({
  runState,
  completedCount,
  requestedTotal,
  subject = "math",
  evidence,
  events,
  startedAt,
  finishedAt,
  availableTargets,
  onJump,
  onFeedback,
}: GenerationStatusBarProps) {
  const t = useT();
  const modification = evidence.profile === "modification";
  const phaseEvents = events ?? (
    evidence.profile === "generate-legacy" ? evidence.stageEvents : []
  );
  const phase = selectRunPhase({
    events: phaseEvents,
    subject,
    mode: modification ? "modification" : "generation",
    modificationStageEvents: modification ? evidence.steps : [],
    subQuestionCount: evidence.profile === "generate-legacy"
      ? evidence.subQuestionCount
      : null,
    requestedTotal,
    completedCount,
  });
  const showGenerationSteps =
    evidence.profile === "generate-legacy" && runState === "running" && requestedTotal === 1;
  const showModificationSteps = modification && runState === "running";
  const showV2Status = evidence.profile === "generate-v2";

  return (
    <div
      aria-label={t("statusbar.aria")}
      className="fixed inset-x-0 bottom-0 z-40 border-t border-gray-300 bg-white shadow-[0_-4px_12px_rgba(0,0,0,0.08)]"
    >
      <div className="mx-auto flex h-12 max-w-5xl flex-nowrap items-center gap-2 whitespace-nowrap px-3 text-xs sm:px-4 sm:text-sm">
        <div
          className={`flex min-w-0 items-center gap-2 ${
            runState === "running"
              ? "text-blue-600"
              : runState === "done"
                ? "text-green-600"
                : runState === "error"
                  ? "text-red-600"
                  : runState === "unknown"
                    ? "text-amber-700"
                    : "text-gray-500"
          }`}
        >
          <span data-testid="statusbar-status" className="truncate">
            {runState === "idle" ? (
              <span className="sentry-unmask">
                {t("statusbar.not_started")}
              </span>
            ) : null}
            {runState === "running" ? (
              showModificationSteps || showGenerationSteps ? (
                phase.steps.length > 0 ? (
                  <PhaseBreadcrumb phase={phase} modification={modification} />
                ) : (
                  <RunningLabel phase={phase} />
                )
              ) : showV2Status ? (
                <>
                  <BatchRunningLabel phase={phase} />
                  <span aria-hidden="true"> · </span>
                  <GenerationV2StatusLine evidence={evidence as GenerationV2Evidence} />
                </>
              ) : (
                <BatchRunningLabel phase={phase} />
              )
            ) : null}
            {runState === "done" &&
            startedAt !== null &&
            finishedAt !== null ? (
              showV2Status ? (
                <>
                  <span className="sentry-unmask">✓ {t("statusbar.done")} · </span>
                  <GenerationV2StatusLine evidence={evidence as GenerationV2Evidence} />
                </>
              ) : (
                <>
                  <span className="sentry-unmask">
                    ✓ {t("statusbar.done")}
                  </span>{" "}
                  {completedCount}{" "}
                  <span className="sentry-unmask">
                    {t("statusbar.unit_question")} ·
                  </span>{" "}
                  {formatDuration(
                    finishedAt - startedAt,
                    t("statusbar.unit_minute"),
                    t("statusbar.unit_second"),
                  )}
                </>
              )
            ) : null}
            {runState === "error" && showV2Status ? (
              <>
                <span className="sentry-unmask">✕ {t("statusbar.error")} · </span>
                <GenerationV2StatusLine evidence={evidence as GenerationV2Evidence} />
              </>
            ) : null}
            {runState === "error" && !showV2Status ? (
              <span className="sentry-unmask">
                ✕ {t("statusbar.error")}
              </span>
            ) : null}
            {runState === "unknown" && showV2Status ? (
              <>
                <span className="sentry-unmask">? {t("statusbar.unknown")} · </span>
                <GenerationV2StatusLine evidence={evidence as GenerationV2Evidence} />
              </>
            ) : null}
            {runState === "unknown" && !showV2Status ? (
              <span className="sentry-unmask">
                ? {t("statusbar.unknown")}
              </span>
            ) : null}
          </span>
          {runState === "running" && startedAt !== null ? (
            <ElapsedTime startedAt={startedAt} />
          ) : null}
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-1 sm:gap-2">
          {JUMP_BUTTONS.map(({ target, labelKey }) => (
            <button
              key={target}
              type="button"
              disabled={!availableTargets.includes(target)}
              onClick={() => onJump(target)}
              className="sentry-unmask rounded border border-gray-300 bg-white px-1.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 sm:px-2 sm:text-sm"
            >
              {t(labelKey)}
            </button>
          ))}
          {onFeedback !== null ? (
            <button
              type="button"
              onClick={onFeedback}
              className="sentry-unmask rounded border border-blue-600 bg-white px-1.5 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 sm:px-2 sm:text-sm"
            >
              {t("statusbar.feedback")}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
