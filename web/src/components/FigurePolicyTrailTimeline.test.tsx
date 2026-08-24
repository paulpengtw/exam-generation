import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import FigurePolicyTrailTimeline from "./FigurePolicyTrailTimeline";

describe("FigurePolicyTrailTimeline", () => {
  it.each([null, []])("does not render a policy section for %s", (entries) => {
    render(<FigurePolicyTrailTimeline entries={entries} />);

    expect(
      screen.queryByRole("region", { name: "Figure-kind policy history" }),
    ).not.toBeInTheDocument();
  });
});
