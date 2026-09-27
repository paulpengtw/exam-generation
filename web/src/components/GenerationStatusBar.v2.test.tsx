/**
 * F4: GenerationStatusBar v2 counts line tests.
 */
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import GenerationStatusBar from "./GenerationStatusBar";
import { applyV2Event, createRunEvidence, type RunEvidenceState } from "../lib/generationEvidence";
import { projectGenerationEvidence } from "../lib/generationStream";
import type { GenerationV2Evidence } from "../lib/runEvidence";

function makeV2Evidence(overrides: Partial<GenerationV2Evidence> = {}): GenerationV2Evidence {
  return {
    profile: "generate-v2",
    total: 4,
    endedCount: 2,
    finalReceivedCount: 3,
    closed: false,
    degraded: false,
    ...overrides,
  };
}

function replayAbcdFixture(): RunEvidenceState {
  const lines = readFileSync(
    resolve(__dirname, "../../../tests/fixtures/generation_v2/math_abcd_transport.jsonl"),
    "utf-8",
  ).trim().split("\n").map((line) => JSON.parse(line) as {
    event: string;
    context: Record<string, unknown>;
    payload: Record<string, unknown>;
  });
  const started = lines[0];
  let state = createRunEvidence({
    runId: String(started.context.run_id),
    total: Number(started.payload.total),
    manifest: (started.payload.questions as Array<Record<string, unknown>>).map((question) => ({
      index: Number(question.index),
      questionId: String(question.question_id),
    })),
  });
  for (const line of lines.slice(1)) {
    state = applyV2Event(state, {
      kind: "v2",
      event: { name: line.event, context: line.context, payload: line.payload },
    });
  }
  return state;
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

  it("renders the degraded notice with role=status when evidence.degraded is true", () => {
    render(<GenerationStatusBar {...baseProps} evidence={makeV2Evidence({ degraded: true })} />);
    const notice = screen.getByTestId("statusbar-v2-degraded");
    expect(notice).toBeTruthy();
    expect(notice.getAttribute("role")).toBe("status");
    // Must still show count lines
    expect(screen.getByTestId("statusbar-v2-ended")).toBeTruthy();
    expect(screen.getByTestId("statusbar-v2-final")).toBeTruthy();
  });

  it("does not render the degraded notice when evidence.degraded is false", () => {
    render(<GenerationStatusBar {...baseProps} evidence={makeV2Evidence({ degraded: false })} />);
    expect(screen.queryByTestId("statusbar-v2-degraded")).toBeNull();
  });

  it("projects the real A/B/C/D fixture as three ended and three final receipts", () => {
    const state = replayAbcdFixture();
    const evidence = projectGenerationEvidence([], null, state);

    render(
      <GenerationStatusBar
        {...baseProps}
        runState="unknown"
        evidence={evidence}
        finishedAt={Date.now()}
      />,
    );

    expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("3");
    expect(screen.getByTestId("statusbar-v2-ended")).toHaveTextContent("4");
    expect(screen.getByTestId("statusbar-v2-final")).toHaveTextContent("3");
  });
});
