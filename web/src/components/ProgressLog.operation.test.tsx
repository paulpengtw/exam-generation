import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import ProgressLog from "./ProgressLog";
import GenerationStatusBar from "./GenerationStatusBar";
import type { LlmCallEvent } from "../hooks/useGenerate";
import { applyV2Event, createRunEvidence } from "../lib/generationEvidence";

function replayAbcdFixture() {
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

describe("ProgressLog operation/call pairing", () => {
  it("keeps interleaved same-purpose text in separate call blocks", () => {
    const calls: LlmCallEvent[] = [
      {
        type: "request", runId: "RUN", operationId: "O1", callId: "C1",
        purpose: "generate", agent: "sub_generator#1", model: "model", messages: [],
      },
      {
        type: "request", runId: "RUN", operationId: "O2", callId: "C2",
        purpose: "generate", agent: "sub_generator#1", model: "model", messages: [],
      },
      {
        type: "content", runId: "RUN", operationId: "O1", callId: "C1",
        channel: "content", purpose: "generate", agent: "sub_generator#1", text: "old text",
      },
      {
        type: "content", runId: "RUN", operationId: "O2", callId: "C2",
        channel: "content", purpose: "generate", agent: "sub_generator#1", text: "new text",
      },
    ];

    render(<ProgressLog lines={[]} status="generating" llmCalls={calls} />);
    fireEvent.click(screen.getByRole("button"));

    expect(screen.getByText("old text")).toBeInTheDocument();
    expect(screen.getByText("new text")).toBeInTheDocument();
  });
});

describe("ProgressLog v2 evidence projection", () => {
  it("uses the normalized A/B/C/D counts and stops the spinner after close", () => {
    const { container } = render(
      <ProgressLog
        lines={[]}
        status="generating"
        evidence={replayAbcdFixture()}
      />,
    );

    expect(screen.getByTestId("progress-v2-ended")).toHaveTextContent("3");
    expect(screen.getByTestId("progress-v2-ended")).toHaveTextContent("4");
    expect(screen.getByTestId("progress-v2-final")).toHaveTextContent("3");
    expect(container.querySelector(".feedback-spinner")).not.toBeInTheDocument();
  });
});

describe("ProgressLog phase status", () => {
  it("uses the same current phase label as GenerationStatusBar", () => {
    const stageEvents: LlmCallEvent[] = [
      { type: "stage", agent: "generator", stage: "llm_generate", status: "end", ts: 1 },
      { type: "stage", agent: "verifier", stage: "verify", status: "start", ts: 2 },
    ];

    render(
      <>
        <GenerationStatusBar
          runState="running"
          completedCount={0}
          requestedTotal={1}
          subject="math"
          evidence={{ profile: "generate-legacy", stageEvents, subQuestionCount: null }}
          startedAt={1}
          finishedAt={null}
          availableTargets={[]}
          onJump={() => {}}
          onFeedback={null}
        />
        <ProgressLog
          lines={[]}
          status="generating"
          llmCalls={stageEvents}
          subject="math"
          subQuestionCount={null}
          requestedTotal={1}
          completedCount={0}
        />
      </>,
    );

    expect(screen.getByTestId("statusbar-status")).toHaveTextContent("審題中");
    expect(screen.getByTestId("progress-phase-label")).toHaveTextContent("審題中");
    expect(screen.getByTestId("progress-phase-label")).toHaveClass("sentry-unmask");
    expect(screen.getByTestId("progress-phase-label").textContent).toBe(
      screen.getByTestId("generation-step-verify").textContent,
    );
    expect(screen.getByTestId("progress-phase-label").querySelector(".status-shimmer"))
      .not.toBeInTheDocument();
  });
});
