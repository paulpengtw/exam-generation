import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import GenerationStatusBar, {
  type GenerationStatusBarProps,
} from "./GenerationStatusBar";

const BASE_PROPS: GenerationStatusBarProps = {
  runState: "running",
  completedCount: 0,
  requestedTotal: 1,
  subject: "social_studies",
  evidence: { profile: "generate-legacy", stageEvents: [], subQuestionCount: null },
  startedAt: null,
  finishedAt: null,
  availableTargets: [],
  onJump: () => {},
  onFeedback: null,
};

describe("GenerationStatusBar — before/after characterization (#739)", () => {
  it("preserves generation steps with overlapping subquestion workers", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        evidence={{ profile: "generate-legacy", subQuestionCount: 3, stageEvents: [
          { type: "stage", agent: "generator", stage: "llm_generate", status: "start", ts: 1 },
          { type: "stage", agent: "generator", stage: "llm_generate", status: "end", ts: 2 },
          { type: "stage", agent: "sub_generator#1", stage: "llm_generate", status: "start", ts: 3 },
          { type: "stage", agent: "sub_generator#2", stage: "llm_generate", status: "start", ts: 4 },
          { type: "stage", agent: "sub_generator#2", stage: "llm_generate", status: "end", ts: 5 },
        ] }}
      />,
    );

    expect(screen.getByTestId("statusbar-status").textContent).toBe(
      "文本 › 子題 1/3 › 圖片 › 驗證 › 修正",
    );
    expect(screen.getByTestId("generation-step-text")).toHaveAttribute("data-state", "complete");
    expect(screen.getByTestId("generation-step-subquestions")).toHaveAttribute("data-state", "live");
    expect(screen.getByTestId("generation-step-verify")).toHaveAttribute("data-state", "pending");
    expect(screen.getByTestId("statusbar-status").innerHTML).toMatchInlineSnapshot(`"<span data-testid="generation-step-breadcrumb" class="sentry-unmask"><span><span data-testid="generation-step-text" data-state="complete" data-dim="false" class="text-green-600 hidden sm:inline">文本</span></span><span><span class="hidden text-gray-300 sm:inline"> › </span><span data-testid="generation-step-subquestions" data-state="live" data-dim="false" class="font-semibold text-blue-600">子題 1/3</span></span><span><span class="hidden text-gray-300 sm:inline"> › </span><span data-testid="generation-step-image" data-state="pending" data-dim="true" class="text-gray-300 hidden sm:inline">圖片</span></span><span><span class="hidden text-gray-300 sm:inline"> › </span><span data-testid="generation-step-verify" data-state="pending" data-dim="false" class="text-gray-400 hidden sm:inline">驗證</span></span><span><span class="hidden text-gray-300 sm:inline"> › </span><span data-testid="generation-step-correct" data-state="pending" data-dim="true" class="text-gray-300 hidden sm:inline">修正</span></span></span>"`);
  });

  it("preserves the aggregate batch line without a breadcrumb", () => {
    render(<GenerationStatusBar {...BASE_PROPS} requestedTotal={3} completedCount={1} />);

    expect(screen.getByTestId("statusbar-status").textContent).toBe("◐ 生成中 · 已完成 1 / 3");
    expect(screen.queryByTestId("generation-step-breadcrumb")).not.toBeInTheDocument();
    expect(screen.queryByTestId("modification-step-breadcrumb")).not.toBeInTheDocument();
    expect(screen.getByTestId("statusbar-status").innerHTML).toMatchInlineSnapshot(`"<span class="sentry-unmask">◐ 生成中 · 已完成</span> 1 / 3"`);
  });

  it("preserves modification, verification and correction step history", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        evidence={{ profile: "modification", steps: [
          { type: "stage", agent: "modifier", stage: "modification", step: "modify", status: "start", ts: 1 },
          { type: "stage", agent: "modifier", stage: "modification", step: "modify", status: "end", ts: 2 },
          { type: "stage", agent: "verifier", stage: "verify", step: "verify", status: "start", ts: 3 },
          { type: "stage", agent: "verifier", stage: "verify", step: "verify", status: "end", ts: 4 },
          { type: "stage", agent: "corrector", stage: "correct", step: "correct", status: "start", ts: 5 },
          { type: "stage", agent: "verifier", stage: "verify", step: "verify", status: "start", ts: 6 },
        ] }}
      />,
    );

    expect(screen.getByTestId("statusbar-status").textContent).toBe("修改 › 驗證 › 修正 › 驗證");
    expect(screen.getByTestId("modification-step-0")).toHaveAttribute("data-state", "complete");
    expect(screen.getByTestId("modification-step-1")).toHaveAttribute("data-state", "complete");
    expect(screen.getByTestId("modification-step-2")).toHaveAttribute("data-state", "live");
    expect(screen.getByTestId("modification-step-3")).toHaveAttribute("data-state", "live");
    expect(screen.getByTestId("statusbar-status").innerHTML).toMatchInlineSnapshot(`"<span data-testid="modification-step-breadcrumb" class="sentry-unmask"><span><span data-testid="modification-step-0" data-state="complete" class="text-green-600">修改</span></span><span><span class="hidden text-gray-300 sm:inline"> › </span><span data-testid="modification-step-1" data-state="complete" class="text-green-600">驗證</span></span><span><span class="hidden text-gray-300 sm:inline"> › </span><span data-testid="modification-step-2" data-state="live" class="font-semibold text-blue-600">修正</span></span><span><span class="hidden text-gray-300 sm:inline"> › </span><span data-testid="modification-step-3" data-state="live" class="font-semibold text-blue-600">驗證</span></span></span>"`);
  });
});
