/**
 * Issue #700: renderer/acquire stage events must display human labels, not raw i18n keys.
 *
 * useT returns the raw key string (e.g. "agent.renderer") when a message is missing,
 * which is truthy — so `t("agent.renderer") || baseAgent` shows "agent.renderer"
 * instead of the intended fallback "renderer".  Fix: add the keys to messages.ts.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import AgentStatusPanel from "./AgentStatusPanel";
import type { AgentLane } from "../hooks/useGenerate";

const RENDERER_LANE: AgentLane = {
  agent: "renderer",
  status: "running",
  currentStage: "acquire",
  streamingThinking: "",
  streamingContent: "",
  stageHistory: [{ stage: "acquire", startedAt: 1 }],
};

describe("AgentStatusPanel — renderer lane (#700)", () => {
  it("shows no raw i18n keys for the renderer agent and acquire stage", () => {
    const { container } = render(
      <AgentStatusPanel lanes={[RENDERER_LANE]} requestedTotal={1} />,
    );
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/agent\./);
    expect(text).not.toMatch(/stage\./);
  });

  it("shows a human-readable label for the renderer agent", () => {
    render(<AgentStatusPanel lanes={[RENDERER_LANE]} requestedTotal={1} />);
    // The label must not be the raw key "agent.renderer"
    expect(screen.queryByText("agent.renderer")).not.toBeInTheDocument();
    // It must show the human label defined in messages.ts
    expect(screen.getByText("渲染器")).toBeInTheDocument();
  });

  it("shows a human-readable stage label for acquire", () => {
    render(<AgentStatusPanel lanes={[RENDERER_LANE]} requestedTotal={1} />);
    // The stage label must not be the raw key "stage.acquire"
    expect(screen.queryByText("stage.acquire")).not.toBeInTheDocument();
    // It must show the human label defined in messages.ts
    expect(screen.getByText("等待渲染器")).toBeInTheDocument();
  });
});
