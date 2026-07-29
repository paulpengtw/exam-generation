import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import GenerationStatusBar, {
  type GenerationStatusBarProps,
} from "./GenerationStatusBar";
import type { LlmCallEvent } from "../hooks/useGenerate";

function stageEvent(
  agent: string,
  stage: string,
  status: "start" | "end",
  ts: number,
): LlmCallEvent {
  return { type: "stage", agent, stage, status, ts };
}

const BASE_PROPS: GenerationStatusBarProps = {
  runState: "idle",
  completedCount: 0,
  requestedTotal: 0,
  subject: "math",
  stageEvents: [],
  subQuestionCount: null,
  startedAt: null,
  finishedAt: null,
  availableTargets: ["form"],
  onJump: vi.fn(),
  onFeedback: null,
};

describe("GenerationStatusBar — 生成步驟", () => {
  it("shows the four-step math skeleton with 生成 live when generation starts", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        requestedTotal={1}
        startedAt={1_000}
        stageEvents={[
          stageEvent("generator", "llm_generate", "start", 1_000),
        ]}
      />,
    );

    const breadcrumb = screen.getByTestId("generation-step-breadcrumb");
    expect(breadcrumb).toHaveTextContent("生成 › 圖片 › 驗證 › 修正");
    expect(screen.getByTestId("generation-step-generate")).toHaveAttribute(
      "data-state",
      "live",
    );
  });

  it.each(["social_studies", "natural_sciences"] as const)(
    "shows the five-step %s skeleton with 文本 live when generation starts",
    (subject) => {
      render(
        <GenerationStatusBar
          {...BASE_PROPS}
          subject={subject}
          runState="running"
          requestedTotal={1}
          startedAt={1_000}
          stageEvents={[
            stageEvent("generator", "llm_generate", "start", 1_000),
          ]}
        />,
      );

      const breadcrumb = screen.getByTestId("generation-step-breadcrumb");
      expect(breadcrumb).toHaveTextContent("文本 › 子題 › 圖片 › 驗證 › 修正");
      expect(screen.getByTestId("generation-step-text")).toHaveAttribute(
        "data-state",
        "live",
      );
    },
  );

  it("completes 生成 and makes 驗證 live when the pipeline moves to verification", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        requestedTotal={1}
        startedAt={1_000}
        stageEvents={[
          stageEvent("generator", "llm_generate", "start", 1_000),
          stageEvent("generator", "llm_generate", "end", 2_000),
          stageEvent("verifier", "verify", "start", 3_000),
        ]}
      />,
    );

    expect(screen.getByTestId("generation-step-generate")).toHaveAttribute(
      "data-state",
      "complete",
    );
    expect(screen.getByTestId("generation-step-verify")).toHaveAttribute(
      "data-state",
      "live",
    );
  });

  it("dims conditional 圖片 and 修正 until their activity arrives", () => {
    const { rerender } = render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        requestedTotal={1}
        startedAt={1_000}
        stageEvents={[
          stageEvent("generator", "llm_generate", "start", 1_000),
        ]}
      />,
    );

    expect(screen.getByTestId("generation-step-image")).toHaveAttribute(
      "data-dim",
      "true",
    );
    expect(screen.getByTestId("generation-step-correct")).toHaveAttribute(
      "data-dim",
      "true",
    );

    rerender(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        requestedTotal={1}
        startedAt={1_000}
        stageEvents={[
          stageEvent("generator", "llm_generate", "start", 1_000),
          stageEvent("generator", "llm_generate", "end", 2_000),
          stageEvent("image_agent", "render_image", "start", 3_000),
        ]}
      />,
    );

    expect(screen.getByTestId("generation-step-image")).toHaveAttribute(
      "data-state",
      "live",
    );
    expect(screen.getByTestId("generation-step-image")).toHaveAttribute(
      "data-dim",
      "false",
    );
  });

  it("keeps 圖片 and 修正 dim when verification is reached without either activity", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        requestedTotal={1}
        startedAt={1_000}
        stageEvents={[
          stageEvent("generator", "llm_generate", "start", 1_000),
          stageEvent("generator", "llm_generate", "end", 2_000),
          stageEvent("verifier", "verify", "start", 3_000),
        ]}
      />,
    );

    expect(screen.getByTestId("generation-step-verify")).toHaveAttribute(
      "data-state",
      "live",
    );
    expect(screen.getByTestId("generation-step-image")).toHaveAttribute(
      "data-dim",
      "true",
    );
    expect(screen.getByTestId("generation-step-correct")).toHaveAttribute(
      "data-dim",
      "true",
    );
  });

  it("shows distinct completed 子題 workers with and without a submitted total", () => {
    const subQuestionEvents = [
      stageEvent("sub_generator#1", "llm_generate", "end", 1_000),
      stageEvent("sub_generator#2", "llm_generate", "end", 2_000),
      stageEvent("sub_generator#3", "llm_generate", "start", 3_000),
    ];
    const { rerender } = render(
      <GenerationStatusBar
        {...BASE_PROPS}
        subject="social_studies"
        runState="running"
        requestedTotal={1}
        subQuestionCount={5}
        startedAt={1_000}
        stageEvents={subQuestionEvents}
      />,
    );

    const subquestions = screen.getByTestId("generation-step-subquestions");
    expect(subquestions).toHaveAttribute("data-state", "live");
    expect(subquestions).toHaveTextContent("子題 2/5");

    rerender(
      <GenerationStatusBar
        {...BASE_PROPS}
        subject="social_studies"
        runState="running"
        requestedTotal={1}
        subQuestionCount={null}
        startedAt={1_000}
        stageEvents={subQuestionEvents}
      />,
    );

    expect(screen.getByTestId("generation-step-subquestions")).toHaveTextContent(
      "子題 2",
    );
    expect(screen.getByTestId("generation-step-subquestions")).not.toHaveTextContent(
      "2/",
    );
  });

  it("keeps the roll-up and omits every breadcrumb element for a multi-question run", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        completedCount={1}
        requestedTotal={2}
        startedAt={1_000}
        stageEvents={[
          stageEvent("generator", "llm_generate", "start", 1_000),
        ]}
      />,
    );

    expect(screen.getByTestId("statusbar-status")).toHaveTextContent(
      "生成中 · 已完成 1 / 2",
    );
    expect(screen.queryAllByTestId(/^generation-step-/)).toHaveLength(0);
  });

  it("hides non-live steps below 640px while keeping the live step visible", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        requestedTotal={1}
        startedAt={1_000}
        stageEvents={[
          stageEvent("generator", "llm_generate", "start", 1_000),
          stageEvent("generator", "llm_generate", "end", 2_000),
          stageEvent("verifier", "verify", "start", 3_000),
        ]}
      />,
    );

    for (const step of ["generate", "image", "correct"]) {
      expect(screen.getByTestId(`generation-step-${step}`)).toHaveClass(
        "hidden",
        "sm:inline",
      );
    }
    expect(screen.getByTestId("generation-step-verify")).not.toHaveClass(
      "hidden",
    );
  });
});

