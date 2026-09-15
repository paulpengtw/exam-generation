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

/** Evidence profile for the generation stream v2 protocol (issue #742). */
export type GenerationV2Evidence = {
  profile: "generate-v2";
  total: number;
  endedCount: number;
  finalReceivedCount: number;
  closed: boolean;
};

export type RunEvidence = GenerationLegacyEvidence | ModificationEvidence | GenerationV2Evidence;
