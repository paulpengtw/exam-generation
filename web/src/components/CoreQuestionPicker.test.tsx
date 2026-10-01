import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CoreQuestionPicker from "./CoreQuestionPicker";

// Use English locale for all tests
vi.mock("../store/langStore", () => ({
  useLangStore: Object.assign(
    (selector: (s: { lang: string }) => unknown) => selector({ lang: "en-US" }),
    { getState: () => ({ lang: "en-US" }) },
  ),
}));

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    detail: string;
    code?: string;
    failureClass?: string | null;

    constructor(status: number, detail: string, code?: string, _errors?: unknown, failureClass?: string | null) {
      super(detail);
      this.name = "ApiError";
      this.status = status;
      this.detail = detail;
      this.code = code;
      this.failureClass = failureClass ?? null;
    }
  },
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

  it("announces candidate generation as pending on the control", async () => {
    const { planCoreQuestions } = await import("../api/client");
    let resolve!: (value: { candidates: string[] }) => void;
    vi.mocked(planCoreQuestions).mockReturnValueOnce(new Promise((yes) => { resolve = yes; }));
    const user = userEvent.setup();
    render(<CoreQuestionPicker {...defaultProps} />);

    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));
    expect(screen.getByRole("status")).toHaveTextContent("Generating candidates…");
    expect(screen.getByRole("button", { name: "Generating candidates…" })).toBeDisabled();
    await resolve({ candidates: [] });
  });

  it("keeps the planner label and marks only that control after failure", async () => {
    const { planCoreQuestions } = await import("../api/client");
    vi.mocked(planCoreQuestions).mockRejectedValueOnce(new Error("provider detail"));
    const user = userEvent.setup();
    render(<CoreQuestionPicker {...defaultProps} />);

    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));

    const planner = screen.getByRole("button", { name: "Generate core question candidates" });
    expect(planner).toHaveAttribute("data-action-state", "failed");
    expect(planner).toHaveTextContent("Generate core question candidates");
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to generate core question candidates.");
    expect(screen.getByRole("button", { name: "Use my core question" })).not.toHaveAttribute(
      "data-action-state",
      "failed",
    );
  });

  it("does not fail a planner call that runs longer than 30 seconds", async () => {
    vi.useFakeTimers();
    try {
      const { planCoreQuestions } = await import("../api/client");
      let resolve!: (value: { candidates: string[] }) => void;
      vi.mocked(planCoreQuestions).mockReturnValueOnce(new Promise((yes) => { resolve = yes; }));
      render(<CoreQuestionPicker {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Generate core question candidates" }));
      await act(async () => {
        vi.advanceTimersByTime(30_001);
      });

      expect(screen.getByRole("status")).toHaveTextContent("Generating candidates…");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();

      await act(async () => {
        resolve({ candidates: [] });
        await Promise.resolve();
      });
    } finally {
      vi.clearAllTimers();
      vi.useRealTimers();
    }
  });
});

// ---------------------------------------------------------------------------
// issue #946 — failure_class localization in CoreQuestionPicker
// ---------------------------------------------------------------------------

describe("CoreQuestionPicker — failure_class localized message (issue #946)", () => {
  it("shows localized message when 502 ApiError has a recognized failure_class (rate_limited)", async () => {
    const { ApiError, planCoreQuestions } = await import("../api/client");
    vi.mocked(planCoreQuestions).mockRejectedValueOnce(
      new ApiError(502, "Planner provider call failed", "PLANNER_PROVIDER_ERROR", undefined, "rate_limited"),
    );
    const user = userEvent.setup();
    render(<CoreQuestionPicker {...defaultProps} />);

    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));

    const alert = screen.getByRole("alert");
    // Must show the localized label and hint — NOT the raw backend "Planner provider call failed"
    expect(alert).toHaveTextContent("Rate limited");
    expect(alert).toHaveTextContent("wait");
    expect(alert).not.toHaveTextContent("Planner provider call failed");
  });

  it("shows localized admin-only message for quota_billing_exhausted", async () => {
    const { ApiError, planCoreQuestions } = await import("../api/client");
    vi.mocked(planCoreQuestions).mockRejectedValueOnce(
      new ApiError(502, "Planner provider call failed", "PLANNER_PROVIDER_ERROR", undefined, "quota_billing_exhausted"),
    );
    const user = userEvent.setup();
    render(<CoreQuestionPicker {...defaultProps} />);

    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Quota or billing exhausted");
    expect(alert).toHaveTextContent("Please contact the administrator");
  });

  it("shows ApiError.detail when failure_class is absent (no localization override)", async () => {
    const { ApiError, planCoreQuestions } = await import("../api/client");
    vi.mocked(planCoreQuestions).mockRejectedValueOnce(
      new ApiError(502, "Planner upstream returned malformed candidates", "PLANNER_MALFORMED_OUTPUT"),
    );
    const user = userEvent.setup();
    render(<CoreQuestionPicker {...defaultProps} />);

    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));

    const alert = screen.getByRole("alert");
    // No failure_class → ApiError.detail is shown (existing behavior, no localization override)
    expect(alert).toHaveTextContent("Planner upstream returned malformed candidates");
    // Must NOT show the rate_limited or quota messages
    expect(alert).not.toHaveTextContent("Rate limited");
    expect(alert).not.toHaveTextContent("Please contact the administrator");
  });
});
