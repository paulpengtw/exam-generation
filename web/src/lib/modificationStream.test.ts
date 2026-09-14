import { describe, expect, it } from "vitest";
import type { ModificationStageEvent } from "../hooks/useModificationRun";
import { projectModificationEvidence } from "./modificationStream";

describe("projectModificationEvidence", () => {
  it("tags the same modification steps without generation identity or manifest fields", () => {
    const steps: readonly ModificationStageEvent[] = [
      { type: "stage", agent: "modifier", stage: "modification", step: "modify", status: "start", ts: 1 },
      { type: "stage", agent: "modifier", stage: "modification", step: "modify", status: "end", ts: 2 },
    ];

    const evidence = projectModificationEvidence(steps);

    expect(evidence).toEqual({ profile: "modification", steps });
    expect(evidence.steps).toBe(steps);
    expect(Object.keys(evidence)).toEqual(["profile", "steps"]);
  });
});
