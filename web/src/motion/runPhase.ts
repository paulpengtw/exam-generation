import type { DraftPhase, LlmCallEvent } from "../hooks/useGenerate";
import type { ModificationStageEvent } from "../lib/modificationStream";

export type RunPhaseId =
  | "generating"
  | "generate"
  | "text"
  | "subquestions"
  | "image"
  | "verify"
  | "correct"
  | "modify";

type Subject = "math" | "social_studies" | "natural_sciences";
type StageEvent = Extract<LlmCallEvent, { type: "stage" }>;

export interface RunPhaseStep {
  id: Exclude<RunPhaseId, "generating">;
  labelKey: string;
  liveLabelKey: string;
  state: "pending" | "live" | "complete" | "error";
  dim: boolean;
  message?: string;
}

export interface RunPhaseInput {
  events?: readonly LlmCallEvent[];
  subject?: Subject;
  mode?: "generation" | "modification";
  modificationStageEvents?: readonly ModificationStageEvent[];
  subQuestionCount?: number | null;
  requestedTotal?: number;
  completedCount?: number;
  /** Fallback for a draft whose stream did not include question-indexed stages. */
  draftPhase?: DraftPhase;
}

export interface RunPhaseSelection {
  id: RunPhaseId;
  labelKey: string;
  steps: RunPhaseStep[];
  subQuestionCount: number | null;
  completedSubQuestions: number;
  batch: { completed: number; total: number } | null;
}

const LABELS: Record<RunPhaseId, { labelKey: string; liveLabelKey: string }> = {
  generating: { labelKey: "statusbar.running", liveLabelKey: "statusbar.running" },
  generate: { labelKey: "statusbar.step_generate", liveLabelKey: "statusbar.running" },
  text: { labelKey: "statusbar.step_text", liveLabelKey: "statusbar.phase_text" },
  subquestions: {
    labelKey: "statusbar.step_subquestions",
    liveLabelKey: "statusbar.phase_subquestions",
  },
  image: { labelKey: "statusbar.step_image", liveLabelKey: "statusbar.phase_image" },
  verify: { labelKey: "statusbar.step_verify", liveLabelKey: "statusbar.phase_verify" },
  correct: { labelKey: "statusbar.step_correct", liveLabelKey: "statusbar.phase_correct" },
  modify: { labelKey: "statusbar.step_modify", liveLabelKey: "statusbar.phase_modify" },
};

function isSubQuestionAgent(agent: string): boolean {
  return /^sub_generator#[1-9]\d*$/.test(agent);
}

function phaseForStage(
  event: StageEvent,
  modification: boolean,
  flatMath: boolean,
): RunPhaseId | null {
  if (modification && event.stage === "modification") return "modify";
  if (event.stage === "verify" || event.agent === "verifier") return "verify";
  if (event.stage === "correct" || event.agent === "corrector") return "correct";
  if (
    event.stage === "render_image"
    || event.agent === "image_agent"
    || event.stage.includes("image")
  ) {
    return "image";
  }
  if (isSubQuestionAgent(event.agent) || event.stage === "subquestion") {
    return "subquestions";
  }
  if (
    event.stage === "llm_generate"
    || event.stage === "generate"
    || event.agent === "generator"
    || event.agent === "execute"
  ) {
    return flatMath ? "generate" : "text";
  }
  return null;
}

function phaseIndex(
  stepIds: readonly Exclude<RunPhaseId, "generating">[],
  id: RunPhaseId,
): number {
  return id === "generating" ? -1 : stepIds.indexOf(id);
}

function modificationPhaseId(
  stage: ModificationStageEvent["stage"],
): Exclude<RunPhaseId, "generating"> {
  return stage === "modification" ? "modify" : stage;
}

function currentStage<T extends {
  agent: string;
  stage: string;
  status: "start" | "end" | "error";
}>(
  events: readonly T[],
): T | null {
  const active = new Map<string, T>();
  for (const event of events) {
    const key = `${event.agent}\u0000${event.stage}`;
    if (event.status === "start") active.set(key, event);
    else active.delete(key);
  }
  return events.findLast((event) => (
    active.get(`${event.agent}\u0000${event.stage}`) === event
  )) ?? null;
}

function generationSteps(
  stages: readonly StageEvent[],
  stepIds: readonly Exclude<RunPhaseId, "generating">[],
  phaseFor: (event: StageEvent) => RunPhaseId | null,
  current: StageEvent | null,
  fallbackId: RunPhaseId | null,
): RunPhaseStep[] {
  return stepIds.map((stepId) => {
    const latest = stages.findLast((event) => phaseFor(event) === stepId);
    const isLive = current !== null
      ? phaseFor(current) === stepId
      : latest === undefined && fallbackId === stepId;
    const state: RunPhaseStep["state"] = isLive
      ? "live"
      : latest?.status === "end"
        ? "complete"
        : latest?.status === "error"
          ? "error"
          : "pending";
    return {
      id: stepId,
      ...LABELS[stepId],
      state,
      dim: (stepId === "image" || stepId === "correct") && latest === undefined,
      ...(latest?.message ? { message: latest.message } : {}),
    };
  });
}

