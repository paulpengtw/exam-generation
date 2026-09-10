import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import ReferenceExampleRecordSection from "./ReferenceExampleRecordSection";
import type { ReferenceExampleEntryShape } from "./ReferenceExampleRecordSection";

const _entry = (overrides: Partial<ReferenceExampleEntryShape> = {}): ReferenceExampleEntryShape => ({
  code: "reference_example",
  kind: "example",
  question_id: "q1",
  stage: "generator",
  slot: null,
  description: "My test description",
  source: "/some/path",
  timestamp: "2026-09-10T00:00:00Z",
  ...overrides,
});

describe("ReferenceExampleRecordSection", () => {
  it("does not render anything when record is undefined", () => {
    render(<ReferenceExampleRecordSection />);
    expect(
      screen.queryByRole("region", { name: "Reference examples" }),
    ).not.toBeInTheDocument();
  });

  it("renders a no-record message when record is null", () => {
    render(<ReferenceExampleRecordSection record={null} />);
    expect(
      screen.getByRole("region", { name: "Reference examples" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No reference examples were recorded."),
    ).toBeInTheDocument();
  });

  it("renders a no-record message when entries list is empty", () => {
    render(<ReferenceExampleRecordSection record={{ entries: [] }} />);
    expect(
      screen.getByRole("region", { name: "Reference examples" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No reference examples were recorded."),
    ).toBeInTheDocument();
  });

  it("renders a region with the entry description for an example kind", () => {
    render(
      <ReferenceExampleRecordSection
        record={{ entries: [_entry({ description: "My test description" })] }}
      />,
    );
    expect(
      screen.getByRole("region", { name: "Reference examples" }),
    ).toBeInTheDocument();
    // Collapsed by default — click toggle to reveal entries
    fireEvent.click(
      screen.getByRole("button", { name: "Show reference examples used during generation" }),
    );
    expect(screen.getByText(/My test description/)).toBeInTheDocument();
  });

  it("renders cognitive_process for a process_exemplar kind", () => {
    render(
      <ReferenceExampleRecordSection
        record={{
          entries: [
            _entry({
              kind: "process_exemplar",
              question_id: "q2",
              stage: "subquestion_generator",
              slot: 1,
              cognitive_process: "理解",
              source: "/another/path",
              timestamp: "2026-09-10T01:00:00Z",
              description: undefined,
            }),
          ],
        }}
      />,
    );
    expect(
      screen.getByRole("region", { name: "Reference examples" }),
    ).toBeInTheDocument();
    // Collapsed by default — click toggle to reveal entries
    fireEvent.click(
      screen.getByRole("button", { name: "Show reference examples used during generation" }),
    );
    expect(screen.getByText(/理解/)).toBeInTheDocument();
  });

  it("renders the slot number when entry has a slot", () => {
    render(
      <ReferenceExampleRecordSection
        record={{
          entries: [
            _entry({
              stage: "subquestion_generator",
              slot: 3,
              description: "slotted example",
              timestamp: "2026-09-10T02:00:00Z",
            }),
          ],
        }}
      />,
    );
    // Collapsed by default — click toggle to reveal entries
    fireEvent.click(
      screen.getByRole("button", { name: "Show reference examples used during generation" }),
    );
    expect(screen.getByText(/#3/)).toBeInTheDocument();
  });

  it("renders a duplicate badge when the same source appears in two slots", () => {
    const sharedSource = "/shared/path/to/few_shot.json";
    render(
      <ReferenceExampleRecordSection
        record={{
          entries: [
            _entry({
              slot: 1,
              source: sharedSource,
              description: "first use",
              timestamp: "2026-09-10T00:00:00Z",
            }),
            _entry({
              slot: 2,
              source: sharedSource,
              description: "second use",
              timestamp: "2026-09-10T00:01:00Z",
            }),
          ],
        }}
      />,
    );
    // Collapsed by default — click toggle to reveal entries
    fireEvent.click(
      screen.getByRole("button", { name: "Show reference examples used during generation" }),
    );
    // The second entry should show "Same as subquestion #1" badge
    expect(screen.getByText(/Same as subquestion #1/)).toBeInTheDocument();
    // The first entry should NOT have a duplicate badge
    const badges = screen.queryAllByLabelText("duplicate");
    expect(badges).toHaveLength(1);
  });

  it("does not count null-slot (text-stage) entries as a subquestion slot", () => {
    render(
      <ReferenceExampleRecordSection
        record={{
          entries: [
            _entry({ slot: null, stage: "text_generator", description: "text stage example" }),
            _entry({ slot: 1, stage: "subquestion_generator", description: "slot 1 example", timestamp: "2026-09-10T01:00:00Z" }),
            _entry({ slot: 2, stage: "subquestion_generator", description: "slot 2 example", timestamp: "2026-09-10T02:00:00Z" }),
          ],
        }}
      />,
    );
    expect(screen.getByTestId("ref-record-counts")).toHaveTextContent("3 entries, 2 subquestions");
  });
});
