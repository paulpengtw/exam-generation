import type { StageEvent } from "../hooks/useGenerate";
import type { ModificationStageEvent } from "./modificationStream";

export type EvidenceProfile = "generate-v2" | "generate-legacy" | "generate-legacy-adapter" | "modification";

export type GenerationLegacyEvidence = {
  profile: "generate-legacy";
  stageEvents: readonly StageEvent[];
  subQuestionCount: number | null;
};

/**
 * Evidence profile for the C1×S0 legacy stream adapter (issue #750).
 * The new client received an old-server stream and is storing items via
 * the legacyAdapter state machine; server-confirmed manifest totals are
 * absent and per-question progress is unavailable.
 */
export type GenerationLegacyAdapterEvidence = {
  profile: "generate-legacy-adapter";
  /** From the generate request params.count; never a server-confirmed count. */
  requestTotal: number | null;
  /** Number of unique final results received so far. */
  finalCount: number;
  /** True once a "done" event has been received. */
  done: boolean;
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

export type RunEvidence = GenerationLegacyEvidence | GenerationLegacyAdapterEvidence | ModificationEvidence | GenerationV2Evidence;
