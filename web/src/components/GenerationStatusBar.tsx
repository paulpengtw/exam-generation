import { useEffect, useState } from "react";
import { useT } from "../i18n/useT";
import type { StageEvent } from "../hooks/useGenerate";
import type { ModificationStageEvent } from "../hooks/useModificationRun";
import type { GenerationLegacyEvidence, GenerationV2Evidence, ModificationEvidence, RunEvidence } from "../lib/runEvidence";

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
type StepState = "complete" | "live" | "pending";

interface GenerationStep {
  id: string;
  labelKey: string;
  conditional?: boolean;
  matches: (event: StageEvent) => boolean;
}

const MATH_STEPS: readonly GenerationStep[] = [
  {
    id: "generate",
    labelKey: "statusbar.step_generate",
    matches: (event) =>
      event.agent === "generator" && event.stage === "llm_generate",
  },
  {
    id: "image",
    labelKey: "statusbar.step_image",
    conditional: true,
    matches: (event) =>
      event.agent === "image_agent" && event.stage === "render_image",
  },
  {
    id: "verify",
    labelKey: "statusbar.step_verify",
    matches: (event) =>
      event.agent === "verifier" && event.stage === "verify",
  },
  {
    id: "correct",
    labelKey: "statusbar.step_correct",
    conditional: true,
    matches: (event) =>
      event.agent === "corrector" && event.stage === "correct",
  },
];

const GROUPED_SUBJECT_STEPS: readonly GenerationStep[] = [
  {
    id: "text",
    labelKey: "statusbar.step_text",
    matches: (event) =>
      event.agent === "generator" && event.stage === "llm_generate",
  },
  {
    id: "subquestions",
    labelKey: "statusbar.step_subquestions",
    matches: (event) =>
      /^sub_generator#[1-9]\d*$/.test(event.agent) &&
      event.stage === "llm_generate",
  },
  ...MATH_STEPS.slice(1),
];

function currentStageEvent(events: readonly StageEvent[]): StageEvent | null {
  const activeByAgentAndStage = new Map<string, StageEvent>();

  for (const event of events) {
    const key = `${event.agent}\u0000${event.stage}`;
    if (event.status === "start") {
      activeByAgentAndStage.set(key, event);
    } else {
      activeByAgentAndStage.delete(key);
    }
  }

  return (
    events.findLast((event) => {
      const key = `${event.agent}\u0000${event.stage}`;
      return activeByAgentAndStage.get(key) === event;
    }) ?? null
  );
}

function stepState(
  step: GenerationStep,
  events: readonly StageEvent[],
  currentEvent: StageEvent | null,
): StepState {
  if (currentEvent !== null && step.matches(currentEvent)) return "live";

  const latestStepEvent = events.findLast(step.matches);
  return latestStepEvent?.status === "end" ? "complete" : "pending";
}

function completedSubQuestionWorkers(events: readonly StageEvent[]): number {
  const latestByAgent = new Map<string, StageEvent>();

  for (const event of events) {
    if (
      /^sub_generator#[1-9]\d*$/.test(event.agent) &&
      event.stage === "llm_generate"
    ) {
      latestByAgent.set(event.agent, event);
    }
  }

  return Array.from(latestByAgent.values()).filter(
    (event) => event.status === "end",
  ).length;
}

