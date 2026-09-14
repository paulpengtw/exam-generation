import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => ({ payload, drawn: [] })),
}));

import ParamForm from "./ParamForm";

const MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "standard", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

const MODELS_WITH_EFFORT = {
  allowed: ["claude-opus-4-6", "claude-sonnet-4-6"],
  effort: {
    "claude-opus-4-6": ["low", "medium", "high", "max", "xhigh"],
    "claude-sonnet-4-6": ["low", "medium", "high", "max"],
  },
  defaults: {
    plan: "claude-opus-4-6",
    execute: "claude-sonnet-4-6",
    verify: "",
    correct: "",
    effort_plan: "medium",
    effort_execute: "medium",
    effort_verify: "medium",
    effort_correct: "",
  },
};

const SPLIT_DEFAULT_MODELS = {
  allowed: ["gemini-3.1-pro-preview", "claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-5"],
  effort: {
    "gemini-3.1-pro-preview": ["low", "medium", "high"],
    "claude-opus-4-6": ["low", "medium", "high", "max"],
    "claude-sonnet-4-6": ["low", "medium", "high", "max"],
    "claude-opus-5": ["low", "medium", "high", "xhigh", "max"],
  },
  defaults: {
    plan: "claude-opus-4-6",
    execute: "gemini-3.1-pro-preview",
    verify: "claude-opus-4-6",
    correct: "",
    effort_plan: "high",
    effort_execute: "high",
    effort_verify: "high",
    effort_correct: "",
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(MATH_SCHEMA);
  getAvailableModelsMock.mockResolvedValue(MODELS_WITH_EFFORT);
});

