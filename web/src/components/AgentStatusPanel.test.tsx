import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import AgentStatusPanel from "./AgentStatusPanel";
import type { AgentLane } from "../hooks/useGenerate";

const ACTIVE_LANE: AgentLane = {
  agent: "generator",
  status: "running",
  currentStage: "llm_generate",
  streamingThinking: "",
  streamingContent: "",
  stageHistory: [{ stage: "llm_generate", startedAt: 5 }],
};

describe("AgentStatusPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("preserves the current lane presentation for a single-question run", () => {
    const { container } = render(
      <AgentStatusPanel lanes={[ACTIVE_LANE]} requestedTotal={1} />,
    );

    expect(container.querySelector(".feedback-spinner")).toBeInTheDocument();
    expect(screen.getByText("生成題目中")).toBeInTheDocument();
    expect(screen.getByText("5.0s")).toBeInTheDocument();
    expect(
      screen.queryByTestId("agent-panel-aggregate-label"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("agent-aggregate-counts"),
    ).not.toBeInTheDocument();
  });

  it("shows the aggregate label only for a multi-question run", () => {
    const { rerender } = render(
      <AgentStatusPanel lanes={[ACTIVE_LANE]} requestedTotal={3} />,
    );

    expect(
      screen.getByTestId("agent-panel-aggregate-label"),
    ).toHaveTextContent("合計模式 · 3 題彙總");

    rerender(<AgentStatusPanel lanes={[ACTIVE_LANE]} requestedTotal={1} />);

    expect(
      screen.queryByTestId("agent-panel-aggregate-label"),
    ).not.toBeInTheDocument();
  });

  it("shows aggregate run counts without a per-run stage or timer", () => {
    const aggregateLane: AgentLane = {
      ...ACTIVE_LANE,
      stageHistory: [
        { stage: "llm_generate", startedAt: 1 },
        { stage: "llm_generate", startedAt: 2 },
        { stage: "llm_generate", startedAt: 3, endedAt: 4 },
        { stage: "llm_generate", startedAt: 5, endedAt: 6 },
        { stage: "llm_generate", startedAt: 7, endedAt: 8 },
      ],
    };

    render(<AgentStatusPanel lanes={[aggregateLane]} requestedTotal={3} />);

    const aggregateCounts = screen.getByTestId("agent-aggregate-counts");
    expect(aggregateCounts).toHaveTextContent(
      "2 執行中 · 3 已完成",
    );
    expect(aggregateCounts.parentElement).not.toHaveTextContent("生成題目中");
    expect(screen.queryByText(/^\d+\.\ds$/)).not.toBeInTheDocument();
  });

  it("keeps the aggregate status running while any run is active", () => {
    const staleDoneLane: AgentLane = {
      ...ACTIVE_LANE,
      status: "done",
      currentStage: null,
    };

    const { container } = render(
      <AgentStatusPanel lanes={[staleDoneLane]} requestedTotal={3} />,
    );

    expect(container.querySelector(".feedback-spinner")).toBeInTheDocument();
    const card = screen.getByText("文本生成器").closest(".rounded-lg");
    expect(card).toHaveClass("border-blue-300", "bg-blue-50");
    expect(card).not.toHaveClass("border-green-200", "bg-green-50");
  });
});
