import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CoreQuestionPicker from "./CoreQuestionPicker";
import { clampPickerEffort } from "./pickerEffortClamp";

// Use English locale for all tests
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    detail: string;

    constructor(_status: number, detail: string) {
      super(detail);
      this.name = "ApiError";
      this.detail = detail;
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

const ALLOWED_MODELS = ["gemini-3.1-pro-preview", "claude-opus-4-6", "claude-sonnet-4-6"];
const modelsWithGemini = {
  allowed: ALLOWED_MODELS,
  effort: {
    "gemini-3.1-pro-preview": ["low", "medium", "high"],
    "claude-opus-4-6": ["low", "medium", "high"],
  },
  defaults: { plan: "claude-opus-4-6", execute: "gemini-3.1-pro-preview", verify: "claude-opus-4-6", correct: "claude-opus-4-6", effort_plan: "high" },
};
const modelsWithoutGemini = {
  allowed: ["claude-opus-4-6", "claude-sonnet-4-6"],
  effort: { "claude-opus-4-6": ["low", "medium", "high"] },
  defaults: { plan: "claude-opus-4-6", execute: "claude-sonnet-4-6", verify: "claude-opus-4-6", correct: "claude-opus-4-6" },
};

describe("CoreQuestionPicker — model selector", () => {
  it("sends model_plan when pickerModelPlan is in the allowed list", async () => {
    const { planCoreQuestions } = await import("../api/client");
    vi.mocked(planCoreQuestions).mockResolvedValueOnce({ candidates: ["Q1"] });
    const user = userEvent.setup();
    render(
      <CoreQuestionPicker
        {...defaultProps}
        models={modelsWithGemini}
        pickerModelPlan="gemini-3.1-pro-preview"
        pickerEffortPlan="high"
        onPickerModelPlanChange={vi.fn()}
        onPickerEffortPlanChange={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));
    await screen.findByText("Q1");
    expect(vi.mocked(planCoreQuestions)).toHaveBeenCalledWith(
      expect.objectContaining({ model_plan: "gemini-3.1-pro-preview", effort_plan: "high" }),
      expect.any(AbortSignal),
    );
  });

  it("does not send model_plan when pickerModelPlan is not in the allowed list", async () => {
    const { planCoreQuestions } = await import("../api/client");
    vi.mocked(planCoreQuestions).mockResolvedValueOnce({ candidates: ["Q1"] });
    const user = userEvent.setup();
    render(
      <CoreQuestionPicker
        {...defaultProps}
        models={modelsWithoutGemini}
        pickerModelPlan="gemini-3.1-pro-preview"
        onPickerModelPlanChange={vi.fn()}
        onPickerEffortPlanChange={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));
    await screen.findByText("Q1");
    const call = vi.mocked(planCoreQuestions).mock.calls[0][0];
    expect(call.model_plan).toBeUndefined();
  });

  it("does not send model_plan when models prop is absent", async () => {
    const { planCoreQuestions } = await import("../api/client");
    vi.mocked(planCoreQuestions).mockResolvedValueOnce({ candidates: ["Q1"] });
    const user = userEvent.setup();
    render(<CoreQuestionPicker {...defaultProps} />);
    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));
    await screen.findByText("Q1");
    const call = vi.mocked(planCoreQuestions).mock.calls[0][0];
    expect(call.model_plan).toBeUndefined();
  });

  it("shows the model dropdown when models prop is provided", async () => {
    render(
      <CoreQuestionPicker
        {...defaultProps}
        models={modelsWithGemini}
        pickerModelPlan="gemini-3.1-pro-preview"
        onPickerModelPlanChange={vi.fn()}
        onPickerEffortPlanChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Core question model" })).toBeInTheDocument();
  });

  it("shows gemini-3.1-pro-preview selected by default in the dropdown", async () => {
    render(
      <CoreQuestionPicker
        {...defaultProps}
        models={modelsWithGemini}
        pickerModelPlan="gemini-3.1-pro-preview"
        onPickerModelPlanChange={vi.fn()}
        onPickerEffortPlanChange={vi.fn()}
      />,
    );
    const select = screen.getByRole("combobox", { name: "Core question model" }) as HTMLSelectElement;
    expect(select.value).toBe("gemini-3.1-pro-preview");
  });

  it("hides the model dropdown when models prop is absent", () => {
    render(<CoreQuestionPicker {...defaultProps} />);
    expect(screen.queryByRole("combobox", { name: "Core question model" })).toBeNull();
  });

  it("shows the effort dropdown when models include effort levels", () => {
    render(
      <CoreQuestionPicker
        {...defaultProps}
        models={modelsWithGemini}
        pickerModelPlan="gemini-3.1-pro-preview"
        pickerEffortPlan="high"
        onPickerModelPlanChange={vi.fn()}
        onPickerEffortPlanChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Core question effort" })).toBeInTheDocument();
  });

  it("does not send effort_plan when pickerEffortPlan is empty", async () => {
    const { planCoreQuestions } = await import("../api/client");
    vi.mocked(planCoreQuestions).mockResolvedValueOnce({ candidates: ["Q1"] });
    const user = userEvent.setup();
    render(
      <CoreQuestionPicker
        {...defaultProps}
        models={modelsWithGemini}
        pickerModelPlan="gemini-3.1-pro-preview"
        pickerEffortPlan=""
        onPickerModelPlanChange={vi.fn()}
        onPickerEffortPlanChange={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Generate core question candidates" }));
    await screen.findByText("Q1");
    const call = vi.mocked(planCoreQuestions).mock.calls[0][0];
    expect(call.effort_plan).toBeUndefined();
  });

  it("clamps effort when model changes to one that doesn't support the current effort", async () => {
    const onPickerEffortPlanChange = vi.fn();
    const user = userEvent.setup();
    const modelsWithFiveEffort = {
      allowed: ["claude-opus-5", "gemini-3.1-pro-preview"],
      effort: {
        "claude-opus-5": ["low", "medium", "high", "xhigh", "max"],
        "gemini-3.1-pro-preview": ["low", "medium", "high"],
      },
      defaults: { plan: "claude-opus-5", execute: "gemini-3.1-pro-preview", verify: "claude-opus-5", correct: "claude-opus-5" },
    };
    render(
      <CoreQuestionPicker
        {...defaultProps}
        models={modelsWithFiveEffort}
        pickerModelPlan="claude-opus-5"
        pickerEffortPlan="xhigh"
        onPickerModelPlanChange={vi.fn()}
        onPickerEffortPlanChange={onPickerEffortPlanChange}
      />,
    );
    await user.selectOptions(screen.getByRole("combobox", { name: "Core question model" }), "gemini-3.1-pro-preview");
    expect(onPickerEffortPlanChange).toHaveBeenCalledWith("medium");
  });

  it("clamps effort when switching to '' (server default) whose effective model doesn't support the current effort", async () => {
    const onPickerEffortPlanChange = vi.fn();
    const user = userEvent.setup();
    const modelsServerDefaultHasNoXhigh = {
      allowed: ["claude-opus-5", "claude-opus-4-6"],
      effort: {
        "claude-opus-5": ["low", "medium", "high", "xhigh", "max"],
        "claude-opus-4-6": ["low", "medium", "high", "max"],
      },
      defaults: { plan: "claude-opus-4-6", execute: "claude-opus-5", verify: "claude-opus-4-6", correct: "claude-opus-4-6" },
    };
    render(
      <CoreQuestionPicker
        {...defaultProps}
        models={modelsServerDefaultHasNoXhigh}
        pickerModelPlan="claude-opus-5"
        pickerEffortPlan="xhigh"
        onPickerModelPlanChange={vi.fn()}
        onPickerEffortPlanChange={onPickerEffortPlanChange}
      />,
    );
    // Switch to "" (server default), whose effective model (claude-opus-4-6) doesn't support "xhigh"
    await user.selectOptions(screen.getByRole("combobox", { name: "Core question model" }), "");
    expect(onPickerEffortPlanChange).toHaveBeenCalledWith("medium");
  });
});

const modelsForClamp = {
  allowed: ["gemini-3.1-pro-preview", "claude-opus-4-6", "claude-opus-5"],
  effort: {
    "gemini-3.1-pro-preview": ["low", "medium", "high"],
    "claude-opus-4-6": ["low", "medium", "high", "max"],
    "claude-opus-5": ["low", "medium", "high", "xhigh", "max"],
  },
  defaults: { plan: "claude-opus-4-6", execute: "gemini-3.1-pro-preview", verify: "claude-opus-4-6", correct: "claude-opus-4-6", effort_plan: "high" },
};

describe("clampPickerEffort", () => {
  it("returns supported effort unchanged", () => {
    expect(clampPickerEffort(modelsForClamp, "gemini-3.1-pro-preview", "medium")).toBe("medium");
    expect(clampPickerEffort(modelsForClamp, "claude-opus-4-6", "max")).toBe("max");
    expect(clampPickerEffort(modelsForClamp, "claude-opus-5", "xhigh")).toBe("xhigh");
  });

  it("clamps unsupported effort to 'medium' when available", () => {
    expect(clampPickerEffort(modelsForClamp, "gemini-3.1-pro-preview", "max")).toBe("medium");
    expect(clampPickerEffort(modelsForClamp, "gemini-3.1-pro-preview", "xhigh")).toBe("medium");
    expect(clampPickerEffort(modelsForClamp, "claude-opus-4-6", "xhigh")).toBe("medium");
  });

  it("resolves '' model to defaults.plan roster", () => {
    // defaults.plan = "claude-opus-4-6" which supports ["low","medium","high","max"]
    expect(clampPickerEffort(modelsForClamp, "", "max")).toBe("max");   // max is in claude-opus-4-6's roster
    expect(clampPickerEffort(modelsForClamp, "", "xhigh")).toBe("medium"); // xhigh is NOT in claude-opus-4-6's roster
  });

  it("uses server fallback roster for unknown models", () => {
    // Unknown model → ["low","medium","high","max"] (server default)
    expect(clampPickerEffort(modelsForClamp, "unknown-model", "max")).toBe("max");
    expect(clampPickerEffort(modelsForClamp, "unknown-model", "xhigh")).toBe("medium");
  });

  it("returns effort unchanged when models.effort is absent", () => {
    const modelsNoEffort = { ...modelsForClamp, effort: undefined };
    expect(clampPickerEffort(modelsNoEffort, "gemini-3.1-pro-preview", "xhigh")).toBe("xhigh");
  });

  it("returns effort unchanged when effort is empty", () => {
    expect(clampPickerEffort(modelsForClamp, "gemini-3.1-pro-preview", "")).toBe("");
  });
});
