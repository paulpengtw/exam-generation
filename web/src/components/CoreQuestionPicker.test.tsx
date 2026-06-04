import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CoreQuestionPicker from "./CoreQuestionPicker";

// Use English locale for all tests
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../api/client", () => ({
  planCoreQuestions: vi.fn(),
}));

const defaultProps = {
  topic: "Calculus",
  onPick: vi.fn(),
  onClear: vi.fn(),
  pickedValue: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CoreQuestionPicker — use my core question button", () => {
  it("renders the 'Use my core question' button enabled when topic is non-empty", () => {
    render(<CoreQuestionPicker {...defaultProps} />);
    const btn = screen.getByRole("button", { name: "Use my core question" });
    expect(btn).toBeEnabled();
  });

  it("disables the button when topic is empty", () => {
    render(<CoreQuestionPicker {...defaultProps} topic="" />);
    const btn = screen.getByRole("button", { name: "Use my core question" });
    expect(btn).toBeDisabled();
  });

  it("calls onPick with the trimmed topic value on click", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    render(<CoreQuestionPicker {...defaultProps} topic="  My topic  " onPick={onPick} />);
    await user.click(screen.getByRole("button", { name: "Use my core question" }));
    expect(onPick).toHaveBeenCalledWith("My topic");
  });

  it("both action buttons appear side by side", () => {
    render(<CoreQuestionPicker {...defaultProps} />);
    expect(screen.getByRole("button", { name: "Generate core question candidates" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use my core question" })).toBeInTheDocument();
  });

  it("button is disabled while AI candidates are loading", async () => {
    const { planCoreQuestions } = await import("../api/client");
    // Never resolves — simulates loading state
    vi.mocked(planCoreQuestions).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    render(<CoreQuestionPicker {...defaultProps} />);
    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));
    expect(screen.getByRole("button", { name: "Use my core question" })).toBeDisabled();
  });
});
