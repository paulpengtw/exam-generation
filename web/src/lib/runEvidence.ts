import type { StageEvent } from "../hooks/useGenerate";
import type { ModificationStageEvent } from "./modificationStream";

export type EvidenceProfile = "generate-v2" | "generate-legacy" | "modification";

export type GenerationLegacyEvidence = {
  profile: "generate-legacy";
  stageEvents: readonly StageEvent[];
  subQuestionCount: number | null;
};

export type ModificationEvidence = {
  profile: "modification";
  steps: readonly ModificationStageEvent[];
};

/** Reserved entry point for OpenSpec per-question-live-progress tasks 5.x/6.x and issue #742. */
export type GenerationV2Evidence = { profile: "generate-v2" };

export type RunEvidence = GenerationLegacyEvidence | ModificationEvidence | GenerationV2Evidence;
