import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import VerificationTrailTimeline from "./VerificationTrailTimeline";
import type { VerificationTrailEntry } from "../hooks/useGenerate";

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

  it("renders expandable snapshots and keeps a terminal failed verdict honest", () => {
    const initial: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "initial",
      question_id: "q-431",
      timestamp: "2026-08-24T00:00:00Z",
      snapshot: { id: "q-431", 題目: ["before"] },
    };
    const failed: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "verification",
      question_id: "q-431",
      passed: false,
      details: "The answer still needs correction.",
      my_answer: "B",
      provided_answer: "A",
      answer_match: false,
      chart_verification: null,
      model: "verify-model",
      timestamp: "2026-08-24T00:00:01Z",
    };
    const correction: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "correction",
      question_id: "q-431",
      retry_index: 1,
      model: "correct-model",
      timestamp: "2026-08-24T00:00:02Z",
      snapshot: { id: "q-431", 題目: ["after"] },
    };
    const terminalFailure: VerificationTrailEntry = {
      ...failed,
      timestamp: "2026-08-24T00:00:03Z",
      details: "The retries were exhausted.",
    };

    render(
      <VerificationTrailTimeline
        entries={[initial, failed, correction, terminalFailure]}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show Agent autonomous verification and correction history",
      }),
    );

    expect(screen.getByText("Initial version")).toBeInTheDocument();
    expect(screen.getByText("Correction")).toBeInTheDocument();
    expect(screen.getByText("correct-model")).toBeInTheDocument();
    expect(screen.getByText("Retry index")).toBeInTheDocument();
    expect(screen.getByText("2026-08-24T00:00:02Z")).toBeInTheDocument();
    expect(screen.getByText("The retries were exhausted.")).toBeInTheDocument();

    const snapshotButtons = screen.getAllByRole("button", { name: "Show snapshot" });
    expect(snapshotButtons).toHaveLength(2);
    fireEvent.click(snapshotButtons[0]);
    fireEvent.click(snapshotButtons[1]);

    expect(screen.getByText(/"before"/)).toBeInTheDocument();
    expect(screen.getByText(/"after"/)).toBeInTheDocument();

    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveAttribute("data-trail-kind", "initial");
    expect(items[2]).toHaveAttribute("data-trail-kind", "correction");
    expect(items[3]).toHaveAttribute("data-verdict", "failed");
    expect(items[3]).toHaveClass("bg-red-50");
  });
});
