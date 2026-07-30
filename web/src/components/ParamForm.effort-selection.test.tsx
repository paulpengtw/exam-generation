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
    effort_plan: "medium",
    effort_execute: "medium",
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(MATH_SCHEMA);
  getAvailableModelsMock.mockResolvedValue(MODELS_WITH_EFFORT);
});

describe("ParamForm — effort-tier selection", () => {
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
