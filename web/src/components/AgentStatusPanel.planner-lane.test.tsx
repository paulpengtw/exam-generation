/**
 * Issue #701: planner/batch_briefs stage events must display human labels, not raw i18n keys.
 *
 * useT returns the raw key string (e.g. "stage.batch_briefs") when a message is missing,
 * which is truthy — so `t("stage.batch_briefs") || stage` shows "stage.batch_briefs"
 * instead of the intended human label.  Fix: add the keys to messages.ts.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import AgentStatusPanel from "./AgentStatusPanel";
import type { AgentLane } from "../hooks/useGenerate";

const PLANNER_LANE: AgentLane = {
  agent: "planner",
  status: "running",
  currentStage: "batch_briefs",
  streamingThinking: "",
  streamingContent: "",
  stageHistory: [{ stage: "batch_briefs", startedAt: 1 }],
};

describe("AgentStatusPanel — planner lane (#701)", () => {
  it("shows no raw i18n keys for the planner agent and batch_briefs stage", () => {
    const { container } = render(
      <AgentStatusPanel lanes={[PLANNER_LANE]} requestedTotal={1} />,
    );
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/agent\./);
    expect(text).not.toMatch(/stage\./);
  });

  it("shows a human-readable label for the planner agent", () => {
    render(<AgentStatusPanel lanes={[PLANNER_LANE]} requestedTotal={1} />);
    // The label must not be the raw key "agent.planner"
    expect(screen.queryByText("agent.planner")).not.toBeInTheDocument();
    // It must show the human label defined in messages.ts
    expect(screen.getByText("規劃器")).toBeInTheDocument();
  });

  it("shows a human-readable stage label for batch_briefs", () => {
    render(<AgentStatusPanel lanes={[PLANNER_LANE]} requestedTotal={1} />);
    // The stage label must not be the raw key "stage.batch_briefs"
    expect(screen.queryByText("stage.batch_briefs")).not.toBeInTheDocument();
    // It must show the human label defined in messages.ts
    expect(screen.getByText("規劃題組取材方向")).toBeInTheDocument();
  });
});