function GenerationStepBreadcrumb({
  subject,
  evidence,
}: {
  subject: Subject;
  evidence: GenerationLegacyEvidence;
}) {
  const t = useT();
  const { stageEvents: events, subQuestionCount } = evidence;
  const steps = subject === "math" ? MATH_STEPS : GROUPED_SUBJECT_STEPS;
  const relevantEvents = events.filter((event) =>
    steps.some((step) => step.matches(event)),
  );
  const currentEvent = currentStageEvent(relevantEvents);
  const completedSubQuestions = completedSubQuestionWorkers(relevantEvents);

  return (
    <span data-testid="generation-step-breadcrumb" className="sentry-unmask">
      {steps.map((step, index) => {
        const state = stepState(step, relevantEvents, currentEvent);
        const isDim =
          step.conditional === true && !relevantEvents.some(step.matches);
        const stateClass =
          state === "live"
            ? "font-semibold text-blue-600"
            : state === "complete"
              ? "text-green-600"
              : isDim
                ? "text-gray-300"
                : "text-gray-400";
        return (
          <span key={step.id}>
            {index > 0 ? (
              <span className="hidden text-gray-300 sm:inline"> › </span>
            ) : null}
            <span
              data-testid={`generation-step-${step.id}`}
              data-state={state}
              data-dim={isDim}
              className={`${stateClass}${
                state === "live" ? "" : " hidden sm:inline"
              }`}
            >
              {t(step.labelKey)}
              {step.id === "subquestions" && state === "live"
                ? ` ${completedSubQuestions}${
                    subQuestionCount === null ? "" : `/${subQuestionCount}`
                  }`
                : null}
            </span>
          </span>
        );
      })}
    </span>
  );
}

type ModificationStepState = "complete" | "live" | "error";

function visibleModificationSteps(
  events: readonly ModificationStageEvent[],
): Array<{ event: ModificationStageEvent; state: ModificationStepState }> {
  const steps: Array<{
    event: ModificationStageEvent;
    state: ModificationStepState;
  }> = [];

  for (const event of events) {
    if (event.status === "start") {
      steps.push({ event, state: "live" });
      continue;
    }
    const openStep = [...steps]
      .reverse()
      .find((step) => step.event.stage === event.stage && step.state === "live");
    if (openStep) openStep.state = event.status === "error" ? "error" : "complete";
  }
  return steps;
}

function ModificationStepBreadcrumb({
  evidence,
}: {
  evidence: ModificationEvidence;
}) {
  const t = useT();
  const steps = visibleModificationSteps(evidence.steps);
  const labels: Record<ModificationStageEvent["stage"], string> = {
    modification: t("statusbar.step_modify"),
    verify: t("statusbar.step_verify"),
    correct: t("statusbar.step_correct"),
  };

  return (
    <span data-testid="modification-step-breadcrumb" className="sentry-unmask">
      {steps.map(({ event, state }, index) => {
        const stateClass = state === "live"
          ? "font-semibold text-blue-600"
          : state === "error"
            ? "font-semibold text-red-600"
            : "text-green-600";
        return (
          <span key={`${event.stage}-${event.ts}-${index}`}>
            {index > 0 ? <span className="hidden text-gray-300 sm:inline"> › </span> : null}
            <span
              data-testid={`modification-step-${index}`}
              data-state={state}
              className={stateClass}
            >
              {labels[event.stage]}
            </span>
          </span>
        );
      })}
    </span>
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
  startedAt,
  finishedAt,
  availableTargets,
  onJump,
  onFeedback,
}: GenerationStatusBarProps) {
  const t = useT();
  const showGenerationSteps =
    evidence.profile === "generate-legacy" && runState === "running" && requestedTotal === 1;
  const showModificationSteps = evidence.profile === "modification" && runState === "running";
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
              showModificationSteps ? (
                <ModificationStepBreadcrumb evidence={evidence} />
              ) : showGenerationSteps ? (
                <GenerationStepBreadcrumb
                  subject={subject}
                  evidence={evidence}
                />
              ) : showV2Status ? (
                <>
                  <span className="sentry-unmask">◐ {t("statusbar.running")} · </span>
                  <GenerationV2StatusLine evidence={evidence as GenerationV2Evidence} />
                </>
              ) : (
                <>
                  <span className="sentry-unmask">
                    ◐ {t("statusbar.running")} ·{" "}
                    {t("statusbar.completed_prefix")}
                  </span>{" "}
                  {completedCount} / {requestedTotal}
                </>
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
            {runState === "error" ? (
              <span className="sentry-unmask">
                ✕ {t("statusbar.error")}
              </span>
            ) : null}
            {runState === "unknown" ? (
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
