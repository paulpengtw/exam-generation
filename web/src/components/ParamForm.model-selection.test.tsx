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
  planCoreQuestions: vi.fn(),
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

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(MATH_SCHEMA);
  getAvailableModelsMock.mockResolvedValue({
    allowed: ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6"],
    defaults: { plan: "claude-opus-4-6", execute: "claude-sonnet-4-6" },
  });
});

describe("ParamForm — model selection dropdowns", () => {
  it("renders two selects populated from /api/models", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    const planSelect = await screen.findByLabelText("Planner model");
    const execSelect = await screen.findByLabelText("Execution model");
    const planOptions = Array.from(planSelect.querySelectorAll("option")).map(
      (o) => o.value,
    );
    expect(planOptions).toEqual([
      "",
      "claude-opus-4-6",
      "claude-sonnet-4-6",
      "claude-haiku-4-6",
    ]);
    // Both selects start at the "Default" (empty) option.
    expect((planSelect as HTMLSelectElement).value).toBe("");
    expect((execSelect as HTMLSelectElement).value).toBe("");
  });

  it("passes the selected model_plan/model_execute to onSubmit and persists them", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
    await screen.findByLabelText("Planner model");

    const user = userEvent.setup();
    await user.selectOptions(
      screen.getByLabelText("Planner model"),
      "claude-opus-4-6",
    );
    await user.selectOptions(
      screen.getByLabelText("Execution model"),
      "claude-haiku-4-6",
    );

    // ParamForm stages params via a confirmation screen before calling
    // onSubmit: "Generate" only reveals the confirm/back screen, and the
    // confirm button's label is not currently localized to English (a
    // pre-existing i18n gap unrelated to this task), so it is targeted by
    // its actual rendered text here.
    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: "確定發送" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_plan).toBe("claude-opus-4-6");
    expect(submitted.model_execute).toBe("claude-haiku-4-6");

    expect(window.localStorage.getItem("model_plan")).toBe("claude-opus-4-6");
    expect(window.localStorage.getItem("model_execute")).toBe("claude-haiku-4-6");
  });

  it("hides the dropdowns when /api/models fails", async () => {
    getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    // Wait for the schema fetch to resolve so the form is rendered.
    await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
    await waitFor(() => {
      expect(screen.queryByLabelText("Planner model")).toBeNull();
      expect(screen.queryByLabelText("Execution model")).toBeNull();
    });
  });

  it("hydrates from localStorage on mount", async () => {
    window.localStorage.setItem("model_plan", "claude-sonnet-4-6");
    window.localStorage.setItem("model_execute", "claude-haiku-4-6");
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    const planSelect = await screen.findByLabelText("Planner model");
    const execSelect = await screen.findByLabelText("Execution model");
    expect((planSelect as HTMLSelectElement).value).toBe("claude-sonnet-4-6");
    expect((execSelect as HTMLSelectElement).value).toBe("claude-haiku-4-6");
  });

  it("never submits model_plan/model_execute when /api/models fails, even with a persisted selection", async () => {
    window.localStorage.setItem("model_plan", "claude-opus-4-6");
    window.localStorage.setItem("model_execute", "claude-haiku-4-6");
    getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));

    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);

    // Dropdowns must be hidden once discovery fails.
    await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
    await waitFor(() => {
      expect(screen.queryByLabelText("Planner model")).toBeNull();
      expect(screen.queryByLabelText("Execution model")).toBeNull();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: "確定發送" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_plan).toBeUndefined();
    expect(submitted.model_execute).toBeUndefined();
  });

  it("drops a persisted selection that is no longer in the allowlist", async () => {
    window.localStorage.setItem("model_plan", "claude-legacy-model");
    window.localStorage.setItem("model_execute", "claude-sonnet-4-6");

    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);

    const planSelect = await screen.findByLabelText("Planner model");
    const execSelect = await screen.findByLabelText("Execution model");
    // The stale value is reset to "Default"; the still-valid value survives.
    expect((planSelect as HTMLSelectElement).value).toBe("");
    expect((execSelect as HTMLSelectElement).value).toBe("claude-sonnet-4-6");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: "確定發送" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_plan).toBeUndefined();
    expect(submitted.model_execute).toBe("claude-sonnet-4-6");
  });
});
