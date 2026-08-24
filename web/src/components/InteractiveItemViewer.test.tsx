import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import InteractiveItemViewer from "./InteractiveItemViewer";
import type { DragDropSpec, SliderSpec } from "../hooks/useGenerate";

const sliderSpec: SliderSpec = {
  min: 0,
  max: 100,
  step: 1,
  unit: "%",
  correct_value: 63,
  tolerance: 2,
  show_ticks: true,
};

const dragDropSpec: DragDropSpec = {
  draggables: [
    { id: "d1", label: "例子一" },
    { id: "d2", label: "例子二" },
    { id: "d3", label: "例子三" },
  ],
  targets: [
    { id: "t1", label: "倫理道德", capacity: 2 },
    { id: "t2", label: "法律", capacity: 1 },
    { id: "t3", label: "宗教信仰", capacity: 1 },
  ],
  correct_mapping: { d1: "t1", d2: "t2", d3: "t3" },
  exact_match: false,
  shuffle_draggables: true,
};

function renderSlider(
  distractorAnalysis: Record<string, string> = {},
  overrides: Partial<SliderSpec> = {},
) {
  const onSubmit = vi.fn();
  render(
    <InteractiveItemViewer
      itemId="slider-1"
      題型="滑桿題"
      interaction={{ ...sliderSpec, ...overrides }}
      distractorAnalysis={distractorAnalysis}
      onSubmit={onSubmit}
    />,
  );
  return {
    onSubmit,
    slider: screen.getByRole("slider", { name: "滑桿作答" }),
  };
}

function renderDragDrop(
  spec: DragDropSpec = dragDropSpec,
  distractorAnalysis: Record<string, string> = {},
) {
  const onSubmit = vi.fn();
  render(
    <InteractiveItemViewer
      itemId="drag-1"
      題型="拖放題"
      interaction={spec}
      distractorAnalysis={distractorAnalysis}
      onSubmit={onSubmit}
    />,
  );
  return { onSubmit };
}

function dragTarget(label: string): HTMLElement {
  return screen.getByRole("group", { name: label });
}

async function placeByClick(user: ReturnType<typeof userEvent.setup>, draggable: string, target: string) {
  await user.click(screen.getByRole("button", { name: draggable }));
  await user.click(dragTarget(target));
}

describe("InteractiveItemViewer slider", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the configured range, unit, live value, and ticks", () => {
    const { slider } = renderSlider();

    expect(slider).toHaveAttribute("min", "0");
    expect(slider).toHaveAttribute("max", "100");
    expect(slider).toHaveAttribute("step", "1");
    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(screen.getByTestId("interactive-slider-value")).toHaveTextContent("50%");
    expect(screen.getByTestId("interactive-slider-ticks")).toBeInTheDocument();

    fireEvent.change(slider, { target: { value: "63" } });

    expect(screen.getByTestId("interactive-slider-value")).toHaveTextContent("63%");
  });

  it("scores a correct value and emits the locked submission object", () => {
    const { onSubmit, slider } = renderSlider();

    fireEvent.change(slider, { target: { value: "63" } });
    fireEvent.click(screen.getByRole("button", { name: "檢查答案" }));

    expect(screen.getByTestId("interactive-score")).toHaveTextContent("得分 1 / 1");
    expect(screen.getByTestId("interactive-score")).toHaveAttribute("role", "status");
    expect(screen.getByTestId("interactive-verdict")).toHaveTextContent("✓");
    expect(screen.getByTestId("interactive-verdict")).toHaveAttribute("aria-label", "答對");
    expect(onSubmit).toHaveBeenCalledWith({
      item_id: "slider-1",
      題型: "滑桿題",
      response: { value: 63 },
      score: 1,
      max_score: 1,
    });
  });

  it("scores a wrong value and shows the matching named-zone rationale", () => {
    const rationale = "取到舊資料，沒有讀到題目指定的年份。";
    const { onSubmit, slider } = renderSlider({
      below_range: rationale,
      far_off: "未依資料作答。",
    });

    fireEvent.change(slider, { target: { value: "55" } });
    fireEvent.click(screen.getByRole("button", { name: "檢查答案" }));

    expect(screen.getByTestId("interactive-score")).toHaveTextContent("得分 0 / 1");
    expect(screen.getByTestId("interactive-verdict")).toHaveTextContent("✗");
    expect(screen.getByTestId("interactive-verdict")).toHaveAttribute("aria-label", "答錯");
    expect(screen.getByTestId("interactive-feedback")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText(rationale)).toBeInTheDocument();
    expect(onSubmit).toHaveBeenCalledWith({
      item_id: "slider-1",
      題型: "滑桿題",
      response: { value: 55 },
      score: 0,
      max_score: 1,
    });
  });

  it("uses far-off rationale outside a nearby directional wrong zone", () => {
    const nearRationale = "取到鄰近的舊資料。";
    const farRationale = "未依資料作答，可能僅憑直覺估計。";
    const { slider } = renderSlider({
      below_range: nearRationale,
      far_off: farRationale,
    });

    fireEvent.change(slider, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "檢查答案" }));

    expect(screen.getByText(farRationale)).toBeInTheDocument();
    expect(screen.queryByText(nearRationale)).not.toBeInTheDocument();
  });

  it("resets the value and clears a prior submission", () => {
    const { slider } = renderSlider({ below_range: "錯誤區間說明" });

    fireEvent.change(slider, { target: { value: "63" } });
    fireEvent.click(screen.getByRole("button", { name: "檢查答案" }));
    expect(screen.getByTestId("interactive-score")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重設" }));

    expect(slider).toHaveValue("50");
    expect(screen.getByTestId("interactive-slider-value")).toHaveTextContent("50%");
    expect(screen.queryByTestId("interactive-score")).not.toBeInTheDocument();
    expect(screen.queryByTestId("interactive-verdict")).not.toBeInTheDocument();
  });
});

