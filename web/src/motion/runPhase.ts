import type { DraftPhase, LlmCallEvent } from "../hooks/useGenerate";
import type { ModificationStageEvent } from "../hooks/useModificationRun";

export type RunPhaseId = "generating" | "generate" | "text" | "subquestions" | "image" | "verify" | "correct" | "modify";
type StageEvent = Extract<LlmCallEvent, { type: "stage" }>;

export interface RunPhaseStep {
  id: RunPhaseId;
  labelKey: string;
  liveLabelKey: string;
  state: "pending" | "live" | "complete" | "error";
  dim: boolean;
}

export interface RunPhaseInput {
  events?: readonly LlmCallEvent[];
  subject?: "math" | "social_studies" | "natural_sciences";
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
  subquestions: { labelKey: "statusbar.step_subquestions", liveLabelKey: "statusbar.phase_subquestions" },
  image: { labelKey: "statusbar.step_image", liveLabelKey: "statusbar.phase_image" },
  verify: { labelKey: "statusbar.step_verify", liveLabelKey: "statusbar.phase_verify" },
  correct: { labelKey: "statusbar.step_correct", liveLabelKey: "statusbar.phase_correct" },
  modify: { labelKey: "statusbar.step_modify", liveLabelKey: "statusbar.phase_modify" },
};

function phaseForStage(event: StageEvent, modification: boolean, flatMath: boolean): RunPhaseId | null {
  if (modification && event.stage === "modification") return "modify";
  if (event.stage === "verify") return "verify";
  if (event.stage === "correct") return "correct";
  if (event.stage === "render_image") return "image";
  if (event.stage === "llm_generate") {
    if (/^sub_generator#[1-9]\d*$/.test(event.agent)) return "subquestions";
    if (event.agent === "generator") return flatMath ? "generate" : "text";
  }
  return null;
}

/** Shared live wording for the bar, progress log, and an indexed batch card. */
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
  const flatMath = subject === "math" && !(subQuestionCount !== null && subQuestionCount > 0)
    && !events.some((event) => event.type === "stage" && event.agent.startsWith("sub_generator#"));
  const phaseFor = (event: StageEvent) => phaseForStage(event, modification, flatMath);
  const stages = (modification ? modificationStageEvents : events).filter(
    (event): event is StageEvent => event.type === "stage" && phaseFor(event) !== null,
  );
  const active = new Map<string, StageEvent>();
  const latestWorker = new Map<string, StageEvent>();
  for (const event of stages) {
    const key = `${event.agent}\u0000${event.stage}`;
    if (event.status === "start") active.set(key, event);
    else active.delete(key);
    if (phaseFor(event) === "subquestions") latestWorker.set(event.agent, event);
  }
  const current = stages.findLast((event) => active.get(`${event.agent}\u0000${event.stage}`) === event);
  const latest = stages.at(-1);
  const fallback: Record<DraftPhase, RunPhaseId> = {
    draft: flatMath ? "generate" : "text", image: "image", verified: "verify", corrected: "correct",
  };
  const id = (current ? phaseFor(current) : null)
    ?? (latest ? phaseFor(latest) : null)
    ?? (modification ? "modify" : draftPhase ? fallback[draftPhase] : "generating");
  const stepIds: RunPhaseId[] = modification
    ? ["modify", "verify", "correct"]
    : flatMath ? ["generate", "image", "verify", "correct"]
      : ["text", "subquestions", "image", "verify", "correct"];
  let steps: RunPhaseStep[] = id === "generating" ? [] : stepIds.map((stepId) => {
    const last = stages.findLast((event) => phaseFor(event) === stepId);
    const live = current ? phaseFor(current) === stepId : !latest && id === stepId;
    return {
      id: stepId,
      ...LABELS[stepId],
      state: live ? "live" : last?.status === "end" ? "complete" : last?.status === "error" ? "error" : "pending",
      dim: (stepId === "image" || stepId === "correct") && !last,
    };
  });
  // Keep re-verification visible when a modification needs another correction cycle.
  if (modification && stages.length > 0) {
    const history: RunPhaseStep[] = [];
    let furthestStep = -1;
    for (const event of stages) {
      const stepId = phaseFor(event);
      if (stepId === null) continue;
      furthestStep = Math.max(furthestStep, stepIds.indexOf(stepId));
      if (event.status === "start") {
        history.push({ id: stepId, ...LABELS[stepId], state: "live", dim: false });
      } else {
        const open = history.findLast((step) => step.id === stepId && step.state === "live");
        if (open) open.state = event.status === "error" ? "error" : "complete";
      }
    }
    steps = [...history, ...steps.slice(furthestStep + 1)];
  }
  return {
    id,
    labelKey: LABELS[id].liveLabelKey,
    steps,
    subQuestionCount,
    completedSubQuestions: [...latestWorker.values()].filter((event) => event.status === "end").length,
    batch: !modification && requestedTotal > 1 ? { completed: completedCount, total: requestedTotal } : null,
  };
}

export function runPhaseLabel(phase: RunPhaseSelection, t: (key: string) => string): string {
  if (phase.batch) {
    return `${t("statusbar.running")} · ${t("statusbar.completed_prefix")} ${phase.batch.completed} / ${phase.batch.total}`;
  }
  return `${t(phase.labelKey)}${phase.id === "subquestions"
    ? ` ${phase.completedSubQuestions}${phase.subQuestionCount === null ? "" : `/${phase.subQuestionCount}`}`
    : ""}`;
}
