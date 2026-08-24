import { describe, expect, it } from "vitest";
import { findSocialStudiesPinRuleViolations } from "./socialStudiesPinRules";

describe("findSocialStudiesPinRuleViolations", () => {
  it("treats an unknown cognitive-process value as an unpinned slot", () => {
    expect(findSocialStudiesPinRuleViolations([
      { cognitive_process: "future-bucket" },
      { cognitive_process: "Knowing–Defining and Describing" },
    ], "跨科")).toEqual([]);
  });
});
