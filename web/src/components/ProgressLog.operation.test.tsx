import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import ProgressLog from "./ProgressLog";
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
    expect(container.querySelector(".animate-spin")).not.toBeInTheDocument();
  });
});
