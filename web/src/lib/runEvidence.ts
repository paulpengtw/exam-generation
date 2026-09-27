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
  /** True once the seq buffer degraded (issue #748). */
  degraded: boolean;
  /**
   * Number of questions with any conflict flag (terminalConflict, contentConflict,
   * or reviewConflict).  Issue #749.
   */
  conflictCount: number;
  /**
   * True when an unattributable seq conflict stops whole-batch live updates.
   * Individual already-confirmed terminals are NOT erased.  Issue #749.
   */
  batchConflict: boolean;
  /**
   * True when a raw legacy event was received in v2 mode.
   * The decoder stays in v2 mode; content may be incomplete.  Issue #749.
   */
  legacyMixed: boolean;
};

export type RunEvidence = GenerationLegacyEvidence | ModificationEvidence | GenerationV2Evidence;
