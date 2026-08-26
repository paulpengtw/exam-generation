import { describe, expect, it } from "vitest";
import { filterEntriesByAdmittedParent } from "./admittedBy";

describe("filterEntriesByAdmittedParent", () => {
  it("filters by a parent key and accepts any resolved parent value", () => {
    const entries = [
      { value: "Personal child", admitted_by: { "情境": ["Personal"] } },
      { value: "Shared child", admitted_by: { "情境": ["Global", "Personal"] } },
      { value: "Other relation", admitted_by: { "科目": ["自然科學"] } },
    ];

    expect(filterEntriesByAdmittedParent(entries, "情境", "Global").map((entry) => entry.value))
      .toEqual(["Shared child"]);
    expect(filterEntriesByAdmittedParent(entries, "情境", ["Personal", "Global"]).map((entry) => entry.value))
      .toEqual(["Personal child", "Shared child"]);
  });
});
