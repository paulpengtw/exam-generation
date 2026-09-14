import type { LlmCallEvent } from "../hooks/useGenerate";
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
