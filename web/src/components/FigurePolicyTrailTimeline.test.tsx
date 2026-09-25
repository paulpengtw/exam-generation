import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import FigurePolicyTrailTimeline from "./FigurePolicyTrailTimeline";
import type { FigurePolicyTrailEntry } from "../hooks/useGenerate";

describe("FigurePolicyTrailTimeline", () => {
  it.each([null, []])("does not render a policy section for %s", (entries) => {
    render(<FigurePolicyTrailTimeline entries={entries} />);

    expect(
      screen.queryByRole("region", { name: "Figure-kind policy history" }),
    ).not.toBeInTheDocument();
  });

  it("shows the content version for persisted policy evidence", () => {
    const entry: FigurePolicyTrailEntry = {
      code: "figure_policy",
      kind: "spec",
      question_id: "q-1",
      label: "題幹",
      effective_figure_kind: "line_chart",
      timestamp: "2026-08-24T00:00:00Z",
      content_revision: 3,
    };
    render(<FigurePolicyTrailTimeline entries={[entry]} />);
    expect(screen.getByText(/Content version/)).toHaveTextContent("3");
  });
});