describe("ParamForm — effort-tier selection", () => {
  it.each([
    ["high", "high"],
    ["low", "medium"],
  ])("opens and submits untouched efforts from server defaults (%s, %s)", async (plan, execute) => {
    getAvailableModelsMock.mockResolvedValue({
      ...SPLIT_DEFAULT_MODELS,
      defaults: { ...SPLIT_DEFAULT_MODELS.defaults, effort_plan: plan, effort_execute: execute },
    });
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);

    expect(await screen.findByLabelText("Planning effort")).toHaveValue(plan);
    expect(screen.getByLabelText("Execution effort")).toHaveValue(execute);
    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ effort_plan: plan, effort_execute: execute });
  });

  it("keeps saved low efforts when the server advertises high", async () => {
    window.localStorage.setItem("effort_plan", "low");
    window.localStorage.setItem("effort_execute", "low");
    getAvailableModelsMock.mockResolvedValue(SPLIT_DEFAULT_MODELS);
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);

    expect(await screen.findByLabelText("Planning effort")).toHaveValue("low");
    expect(screen.getByLabelText("Execution effort")).toHaveValue("low");
    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ effort_plan: "low", effort_execute: "low" });
  });

  it("shows the advertised split and roster in the default model options", async () => {
    getAvailableModelsMock.mockResolvedValue(SPLIT_DEFAULT_MODELS);
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

    const plan = await screen.findByLabelText("Planner model") as HTMLSelectElement;
    const execute = screen.getByLabelText("Execution model") as HTMLSelectElement;
    const verify = screen.getByLabelText("Verification model") as HTMLSelectElement;
    const verifyEffort = screen.getByLabelText("Verification effort") as HTMLSelectElement;
    expect(plan.selectedOptions[0]).toHaveTextContent("(claude-opus-4-6)");
    expect(execute.selectedOptions[0]).toHaveTextContent("(gemini-3.1-pro-preview)");
    expect(verify.selectedOptions[0]).toHaveTextContent("(claude-opus-4-6)");
    expect(verifyEffort.selectedOptions[0]).toHaveTextContent("(high)");
    for (const select of [plan, execute, verify]) {
      expect(Array.from(select.options).map((option) => option.value)).toEqual([
        "", "gemini-3.1-pro-preview", "claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-5",
      ]);
    }
  });

  describe("options filtered per model", () => {
    it("plan effort dropdown shows xhigh when plan model is claude-opus-4-6", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const planModelSelect = await screen.findByLabelText("Planner model");
      await user.selectOptions(planModelSelect, "claude-opus-4-6");
      const planEffortSelect = screen.getByLabelText("Planning effort");
      const options = Array.from(
        planEffortSelect.querySelectorAll("option"),
      ).map((o) => (o as HTMLOptionElement).value);
      expect(options).toContain("xhigh");
    });

    it("execute effort dropdown does NOT show xhigh when execute model is claude-sonnet-4-6", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const execModelSelect = await screen.findByLabelText("Execution model");
      await user.selectOptions(execModelSelect, "claude-sonnet-4-6");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      const options = Array.from(
        execEffortSelect.querySelectorAll("option"),
      ).map((o) => (o as HTMLOptionElement).value);
      expect(options).not.toContain("xhigh");
      expect(options).toContain("max");
    });
  });

  describe("reconcile on model change", () => {
    it("effort_execute falls back to medium when switching from opus to sonnet with xhigh selected", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);

      // Set execute model to opus (which supports xhigh)
      const execModelSelect = await screen.findByLabelText("Execution model");
      await user.selectOptions(execModelSelect, "claude-opus-4-6");

      // Select xhigh for effort
      const execEffortSelect = screen.getByLabelText("Execution effort");
      await user.selectOptions(execEffortSelect, "xhigh");
      expect((execEffortSelect as HTMLSelectElement).value).toBe("xhigh");

      // Switch execute model to sonnet (which doesn't support xhigh)
      await user.selectOptions(execModelSelect, "claude-sonnet-4-6");

      // effort_execute should fall back to medium
      expect((execEffortSelect as HTMLSelectElement).value).toBe("medium");
    });
  });

  describe("localStorage persistence round-trip", () => {
    it("persists effort_plan and effort_execute to localStorage when selected", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const planEffortSelect = await screen.findByLabelText("Planning effort");
      await user.selectOptions(planEffortSelect, "high");
      expect(window.localStorage.getItem("effort_plan")).toBe("high");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      await user.selectOptions(execEffortSelect, "max");
      expect(window.localStorage.getItem("effort_execute")).toBe("max");
    });

    it("hydrates effortPlan and effortExecute from localStorage on mount", async () => {
      window.localStorage.setItem("effort_plan", "high");
      window.localStorage.setItem("effort_execute", "max");
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const planEffortSelect = await screen.findByLabelText("Planning effort");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      expect((planEffortSelect as HTMLSelectElement).value).toBe("high");
      expect((execEffortSelect as HTMLSelectElement).value).toBe("max");
    });
  });

  describe("discovery failure", () => {
    it("hides effort dropdowns when /api/models fails", async () => {
      getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
      await waitFor(() => {
        expect(screen.queryByLabelText("Planning effort")).toBeNull();
        expect(screen.queryByLabelText("Execution effort")).toBeNull();
      });
    });

    it("does not send effort_plan/effort_execute when /api/models fails", async () => {
      window.localStorage.setItem("effort_plan", "high");
      window.localStorage.setItem("effort_execute", "max");
      getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));
      const onSubmit = vi.fn();
      render(
        <ParamForm subject="math" onSubmit={onSubmit} disabled={false} />,
      );
      await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
      await waitFor(() => {
        expect(screen.queryByLabelText("Planning effort")).toBeNull();
      });
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_plan).toBeUndefined();
      expect(submitted.effort_execute).toBeUndefined();
    });
  });

  describe("confirmation screen rows", () => {
    it("shows Planning effort and Execution effort rows with selected values (en-US)", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={vi.fn()} disabled={false} />);
      const planEffortSelect = await screen.findByLabelText("Planning effort");
      await user.selectOptions(planEffortSelect, "high");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      await user.selectOptions(execEffortSelect, "max");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await screen.findByRole("heading", { name: /review settings/i });
      expect(
        screen.getByText("Planning effort", { selector: "dt" }),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Execution effort", { selector: "dt" }),
      ).toBeInTheDocument();
    });
  });

  describe("generate request params", () => {
    it("sends effort_plan and effort_execute in onSubmit payload", async () => {
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(
        <ParamForm subject="math" onSubmit={onSubmit} disabled={false} />,
      );
      const planEffortSelect = await screen.findByLabelText("Planning effort");
      await user.selectOptions(planEffortSelect, "high");
      const execEffortSelect = screen.getByLabelText("Execution effort");
      await user.selectOptions(execEffortSelect, "max");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_plan).toBe("high");
      expect(submitted.effort_execute).toBe("max");
    });

    it("defaults effort_plan and effort_execute to medium when nothing set", async () => {
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(
        <ParamForm subject="math" onSubmit={onSubmit} disabled={false} />,
      );
      // Don't change effort dropdowns — should send "medium"
      await screen.findByLabelText("Planning effort");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_plan).toBe("medium");
      expect(submitted.effort_execute).toBe("medium");
    });
  });
});

