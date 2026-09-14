import type { ModificationStageEvent } from "../hooks/useModificationRun";
import type { ModificationEvidence } from "./runEvidence";

export function projectModificationEvidence(
  steps: readonly ModificationStageEvent[],
): ModificationEvidence {
  return { profile: "modification", steps };
}
