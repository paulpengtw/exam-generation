export const KNOWING_DEFINING_PROCESS = "Knowing–Defining and Describing";
export const RELATE_OR_INTEGRATE_PROCESS = "Reasoning and Applying–Relate or Integrate";

const COGNITIVE_PROCESS_VALUES = new Set([
  KNOWING_DEFINING_PROCESS,
  "Knowing–Illustrating with examples",
  "Reasoning and Applying–Interpret information",
  RELATE_OR_INTEGRATE_PROCESS,
]);

export type SocialStudiesPinRuleViolation =
  | "knowing_defining_limit"
  | "cross_subject_relate";

export function findSocialStudiesPinRuleViolations(
  pinnedAssignments: Array<{ cognitive_process?: string } | string | null | undefined>,
  subjectFilter: string,
): SocialStudiesPinRuleViolation[] {
  const assignments = pinnedAssignments.map((assignment) => {
    const value = typeof assignment === "string" ? assignment : assignment?.cognitive_process;
    return value !== undefined && COGNITIVE_PROCESS_VALUES.has(value) ? value : undefined;
  });
  const violations: SocialStudiesPinRuleViolation[] = [];

  if (assignments.filter((value) => value === KNOWING_DEFINING_PROCESS).length > 1) {
    violations.push("knowing_defining_limit");
  }

  if (
    subjectFilter === "跨科" &&
    assignments.length > 0 &&
    assignments.every((value) => value !== undefined) &&
    !assignments.includes(RELATE_OR_INTEGRATE_PROCESS)
  ) {
    violations.push("cross_subject_relate");
  }

  return violations;
}
