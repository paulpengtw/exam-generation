import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import QuestionCard from "./QuestionCard";
import type { ExamQuestion, SubQuestion } from "../hooks/useGenerate";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const question: ExamQuestion = {
  id: "q_test",
  情境: ["Personal"],
  題型種類: "Single question",
  題型: "Multiple choice",
  數學思考: ["Reasoning"],
  學習內容: [{ 編碼: "N-7-1", 說明: "Numbers" }],
  題目: ["What is 2 + 2?"],
  正確解題分析: ["2 + 2 = 4."],
};

describe("QuestionCard draft rendering", () => {
  it("marks draft cards, shows available solution content, and disables downloads", () => {
    render(<QuestionCard question={question} phase="draft" isFinal={false} />);

    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("2 + 2 = 4.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download ODT" })).toBeDisabled();
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("QuestionCard + FigureRenderer swap", () => {
  it("renders the PNG img when VITE_ENABLE_FRONTEND_TS_RENDERER is unset", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "");
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: {
        render_mode: "html",
        description: "課表",
        data: { columns: ["a"], rows: [["1"]] },
      },
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "data:image/png;base64,aGVsbG8=",
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders the FigureRenderer when the flag is on and the spec is supported", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: {
        render_mode: "html",
        description: "課表",
        data: { columns: ["時段"], rows: [["9:00"]] },
      },
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    // The PNG <img> should not be rendered in the diagram slot when the TS renderer took over.
    expect(screen.queryByAltText("Question diagram")).toBeNull();
  });

  it("falls back to the PNG img when the flag is on but the spec is unsupported", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: { render_mode: "chart", chart_type: "histogram", data: {} },
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByAltText("Question diagram")).toHaveAttribute(
      "src",
      "data:image/png;base64,aGVsbG8=",
    );
    expect(warn).toHaveBeenCalledWith(
      expect.stringMatching(/^\[figure-renderer-fallback]/),
      expect.anything(),
    );
    warn.mockRestore();
  });
});

const ssSub: SubQuestion = {
  id: "sq1",
  序號: 1,
  年級: 8,
  科目: ["地理"],
  核心素養: ["社-J-A2"],
  學習內容: [],
  學習表現: [],
  出題概念: "",
  題型: "選擇題",
  題目: "Q? (A) x (B) y (C) z (D) w",
  答案: "B",
  答案解析: "…",
  評分規準: [],
  誘答分析: {
    A: "誤讀題意",
    B: "正確答案：y。",
    C: "概念混淆",
    D: "過度推論",
  },
};

const ssQuestion: ExamQuestion = {
  id: "ss1",
  情境: ["公共"],
  題型種類: "題組題",
  題型: "選擇題",
  核心問題: "core?",
  文本: "passage",
  subquestions: [ssSub],
  題目: ["passage", ssSub.題目],
  正確解題分析: ["B"],
};

describe("QuestionCard distractor panel", () => {
  it("renders 誘答分析 rows inside a subquestion when the dict is non-empty", () => {
    render(<QuestionCard question={ssQuestion} phase="verified" isFinal={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Answer" }));
    fireEvent.click(screen.getByRole("button", { name: "Show Distractor Analysis" }));
    expect(screen.getByText("誤讀題意")).toBeInTheDocument();
    expect(screen.getByText(/正確答案：y/)).toBeInTheDocument();
  });

  it("does not render the toggle button when 誘答分析 is empty", () => {
    const emptySub: SubQuestion = { ...ssSub, 誘答分析: {} };
    const empty: ExamQuestion = { ...ssQuestion, subquestions: [emptySub] };
    render(<QuestionCard question={empty} phase="verified" isFinal={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Answer" }));
    expect(screen.queryByRole("button", { name: "Show Distractor Analysis" })).not.toBeInTheDocument();
  });

  it("renders 誘答分析 on math flat questions", () => {
    const mathQ: ExamQuestion = {
      ...question,
      誘答分析: { A: "誤讀題意", B: "正確答案：4。", C: "x", D: "y" },
    };
    render(<QuestionCard question={mathQ} phase="verified" isFinal={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Show Solution" }));
    fireEvent.click(screen.getByRole("button", { name: "Show Distractor Analysis" }));
    expect(screen.getByText(/正確答案：4/)).toBeInTheDocument();
  });
});
