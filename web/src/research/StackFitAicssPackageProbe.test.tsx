import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalCard } from "@aicss/react/approval-card";
import { Orb } from "@aicss/react/orbs";
import { StreamingText } from "@aicss/react/streaming-text";
import { TextResponse } from "@aicss/react/text-response";
import { ThinkingReasoning } from "@aicss/react/thinking-reasoning";
import { ThinkingState } from "@aicss/react/thinking-state";
import { TodoList } from "@aicss/react/task-list";

function StackFitAicssPackageProbe() {
  return (
    <>
      <div data-testid="aicss-thinking-state"><ThinkingState /></div>
      <div data-testid="aicss-thinking-reasoning"><ThinkingReasoning /></div>
      <div data-testid="aicss-orb"><Orb label="Orb probe" pill /></div>
      <div data-testid="aicss-streaming-text"><StreamingText text="stream" /></div>
      <div data-testid="aicss-todo-list"><TodoList /></div>
      <div data-testid="aicss-approval-card">
        <ApprovalCard variant="command" command="echo probe" />
      </div>
      <div data-testid="aicss-text-response"><TextResponse>response</TextResponse></div>
    </>
  );
}

describe("@aicss/react Vite probe", () => {
  beforeEach(() => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders every requested component without Next.js transpilePackages", () => {
    render(<StackFitAicssPackageProbe />);

    for (const id of [
      "aicss-thinking-state",
      "aicss-thinking-reasoning",
      "aicss-orb",
      "aicss-streaming-text",
      "aicss-todo-list",
      "aicss-approval-card",
      "aicss-text-response",
    ]) {
      expect(screen.getByTestId(id)).toBeInTheDocument();
    }
  });
});
