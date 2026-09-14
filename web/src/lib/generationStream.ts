import type {
  DraftPhase,
  FigurePolicyTrailEntry,
  GeneratedQuestion,
  LlmCallEvent,
  ReferenceExampleRecordShape,
  VerificationTrailEntry,
} from "../hooks/useGenerate";
import type { GenerationLegacyEvidence } from "./runEvidence";

export function projectGenerationEvidence(
  llmCalls: readonly LlmCallEvent[],
  subQuestionCount: number | null,
): GenerationLegacyEvidence {
  return {
    profile: "generate-legacy",
    stageEvents: llmCalls.filter((event) => event.type === "stage"),
    subQuestionCount,
  };
}

export type GenerationCardEvidence = {
  phase: DraftPhase;
  isFinal: boolean;
  trail: VerificationTrailEntry[];
  figurePolicyTrail: FigurePolicyTrailEntry[];
  referenceExampleRecord: ReferenceExampleRecordShape | undefined;
};

export function projectGenerationCardEvidence(item: GeneratedQuestion): GenerationCardEvidence {
  return {
    phase: item.phase,
    isFinal: item.isFinal,
    trail: item.trail ?? [],
    figurePolicyTrail: item.figurePolicyTrail ?? [],
    referenceExampleRecord: item.referenceExampleRecord,
  };
}