describe("GenerationStatusBar — status half", () => {
  it("unmasks fixed status labels without unmasking dynamic status values", () => {
    const { rerender } = render(<GenerationStatusBar {...BASE_PROPS} />);
    expect(screen.getByText("尚未生成")).toHaveClass("sentry-unmask");

    rerender(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        completedCount={2}
        requestedTotal={5}
        startedAt={1_000}
      />,
    );
    expect(screen.getByTestId("statusbar-status")).not.toHaveClass(
      "sentry-unmask",
    );
    expect(screen.getByText("◐ 生成中 · 已完成")).toHaveClass(
      "sentry-unmask",
    );

    rerender(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="done"
        completedCount={5}
        requestedTotal={5}
        startedAt={1_000}
        finishedAt={226_000}
      />,
    );
    expect(screen.getByText("✓ 完成")).toHaveClass("sentry-unmask");
    expect(screen.getByText("題 ·")).toHaveClass("sentry-unmask");

    rerender(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="error"
        completedCount={1}
        requestedTotal={5}
        startedAt={1_000}
        finishedAt={13_000}
      />,
    );
    expect(screen.getByText("✕ 錯誤")).toHaveClass("sentry-unmask");
  });

  it("reports 尚未生成 before any run", () => {
    render(<GenerationStatusBar {...BASE_PROPS} />);
    expect(screen.getByText("尚未生成")).toBeInTheDocument();
  });

  it("reports 生成中 with the completed count out of the requested total while a run is live", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        completedCount={2}
        requestedTotal={5}
        startedAt={1_000}
      />,
    );
    const status = screen.getByTestId("statusbar-status");
    expect(status).toHaveTextContent("生成中");
    expect(status).toHaveTextContent("已完成 2 / 5");
  });

  it("reports the finished question count and the total duration after a run", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="done"
        completedCount={5}
        requestedTotal={5}
        startedAt={1_000}
        finishedAt={1_000 + 225_000}
      />,
    );
    const status = screen.getByTestId("statusbar-status");
    expect(status).toHaveTextContent("完成 5 題");
    expect(status).toHaveTextContent("3分45秒");
  });

  it("omits the minutes segment for a run shorter than a minute", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="done"
        completedCount={1}
        requestedTotal={1}
        startedAt={1_000}
        finishedAt={1_000 + 45_000}
      />,
    );
    const status = screen.getByTestId("statusbar-status");
    expect(status).toHaveTextContent("45秒");
    expect(status).not.toHaveTextContent("0分");
  });

  it("signals 錯誤 without repeating the error text when a run fails", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="error"
        completedCount={1}
        requestedTotal={5}
        startedAt={1_000}
        finishedAt={1_000 + 12_000}
      />,
    );
    const status = screen.getByTestId("statusbar-status");
    expect(status).toHaveTextContent("錯誤");
    expect(status).not.toHaveTextContent("生成中");
  });
});

