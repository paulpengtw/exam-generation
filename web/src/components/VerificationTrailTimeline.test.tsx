import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const language = vi.hoisted(() => ({ value: "en-US" }));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: language.value }),
}));

import VerificationTrailTimeline from "./VerificationTrailTimeline";
import type { VerificationTrailEntry } from "../hooks/useGenerate";

afterEach(() => {
  language.value = "en-US";
});

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
      content_revision: 2,
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
    expect(screen.getAllByText("Content version")).toHaveLength(2);
    expect(screen.getAllByText("2")).toHaveLength(2);

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

  it("shows only changed fields in a correction by default", () => {
    const initial: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "initial",
      question_id: "q-432",
      timestamp: "2026-08-24T00:00:00Z",
      snapshot: { id: "q-432", 答案: "B", 題目: ["unchanged question"] },
    };
    const correction: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "correction",
      question_id: "q-432",
      retry_index: 1,
      model: "correct-model",
      timestamp: "2026-08-24T00:00:02Z",
      outcome: "accepted",
      snapshot: { id: "q-432", 答案: "A", 題目: ["unchanged question"] },
    };

    render(<VerificationTrailTimeline entries={[initial, correction]} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show Agent autonomous verification and correction history",
      }),
    );

    expect(screen.getByText("Changed fields")).toBeInTheDocument();
    expect(screen.getByText("答案", { selector: "dt" })).toBeInTheDocument();
    expect(screen.getByText("B → A")).toBeInTheDocument();
    expect(screen.queryByText("題目", { selector: "dt" })).not.toBeInTheDocument();

    const snapshotButtons = screen.getAllByRole("button", { name: "Show snapshot" });
    expect(snapshotButtons).toHaveLength(2);
    fireEvent.click(snapshotButtons[1]);

    expect(screen.getByText(/"答案": "A"/)).toBeInTheDocument();
  });

  it("switches a correction from the changed-fields diff to labeled full snapshots", () => {
    const initial: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "initial",
      question_id: "q-427",
      timestamp: "2026-08-24T00:00:00Z",
      snapshot: {
        id: "q-427",
        題目: "before full question",
        答案: "B",
      },
    };
    const correction: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "correction",
      question_id: "q-427",
      retry_index: 1,
      model: "correct-model",
      timestamp: "2026-08-24T00:00:02Z",
      snapshot: {
        id: "q-427",
        題目: "after full question",
        答案: "A",
      },
    };

    render(<VerificationTrailTimeline entries={[initial, correction]} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show Agent autonomous verification and correction history",
      }),
    );

    const sideBySideButton = screen.getByRole("button", {
      name: "Show before and after snapshots",
    });
    expect(sideBySideButton).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(sideBySideButton);

    expect(
      screen.getByRole("button", { name: "Hide before and after snapshots" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Changed fields")).not.toBeInTheDocument();
    expect(screen.getByText("Before correction")).toBeInTheDocument();
    expect(screen.getByText("After correction")).toBeInTheDocument();
    expect(screen.getByText(/"題目": "before full question"/)).toBeInTheDocument();
    expect(screen.getByText(/"答案": "B"/)).toBeInTheDocument();
    expect(screen.getByText(/"題目": "after full question"/)).toBeInTheDocument();
    expect(screen.getByText(/"答案": "A"/)).toBeInTheDocument();
  });

  it("keeps the first correction in diff view when the second correction is toggled", () => {
    const initial: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "initial",
      question_id: "q-427-two-corrections",
      timestamp: "2026-08-24T00:00:00Z",
      snapshot: { id: "q-427-two-corrections", 答案: "B" },
    };
    const firstCorrection: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "correction",
      question_id: "q-427-two-corrections",
      retry_index: 1,
      model: "correct-model-1",
      timestamp: "2026-08-24T00:00:01Z",
      snapshot: { id: "q-427-two-corrections", 答案: "A" },
    };
    const secondCorrection: VerificationTrailEntry = {
      ...firstCorrection,
      retry_index: 2,
      model: "correct-model-2",
      timestamp: "2026-08-24T00:00:02Z",
      snapshot: { id: "q-427-two-corrections", 答案: "C" },
    };

    render(
      <VerificationTrailTimeline
        entries={[initial, firstCorrection, secondCorrection]}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show Agent autonomous verification and correction history",
      }),
    );

    const sideBySideButtons = screen.getAllByRole("button", {
      name: "Show before and after snapshots",
    });
    expect(sideBySideButtons).toHaveLength(2);

    fireEvent.click(sideBySideButtons[1]);

    expect(
      screen.getAllByRole("button", { name: "Show before and after snapshots" }),
    ).toHaveLength(1);
    expect(
      screen.getAllByRole("button", { name: "Hide before and after snapshots" }),
    ).toHaveLength(1);
    expect(screen.getByText("B → A")).toBeInTheDocument();
    expect(screen.queryByText("A → C")).not.toBeInTheDocument();
  });

  it("returns a correction to its changed-fields diff when toggled back", () => {
    const initial: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "initial",
      question_id: "q-427-toggle-back",
      timestamp: "2026-08-24T00:00:00Z",
      snapshot: { id: "q-427-toggle-back", 答案: "B" },
    };
    const correction: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "correction",
      question_id: "q-427-toggle-back",
      retry_index: 1,
      model: "correct-model",
      timestamp: "2026-08-24T00:00:02Z",
      snapshot: { id: "q-427-toggle-back", 答案: "A" },
    };

    render(<VerificationTrailTimeline entries={[initial, correction]} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show Agent autonomous verification and correction history",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Show before and after snapshots" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Hide before and after snapshots" }),
    );

    expect(
      screen.getByRole("button", { name: "Show before and after snapshots" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Changed fields")).toBeInTheDocument();
    expect(screen.getByText("B → A")).toBeInTheDocument();
    expect(screen.queryByText("Before correction")).not.toBeInTheDocument();
    expect(screen.queryByText("After correction")).not.toBeInTheDocument();
  });

  it("does not offer the side-by-side toggle for an initial entry", () => {
    const initial: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "initial",
      question_id: "q-427-initial",
      timestamp: "2026-08-24T00:00:00Z",
      snapshot: { id: "q-427-initial", 題目: "initial question" },
    };

    render(<VerificationTrailTimeline entries={[initial]} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show Agent autonomous verification and correction history",
      }),
    );

    expect(
      screen.queryByRole("button", { name: "Show before and after snapshots" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Hide before and after snapshots" }),
    ).not.toBeInTheDocument();
  });

  it("shows an explicit no-changes state for an identical correction snapshot", () => {
    const snapshot = { id: "q-432-noop", 答案: "B", 題目: ["unchanged question"] };
    const initial: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "initial",
      question_id: "q-432-noop",
      timestamp: "2026-08-24T00:00:00Z",
      snapshot,
    };
    const correction: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "correction",
      question_id: "q-432-noop",
      retry_index: 1,
      model: "correct-model",
      timestamp: "2026-08-24T00:00:02Z",
      snapshot: { id: "q-432-noop", 答案: "B", 題目: ["unchanged question"] },
    };

    render(<VerificationTrailTimeline entries={[initial, correction]} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show Agent autonomous verification and correction history",
      }),
    );

    expect(
      screen.getByText("No fields changed in this correction."),
    ).toBeInTheDocument();
  });

  it("renders a rejected correction as a retained snapshot without an applied diff", () => {
    const retainedSnapshot = {
      id: "q-433-rejected",
      答案: "B",
      題目: ["retained question"],
    };
    const initial: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "initial",
      question_id: "q-433-rejected",
      timestamp: "2026-08-24T00:00:00Z",
      snapshot: retainedSnapshot,
    };
    const rejected: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "correction",
      question_id: "q-433-rejected",
      retry_index: 1,
      model: "correct-model",
      timestamp: "2026-08-24T00:00:02Z",
      outcome: "rejected",
      reason: {
        code: "subquestion_structure_mismatch",
        path: "subquestions",
        message: "The correction omitted an original sub-question.",
      },
      snapshot: retainedSnapshot,
    };

    render(<VerificationTrailTimeline entries={[initial, rejected]} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Show Agent autonomous verification and correction history",
      }),
    );

    expect(screen.getByText("Correction rejected")).toBeInTheDocument();
    expect(screen.getByText("The correction omitted an original sub-question.")).toBeInTheDocument();
    expect(screen.queryByText("subquestion_structure_mismatch")).not.toBeInTheDocument();
    expect(screen.queryByText("subquestions", { selector: "dt" })).not.toBeInTheDocument();
    expect(screen.queryByText("Changed fields")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Show before and after snapshots" }),
    ).not.toBeInTheDocument();

    const snapshotButtons = screen.getAllByRole("button", { name: "Show snapshot" });
    fireEvent.click(snapshotButtons[1]);
    expect(screen.getByText(/"retained question"/)).toBeInTheDocument();
  });

  it("localizes a rejected correction label for Traditional Chinese", () => {
    language.value = "zh-TW";
    const rejected: VerificationTrailEntry = {
      code: "verification_trail",
      kind: "correction",
      question_id: "q-433-zh",
      retry_index: 1,
      model: "correct-model",
      timestamp: "2026-08-24T00:00:02Z",
      outcome: "rejected",
      snapshot: { id: "q-433-zh", 題目: ["保留題目"] },
    };

    render(<VerificationTrailTimeline entries={[rejected]} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "展開 Agent 自主驗證修正歷程",
      }),
    );

    expect(screen.getByText("修正未採用")).toBeInTheDocument();
    expect(screen.getByText("保留的題目快照")).toBeInTheDocument();
  });
});