function modificationSteps(
  stages: readonly ModificationStageEvent[],
  stepIds: readonly Exclude<RunPhaseId, "generating">[],
  current: ModificationStageEvent | null,
): RunPhaseStep[] {
  if (stages.length === 0) {
    return stepIds.map((id, index) => ({
      id,
      ...LABELS[id],
      state: index === 0 ? "live" : "pending",
      dim: false,
    }));
  }

  const history: RunPhaseStep[] = [];
  let furthest = -1;
  for (const event of stages) {
    const id = modificationPhaseId(event.stage);
    furthest = Math.max(furthest, phaseIndex(stepIds, id));
    if (event.status === "start") {
      history.push({ id, ...LABELS[id], state: "live", dim: false });
      continue;
    }
    const open = history.findLast((step) => step.id === id && step.state === "live");
    if (open) {
      open.state = event.status === "error" ? "error" : "complete";
      if (event.status === "error" && event.message) open.message = event.message;
    }
  }

  const tail = stepIds.slice(furthest + 1).map((id) => ({
    id,
    ...LABELS[id],
    state: current?.stage === id ? "live" as const : "pending" as const,
    dim: false,
  }));
  return [...history, ...tail];
}

function completedSubQuestions(events: readonly StageEvent[]): number {
  const latestByAgent = new Map<string, StageEvent>();
  for (const event of events) {
    if (isSubQuestionAgent(event.agent) && event.stage === "llm_generate") {
      latestByAgent.set(event.agent, event);
    }
  }
  return [...latestByAgent.values()].filter((event) => event.status === "end").length;
}

/**
 * Selects the shared on-screen phase for the status bar, progress log, and
 * in-flight result cards. It contains no locale or rendering logic.
 */
export function selectRunPhase({
  events = [],
  subject = "math",
  mode = "generation",
  modificationStageEvents = [],
  subQuestionCount = null,
  requestedTotal = 1,
  completedCount = 0,
  draftPhase,
}: RunPhaseInput = {}): RunPhaseSelection {
  const modification = mode === "modification";
  const hasSubQuestionWorker = events.some(
    (event) => event.type === "stage" && isSubQuestionAgent(event.agent),
  );
  const flatMath = subject === "math"
    && !(subQuestionCount !== null && subQuestionCount > 0)
    && !hasSubQuestionWorker;
  const phaseFor = (event: StageEvent) => phaseForStage(event, modification, flatMath);
  const stages = events.filter(
    (event): event is StageEvent => event.type === "stage" && phaseFor(event) !== null,
  );
  const current = modification
    ? currentStage(modificationStageEvents)
    : currentStage(stages);
  const latest = modification
    ? modificationStageEvents.length > 0
      ? modificationPhaseId(modificationStageEvents.at(-1)!.stage)
      : null
    : stages.length > 0 ? phaseFor(stages.at(-1)!) : null;
  const fallback: Record<DraftPhase, RunPhaseId> = {
    draft: flatMath ? "generate" : "text",
    image: "image",
    verified: "verify",
    corrected: "correct",
  };
  const currentId = current === null
    ? null
    : modification
      ? modificationPhaseId((current as ModificationStageEvent).stage)
      : phaseFor(current as StageEvent);
  const id = currentId
    ?? latest
    ?? (modification ? "modify" : draftPhase ? fallback[draftPhase] : "generating");
  const stepIds: Exclude<RunPhaseId, "generating">[] = modification
    ? ["modify", "verify", "correct"]
    : flatMath
      ? ["generate", "image", "verify", "correct"]
      : ["text", "subquestions", "image", "verify", "correct"];
  const steps = id === "generating"
    ? []
    : modification
      ? modificationSteps(
        modificationStageEvents,
        stepIds,
        current as ModificationStageEvent | null,
      )
      : generationSteps(
        stages,
        stepIds,
        phaseFor,
        current as StageEvent | null,
        id,
      );

  return {
    id,
    labelKey: LABELS[id].liveLabelKey,
    steps,
    subQuestionCount,
    completedSubQuestions: completedSubQuestions(stages),
    batch: !modification && requestedTotal > 1
      ? { completed: completedCount, total: requestedTotal }
      : null,
  };
}

export function runPhaseLabel(
  phase: RunPhaseSelection,
  t: (key: string) => string,
): string {
  if (phase.batch) {
    return `${t("statusbar.running")} · ${t("statusbar.completed_prefix")} ${phase.batch.completed} / ${phase.batch.total}`;
  }
  return `${t(phase.labelKey)}${phase.id === "subquestions"
    ? ` ${phase.completedSubQuestions}${phase.subQuestionCount === null ? "" : `/${phase.subQuestionCount}`}`
    : ""}`;
}
