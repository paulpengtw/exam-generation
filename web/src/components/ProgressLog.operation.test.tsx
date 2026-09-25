import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ProgressLog from "./ProgressLog";
import type { LlmCallEvent } from "../hooks/useGenerate";

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