describe("InteractiveItemViewer drag and drop", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("places chips with the click-to-place path and gives partial credit with pair rationale", async () => {
    const user = userEvent.setup();
    const rationale = "這個例子屬於另一種規範類型。";
    const { onSubmit } = renderDragDrop(dragDropSpec, { "d3→t1": rationale });

    await placeByClick(user, "例子一", "倫理道德");
    await placeByClick(user, "例子二", "法律");
    await placeByClick(user, "例子三", "倫理道德");
    await user.click(screen.getByRole("button", { name: "檢查答案" }));

    expect(screen.getByTestId("interactive-score")).toHaveTextContent("得分 2 / 3");
    expect(screen.getByTestId("interactive-verdict-d1")).toHaveTextContent("✓");
    expect(screen.getByTestId("interactive-verdict-d2")).toHaveTextContent("✓");
    expect(screen.getByTestId("interactive-verdict-d3")).toHaveTextContent("✗");
    expect(screen.getByText(rationale)).toBeInTheDocument();
    expect(onSubmit).toHaveBeenCalledWith({
      item_id: "drag-1",
      題型: "拖放題",
      response: { placements: { d1: "t1", d2: "t2", d3: "t1" } },
      score: 2,
      max_score: 3,
    });
  });

  it("marks an expected but unplaced chip wrong", async () => {
    const user = userEvent.setup();
    renderDragDrop();

    await placeByClick(user, "例子一", "倫理道德");
    await placeByClick(user, "例子二", "法律");
    await user.click(screen.getByRole("button", { name: "檢查答案" }));

    const unplacedChip = screen.getByTestId("interactive-chip-d3");
    expect(within(unplacedChip).getByTestId("interactive-verdict-d3")).toHaveTextContent("✗");
    expect(screen.getByTestId("interactive-score")).toHaveTextContent("得分 2 / 3");
  });

  it("applies exact-match scoring as all-or-nothing in both directions", async () => {
    const user = userEvent.setup();
    const exactSpec: DragDropSpec = {
      ...dragDropSpec,
      targets: dragDropSpec.targets.map((target) => ({ ...target, capacity: 2 })),
      exact_match: true,
    };
    const { onSubmit } = renderDragDrop(exactSpec);

    await placeByClick(user, "例子一", "倫理道德");
    await placeByClick(user, "例子二", "倫理道德");
    await placeByClick(user, "例子三", "宗教信仰");
    await user.click(screen.getByRole("button", { name: "檢查答案" }));
    expect(screen.getByTestId("interactive-score")).toHaveTextContent("得分 0 / 3");

    await user.click(screen.getByRole("button", { name: "重設" }));
    await placeByClick(user, "例子一", "倫理道德");
    await placeByClick(user, "例子二", "法律");
    await placeByClick(user, "例子三", "宗教信仰");
    await user.click(screen.getByRole("button", { name: "檢查答案" }));

    expect(screen.getByTestId("interactive-score")).toHaveTextContent("得分 3 / 3");
    expect(onSubmit).toHaveBeenNthCalledWith(1, expect.objectContaining({ score: 0, max_score: 3 }));
    expect(onSubmit).toHaveBeenNthCalledWith(2, expect.objectContaining({ score: 3, max_score: 3 }));
  });

  it("refuses a placement when the target capacity is full", async () => {
    const user = userEvent.setup();
    const capacitySpec: DragDropSpec = {
      ...dragDropSpec,
      targets: dragDropSpec.targets.map((target) => (
        target.id === "t1" ? { ...target, capacity: 1 } : target
      )),
    };
    renderDragDrop(capacitySpec);

    await placeByClick(user, "例子一", "倫理道德");
    await user.click(screen.getByRole("button", { name: "例子二" }));
    await user.click(dragTarget("倫理道德"));

    expect(screen.getByRole("button", { name: "例子二" })).toBeInTheDocument();
    expect(within(dragTarget("倫理道德")).getByText("例子一")).toBeInTheDocument();
    expect(within(dragTarget("倫理道德")).queryByText("例子二")).not.toBeInTheDocument();
  });

  it("defaults an omitted target capacity to one", async () => {
    const user = userEvent.setup();
    const defaultCapacitySpec = {
      ...dragDropSpec,
      targets: dragDropSpec.targets.map((target) => ({ id: target.id, label: target.label })),
    } as unknown as DragDropSpec;
    renderDragDrop(defaultCapacitySpec);

    await placeByClick(user, "例子一", "倫理道德");
    await user.click(screen.getByRole("button", { name: "例子二" }));
    await user.click(dragTarget("倫理道德"));

    expect(screen.getByRole("button", { name: "例子二" })).toBeInTheDocument();
    expect(within(dragTarget("倫理道德")).queryByText("例子二")).not.toBeInTheDocument();
  });

  it("supports HTML5 drag-and-drop placement", () => {
    const dataTransfer = {
      setData: vi.fn(),
      getData: vi.fn(() => "d1"),
      effectAllowed: "move",
      dropEffect: "move",
    };
    renderDragDrop();

    const chip = screen.getByRole("button", { name: "例子一" });
    const target = dragTarget("倫理道德");
    fireEvent.dragStart(chip, { dataTransfer });
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });

    expect(within(target).getByText("例子一")).toBeInTheDocument();
    expect(dataTransfer.setData).toHaveBeenCalled();
  });

  it("can reset and answer again after submitting", async () => {
    const user = userEvent.setup();
    const rationale = "錯誤的目標反映概念混淆。";
    const { onSubmit } = renderDragDrop(dragDropSpec, { "d1→t2": rationale });

    await placeByClick(user, "例子一", "法律");
    await user.click(screen.getByRole("button", { name: "檢查答案" }));
    expect(screen.getByText(rationale)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "移除 例子一" }));
    await placeByClick(user, "例子一", "倫理道德");
    await user.click(screen.getByRole("button", { name: "檢查答案" }));

    expect(screen.getByTestId("interactive-verdict-d1")).toHaveTextContent("✓");
    expect(screen.queryByText(rationale)).not.toBeInTheDocument();
    expect(onSubmit).toHaveBeenCalledTimes(2);
    expect(onSubmit).toHaveBeenLastCalledWith(expect.objectContaining({
      response: { placements: { d1: "t1" } },
      score: 1,
      max_score: 3,
    }));

    await user.click(screen.getByRole("button", { name: "重設" }));
    expect(screen.queryByTestId("interactive-score")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "例子一" })).toBeInTheDocument();
  });
});
