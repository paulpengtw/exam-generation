import { useEffect, useState } from "react";
import { useT } from "../i18n/useT";
import type { LlmCallEvent } from "../hooks/useGenerate";
import type { ModificationStageEvent } from "../hooks/useModificationRun";
import { Shimmer, Spinner } from "../motion/Indicators";
import { selectRunPhase, type RunPhaseSelection } from "../motion/runPhase";

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

export type RunState = "idle" | "running" | "done" | "error";
export type JumpTarget = "form" | "progress" | "results";
type Subject = "math" | "social_studies" | "natural_sciences";
function PhaseBreadcrumb({ phase, modification }: {
  phase: RunPhaseSelection;
  modification: boolean;
}) {
  const t = useT();
  if (phase.batch) {
    return (
      <Shimmer>
        <span className="sentry-unmask">
          {t("statusbar.running")} · {t("statusbar.completed_prefix")}
        </span>{" "}
        {phase.batch.completed} / {phase.batch.total}
      </Shimmer>
    );
  }
  if (phase.steps.length === 0) {
    return <Shimmer className="sentry-unmask">{t("statusbar.running")}</Shimmer>;
  }
  return (
    <span data-testid={modification ? "modification-step-breadcrumb" : "generation-step-breadcrumb"}>
      {phase.steps.map((step, index) => {
        const stateClass = step.state === "live"
          ? "font-semibold text-blue-600"
          : step.state === "complete"
            ? "text-green-600"
            : step.state === "error"
              ? "text-red-600"
              : step.dim ? "text-gray-300" : "text-gray-400";
        return (
          <span key={`${step.id}-${index}`}>
            {index > 0 && <span className="hidden text-gray-300 sm:inline"> › </span>}
            <span
              data-testid={modification ? `modification-step-${index}` : `generation-step-${step.id}`}
              data-state={step.state}
              data-dim={step.dim}
              className={`${stateClass}${step.state === "live" ? "" : " hidden sm:inline"}`}
            >
              {step.state === "live" ? (
                <Shimmer>
                  <span className="sentry-unmask">{t(step.liveLabelKey)}</span>
                  {step.id === "subquestions" && ` ${phase.completedSubQuestions}${phase.subQuestionCount === null ? "" : `/${phase.subQuestionCount}`}`}
                </Shimmer>
              ) : (
                <span className="sentry-unmask">{t(step.labelKey)}</span>
              )}
            </span>
          </span>
        );
      })}
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
  subject: Subject;
  stageEvents: LlmCallEvent[];
  subQuestionCount: number | null;
  startedAt: number | null;
  finishedAt: number | null;
  availableTargets: readonly JumpTarget[];
  onJump: (target: JumpTarget) => void;
  onFeedback: (() => void) | null;
  mode?: "generation" | "modification";
  modificationStageEvents?: readonly ModificationStageEvent[];
  handoff?: boolean;
}

export default function GenerationStatusBar({
  runState,
  completedCount,
  requestedTotal,
  subject = "math",
  stageEvents = [],
  subQuestionCount = null,
  startedAt,
  finishedAt,
  availableTargets,
  onJump,
  onFeedback,
  mode = "generation",
  modificationStageEvents = [],
  handoff = false,
}: GenerationStatusBarProps) {
  const t = useT();
  const phase = selectRunPhase({
    events: stageEvents,
    subject,
    mode,
    modificationStageEvents,
    subQuestionCount,
    requestedTotal,
    completedCount,
  });

  return (
    <div
      aria-label={t("statusbar.aria")}
      className={`fixed inset-x-0 bottom-0 z-40 border-t border-gray-300 bg-white shadow-[0_-4px_12px_rgba(0,0,0,0.08)]${handoff ? " handoff-highlight" : ""}`}
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
                  : "text-gray-500"
          }`}
        >
          {runState === "running" && <Spinner className="statusbar-running-indicator h-3 w-3 shrink-0" />}
          <span data-testid="statusbar-status" className="truncate" role="status">
            {runState === "idle" ? (
              <span className="sentry-unmask">
                {t("statusbar.not_started")}
              </span>
            ) : null}
            {runState === "running" && (
              <PhaseBreadcrumb phase={phase} modification={mode === "modification"} />
            )}
            {runState === "done" &&
            startedAt !== null &&
            finishedAt !== null ? (
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
            ) : null}
            {runState === "error" ? (
              <span className="sentry-unmask">
                ✕ {t("statusbar.error")}
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
