import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import ReferenceExampleRecordSection from "./ReferenceExampleRecordSection";

describe("ReferenceExampleRecordSection", () => {
  it.each([null, undefined, []])(
    "does not render anything when entries is %s",
    (entries) => {
      render(<ReferenceExampleRecordSection entries={entries as never} />);
      expect(
        screen.queryByRole("region", { name: "Reference examples" }),
      ).not.toBeInTheDocument();
    },
  );

  it("renders a region with the entry description for an example kind", () => {
    const entry = {
      code: "reference_example" as const,
      kind: "example" as const,
      question_id: "q1",
      stage: "generator",
      slot: null,
      description: "My test description",
      source: "/some/path",
      timestamp: "2026-09-10T00:00:00Z",
    };
    render(<ReferenceExampleRecordSection entries={[entry]} />);
    expect(
      screen.getByRole("region", { name: "Reference examples" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/My test description/)).toBeInTheDocument();
  });

  it("renders cognitive_process for a process_exemplar kind", () => {
    const entry = {
      code: "reference_example" as const,
      kind: "process_exemplar" as const,
      question_id: "q2",
      stage: "subquestion_generator",
      slot: 1,
      cognitive_process: "理解",
      source: "/another/path",
      timestamp: "2026-09-10T01:00:00Z",
    };
    render(<ReferenceExampleRecordSection entries={[entry]} />);
    expect(
      screen.getByRole("region", { name: "Reference examples" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/理解/)).toBeInTheDocument();
  });

  it("renders the slot number when entry has a slot", () => {
    const entry = {
      code: "reference_example" as const,
      kind: "example" as const,
      question_id: "q3",
      stage: "subquestion_generator",
      slot: 3,
      description: "slotted example",
      source: "/path",
      timestamp: "2026-09-10T02:00:00Z",
    };
    render(<ReferenceExampleRecordSection entries={[entry]} />);
    expect(screen.getByText(/#3/)).toBeInTheDocument();
  });
});
