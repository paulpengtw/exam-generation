import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import GenerationStatusBar, {
  type GenerationStatusBarProps,
} from "./GenerationStatusBar";

const BASE_PROPS: GenerationStatusBarProps = {
  runState: "idle",
  completedCount: 0,
  requestedTotal: 0,
  startedAt: null,
  finishedAt: null,
  availableTargets: ["form"],
  onJump: vi.fn(),
  onFeedback: null,
};

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