describe("ParamForm — verify/correct effort-tier selection", () => {
  describe("default state", () => {
    it("does not send effort_verify or effort_correct when left at inherit", async () => {
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
      await screen.findByLabelText("Verification effort");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_verify).toBeUndefined();
      expect(submitted.effort_correct).toBeUndefined();
    });

    it("defaults effort_verify and effort_correct to '' (inherit) on first load", async () => {
      window.localStorage.clear();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const verifySelect = await screen.findByLabelText("Verification effort");
      const correctSelect = screen.getByLabelText("Correction effort");
      expect((verifySelect as HTMLSelectElement).value).toBe("");
      expect((correctSelect as HTMLSelectElement).value).toBe("");
    });
  });

  describe("selecting a level", () => {
    it("sends effort_verify when a level is selected", async () => {
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
      const verifySelect = await screen.findByLabelText("Verification effort");
      await user.selectOptions(verifySelect, "high");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_verify).toBe("high");
    });

    it("sends effort_correct when a level is selected", async () => {
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
      const correctSelect = await screen.findByLabelText("Correction effort");
      await user.selectOptions(correctSelect, "low");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_correct).toBe("low");
    });

    it("stops sending effort_verify when reset to inherit", async () => {
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
      const verifySelect = await screen.findByLabelText("Verification effort");
      await user.selectOptions(verifySelect, "high");
      await user.selectOptions(verifySelect, "");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_verify).toBeUndefined();
    });
  });

  describe("localStorage persistence", () => {
    it("persists effort_verify and effort_correct to localStorage under correct keys", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const verifySelect = await screen.findByLabelText("Verification effort");
      await user.selectOptions(verifySelect, "max");
      expect(window.localStorage.getItem("effort_verify")).toBe("max");
      const correctSelect = screen.getByLabelText("Correction effort");
      await user.selectOptions(correctSelect, "low");
      expect(window.localStorage.getItem("effort_correct")).toBe("low");
    });

    it("hydrates effortVerify and effortCorrect from localStorage on remount", async () => {
      window.localStorage.setItem("effort_verify", "high");
      window.localStorage.setItem("effort_correct", "low");
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const verifySelect = await screen.findByLabelText("Verification effort");
      const correctSelect = screen.getByLabelText("Correction effort");
      expect((verifySelect as HTMLSelectElement).value).toBe("high");
      expect((correctSelect as HTMLSelectElement).value).toBe("low");
    });
  });

  describe("effective model determines offered levels", () => {
    it("verify effort offers levels of the effective model when modelVerify is set", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const verifyModelSelect = await screen.findByLabelText("Verification model");
      // Set modelVerify to opus (which supports xhigh)
      await user.selectOptions(verifyModelSelect, "claude-opus-4-6");
      const verifyEffortSelect = screen.getByLabelText("Verification effort");
      const options = Array.from(verifyEffortSelect.querySelectorAll("option")).map(
        (o) => (o as HTMLOptionElement).value,
      );
      expect(options).toContain("xhigh");
    });

    it("verify effort follows execute model levels when modelVerify is not set", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      // Set execute model to sonnet (no xhigh), leave verify unset
      const execModelSelect = await screen.findByLabelText("Execution model");
      await user.selectOptions(execModelSelect, "claude-sonnet-4-6");
      const verifyEffortSelect = screen.getByLabelText("Verification effort");
      const options = Array.from(verifyEffortSelect.querySelectorAll("option")).map(
        (o) => (o as HTMLOptionElement).value,
      );
      expect(options).not.toContain("xhigh");
      expect(options).toContain("max");
    });
  });

  describe("model change resets effort to inherit when level unavailable", () => {
    it("resets effortVerify to inherit when switching to a model that lacks the selected level", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const verifyModelSelect = await screen.findByLabelText("Verification model");
      // Switch verify model to opus (supports xhigh)
      await user.selectOptions(verifyModelSelect, "claude-opus-4-6");
      const verifyEffortSelect = screen.getByLabelText("Verification effort");
      await user.selectOptions(verifyEffortSelect, "xhigh");
      expect((verifyEffortSelect as HTMLSelectElement).value).toBe("xhigh");
      // Switch verify model to sonnet (no xhigh) — effort should reset to ""
      await user.selectOptions(verifyModelSelect, "claude-sonnet-4-6");
      expect((verifyEffortSelect as HTMLSelectElement).value).toBe("");
    });
  });

  describe("discovery failure", () => {
    it("hides verify/correct effort selects when /api/models fails", async () => {
      getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
      await waitFor(() => {
        expect(screen.queryByLabelText("Verification effort")).toBeNull();
        expect(screen.queryByLabelText("Correction effort")).toBeNull();
      });
    });

    it("does not send effort_verify/effort_correct when /api/models fails", async () => {
      window.localStorage.setItem("effort_verify", "high");
      window.localStorage.setItem("effort_correct", "low");
      getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));
      const onSubmit = vi.fn();
      render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
      await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
      await waitFor(() => {
        expect(screen.queryByLabelText("Verification effort")).toBeNull();
      });
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.effort_verify).toBeUndefined();
      expect(submitted.effort_correct).toBeUndefined();
    });
  });

  describe("labels and i18n", () => {
    it("shows 'Verification effort' and 'Correction effort' labels (en-US)", async () => {
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      expect(await screen.findByLabelText("Verification effort")).toBeInTheDocument();
      expect(screen.getByLabelText("Correction effort")).toBeInTheDocument();
    });

    it("shows inherit option with env default in parentheses when defaults.effort_verify is non-empty", async () => {
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const verifySelect = await screen.findByLabelText("Verification effort");
      const inheritOption = Array.from(verifySelect.querySelectorAll("option")).find(
        (o) => (o as HTMLOptionElement).value === "",
      );
      expect(inheritOption).toBeDefined();
      // defaults.effort_verify = "medium" → should show "(medium)"
      expect(inheritOption!.textContent).toContain("medium");
    });

    it("shows plain inherit option text when defaults.effort_correct is empty", async () => {
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      const correctSelect = await screen.findByLabelText("Correction effort");
      const inheritOption = Array.from(correctSelect.querySelectorAll("option")).find(
        (o) => (o as HTMLOptionElement).value === "",
      );
      expect(inheritOption).toBeDefined();
      // defaults.effort_correct = "" → should NOT show parentheses with a value
      expect(inheritOption!.textContent).not.toMatch(/\(.+\)/);
    });
  });

  describe("confirmation screen rows", () => {
    it("shows Verification effort and Correction effort rows when values are set", async () => {
      const user = userEvent.setup();
      render(<ParamForm subject="math" onSubmit={vi.fn()} disabled={false} />);
      const verifySelect = await screen.findByLabelText("Verification effort");
      await user.selectOptions(verifySelect, "high");
      const correctSelect = screen.getByLabelText("Correction effort");
      await user.selectOptions(correctSelect, "low");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await screen.findByRole("heading", { name: /review settings/i });
      expect(
        screen.getByText("Verification effort", { selector: "dt" }),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Correction effort", { selector: "dt" }),
      ).toBeInTheDocument();
    });
  });
});
