import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import QuestionCard from "./QuestionCard";
import type { ExamQuestion } from "../hooks/useGenerate";

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
