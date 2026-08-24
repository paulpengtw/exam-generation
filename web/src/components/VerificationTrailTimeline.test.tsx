import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import VerificationTrailTimeline from "./VerificationTrailTimeline";

describe("VerificationTrailTimeline", () => {
  it("renders a no-trail state for a persisted null trail", () => {
    render(
      <VerificationTrailTimeline
        entries={null as unknown as []}
      />,
    );

    expect(
      screen.getByText("No Agent autonomous verification and correction history was recorded."),
    ).toBeInTheDocument();
  });
});
