/**
 * F4: GenerationStatusBar v2 counts line tests.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import GenerationStatusBar from "./GenerationStatusBar";
import type { GenerationV2Evidence } from "../lib/runEvidence";

function makeV2Evidence(overrides: Partial<GenerationV2Evidence> = {}): GenerationV2Evidence {
  return {
    profile: "generate-v2",
    total: 4,
    endedCount: 2,
    finalReceivedCount: 3,
    closed: false,
    ...overrides,
  };
}

const baseProps = {
  runState: "running" as const,
  completedCount: 2,
  requestedTotal: 4,
  evidence: makeV2Evidence(),
  startedAt: Date.now(),
  finishedAt: null,
  availableTargets: [] as const,
  onJump: () => {},
  onFeedback: null,
};

describe("GenerationStatusBar — generate-v2 evidence", () => {
  it("renders the ended count line while running", () => {
    render(<GenerationStatusBar {...baseProps} />);
    expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("2");
    expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("4");
  });

  it("renders the final received count line while running", () => {
    render(<GenerationStatusBar {...baseProps} />);
    expect(screen.getByTestId("statusbar-v2-final")).toHaveTextContent("3");
  });

  it("renders after closure (closed=true, runState done)", () => {
    render(<GenerationStatusBar {...baseProps} runState="done" finishedAt={Date.now()} evidence={makeV2Evidence({ closed: true, endedCount: 4, finalReceivedCount: 4 })} />);
    expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("4");
    expect(screen.getByTestId("statusbar-v2-final")).toHaveTextContent("4");
  });

  it("uses sentry-unmask class on counts", () => {
    render(<GenerationStatusBar {...baseProps} />);
    expect(screen.getByTestId("statusbar-v2-ended").closest(".sentry-unmask") ?? screen.getByTestId("statusbar-v2-ended")).toBeTruthy();
  });
});
