import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import AgentStatusPanel from "./AgentStatusPanel";
import type { AgentLane } from "../hooks/useGenerate";

const ERROR_LANE: AgentLane = {
  agent: "image_agent",
  status: "error",
  currentStage: null,
  streamingThinking: "",
  streamingContent: "",
  stageHistory: [{ stage: "render_image", startedAt: 5, endedAt: 6 }],
  errorMessage: "IMAGE_API_KEY is required for GPT image generation.",
};

describe("AgentStatusPanel — error stage", () => {
  it("shows the complete error message verbatim", () => {
    render(<AgentStatusPanel lanes={[ERROR_LANE]} requestedTotal={1} />);
    const error = screen.getByTestId("stage-error-message");
    expect(error).toHaveTextContent(
      "IMAGE_API_KEY is required for GPT image generation."
    );
    expect(error.querySelector("pre")).not.toHaveClass("sentry-unmask");
  });

  it("shows zh-TW report-to-developer copy", () => {
    render(<AgentStatusPanel lanes={[ERROR_LANE]} requestedTotal={1} />);
    expect(screen.getByTestId("stage-error-message")).toHaveTextContent(
      "請將下方的完整錯誤訊息回報給開發者"
    );
  });

  it("renders with error border and red background", () => {
    const { container } = render(
      <AgentStatusPanel lanes={[ERROR_LANE]} requestedTotal={1} />
    );
    const card = container.querySelector(".rounded-lg");
    expect(card).toHaveClass("border-red-300");
    expect(card).toHaveClass("bg-red-50");
  });
});