describe("GenerationStatusBar — elapsed timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts up while a run is live", async () => {
    vi.setSystemTime(10_000);
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        runState="running"
        completedCount={0}
        requestedTotal={3}
        startedAt={10_000}
      />,
    );

    expect(screen.getByTestId("statusbar-elapsed")).toHaveTextContent("0秒");

    await act(async () => {
      vi.advanceTimersByTime(3_000);
    });

    expect(screen.getByTestId("statusbar-elapsed")).toHaveTextContent("3秒");
  });
});

describe("GenerationStatusBar — jump half", () => {
  it("unmasks fixed action labels in replays", () => {
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        availableTargets={["form", "progress", "results"]}
        onFeedback={vi.fn()}
      />,
    );

    for (const label of ["表單", "進度", "結果", "回饋"]) {
      expect(screen.getByRole("button", { name: label })).toHaveClass(
        "sentry-unmask",
      );
    }
  });

  it("jumps to a section that is on the page", () => {
    const onJump = vi.fn();
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        availableTargets={["form", "progress", "results"]}
        onJump={onJump}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "進度" }));

    expect(onJump).toHaveBeenCalledWith("progress");
  });

  it("makes a target inert while its section is absent from the page", () => {
    const onJump = vi.fn();
    render(
      <GenerationStatusBar
        {...BASE_PROPS}
        availableTargets={["form"]}
        onJump={onJump}
      />,
    );

    const results = screen.getByRole("button", { name: "結果" });
    expect(results).toBeDisabled();

    fireEvent.click(results);

    expect(onJump).not.toHaveBeenCalled();
  });
});

describe("GenerationStatusBar — 回饋", () => {
  it("opens the feedback form from inside the bar", () => {
    const onFeedback = vi.fn();
    render(<GenerationStatusBar {...BASE_PROPS} onFeedback={onFeedback} />);

    fireEvent.click(screen.getByRole("button", { name: "回饋" }));

    expect(onFeedback).toHaveBeenCalled();
  });

  it("omits 回饋 when no feedback handler is available", () => {
    render(<GenerationStatusBar {...BASE_PROPS} onFeedback={null} />);

    expect(screen.queryByRole("button", { name: "回饋" })).toBeNull();
  });
});
