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

describe("CoreQuestionPicker — custom question input", () => {
  it("renders the custom input and disabled button when input is empty", () => {
    render(<CoreQuestionPicker {...defaultProps} />);
    const input = screen.getByPlaceholderText("Type your own core question…");
    const btn = screen.getByRole("button", { name: "Use my core question" });
    expect(input).toBeInTheDocument();
    expect(btn).toBeDisabled();
  });

  it("enables the button once text is typed", async () => {
    const user = userEvent.setup();
    render(<CoreQuestionPicker {...defaultProps} />);
    const input = screen.getByPlaceholderText("Type your own core question…");
    const btn = screen.getByRole("button", { name: "Use my core question" });
    await user.type(input, "What is the derivative of x²?");
    expect(btn).toBeEnabled();
  });

  it("calls onPick with trimmed value and clears input on click", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    render(<CoreQuestionPicker {...defaultProps} onPick={onPick} />);
    const input = screen.getByPlaceholderText("Type your own core question…");
    await user.type(input, "  My custom question  ");
    await user.click(screen.getByRole("button", { name: "Use my core question" }));
    expect(onPick).toHaveBeenCalledWith("My custom question");
    expect(input).toHaveValue("");
  });

  it("pressing Enter in the custom input does not submit the form", async () => {
    const onSubmit = vi.fn();
    render(
      <form onSubmit={onSubmit}>
        <CoreQuestionPicker {...defaultProps} />
      </form>,
    );
    const input = screen.getByPlaceholderText("Type your own core question…");
    await userEvent.type(input, "test{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("button is disabled while AI candidates are loading", async () => {
    const { planCoreQuestions } = await import("../api/client");
    // Never resolves — simulates loading state
    vi.mocked(planCoreQuestions).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    render(<CoreQuestionPicker {...defaultProps} />);
    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));
    await user.type(screen.getByPlaceholderText("Type your own core question…"), "anything");
    expect(screen.getByRole("button", { name: "Use my core question" })).toBeDisabled();
  });
});
