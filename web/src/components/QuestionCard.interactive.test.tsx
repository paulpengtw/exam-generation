import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import QuestionCard from "./QuestionCard";
import type { ExamQuestion, SubQuestion } from "../hooks/useGenerate";

const ordinarySubquestion: SubQuestion = {
  id: "mc-1",
  序號: 1,
  年級: 8,
  科目: ["公民與社會"],
  核心素養: [],
  學習內容: [],
  學習表現: [],
  出題概念: "普通選擇題",
  題型: "選擇題",
  題目: "普通選擇題題幹",
  答案: "A",
  答案解析: "普通題解析",
  誘答分析: {},
};

const dragSubquestion: SubQuestion = {
  ...ordinarySubquestion,
  id: "drag-1",
  序號: 2,
  題型: "拖放題",
  題目: "請將例子放到正確的規範類型。",
  interaction: {
    draggables: [{ id: "d1", label: "例子一" }],
    targets: [{ id: "t1", label: "倫理道德", capacity: 1 }],
    correct_mapping: { d1: "t1" },
    exact_match: false,
    shuffle_draggables: false,
  },
};

const sliderSubquestion: SubQuestion = {
  ...ordinarySubquestion,
  id: "slider-1",
  序號: 3,
  題型: "滑桿題",
  題目: "請以滑桿標出正確數值。",
  interaction: {
    min: 0,
    max: 100,
    step: 1,
    unit: "%",
    correct_value: 63,
    tolerance: 2,
    show_ticks: true,
  },
};

function questionWith(subquestions: SubQuestion[]): ExamQuestion {
  return {
    id: "mixed-interactive-question",
    情境: ["社會"],
    題型種類: "題組題",
    題型: "混合題",
    文本: "共同文本",
    subquestions,
    題目: ["共同文本", ...subquestions.map((subquestion) => subquestion.題目)],
    正確解題分析: [],
  };
}

describe("QuestionCard interactive subquestion integration", () => {
  it("renders interactive viewers for drag-drop and slider subquestions in a mixed group", () => {
    render(<QuestionCard question={questionWith([ordinarySubquestion, dragSubquestion, sliderSubquestion])} />);

    expect(screen.getByText("普通選擇題題幹")).toBeInTheDocument();
    expect(screen.getAllByTestId("interactive-item-viewer")).toHaveLength(2);
    expect(screen.getByRole("slider", { name: "滑桿作答" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "例子一" })).toBeInTheDocument();
    expect(screen.getByText("請將例子放到正確的規範類型。")).toBeInTheDocument();
    expect(screen.getByText("請以滑桿標出正確數值。")).toBeInTheDocument();
  });

  it("does not render an interactive viewer for an ordinary subquestion", () => {
    render(<QuestionCard question={questionWith([ordinarySubquestion])} />);

    expect(screen.queryByTestId("interactive-item-viewer")).not.toBeInTheDocument();
    expect(screen.getByText("普通選擇題題幹")).toBeInTheDocument();
  });

  it("keeps the stem above the controls and forwards in-page submissions", () => {
    const onInteractionSubmit = vi.fn();
    render(
      <QuestionCard
        question={questionWith([dragSubquestion, sliderSubquestion])}
        onInteractionSubmit={onInteractionSubmit}
      />,
    );

    const dragViewer = screen.getAllByTestId("interactive-item-viewer")[0];
    const stem = screen.getByText("請將例子放到正確的規範類型。");
    expect(stem).toBeInTheDocument();
    expect(stem.compareDocumentPosition(dragViewer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(within(dragViewer).getByRole("button", { name: "例子一" }));
    fireEvent.click(within(dragViewer).getByRole("group", { name: "倫理道德" }));
    fireEvent.click(within(dragViewer).getByRole("button", { name: "檢查答案" }));

    expect(onInteractionSubmit).toHaveBeenCalledWith({
      item_id: "drag-1",
      題型: "拖放題",
      response: { placements: { d1: "t1" } },
      score: 1,
      max_score: 1,
    });
  });
});
