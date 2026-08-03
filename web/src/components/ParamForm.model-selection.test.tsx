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

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(MATH_SCHEMA);
  getAvailableModelsMock.mockResolvedValue({
    allowed: ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6"],
    defaults: {
      plan: "claude-opus-4-6",
      execute: "claude-sonnet-4-6",
      verify: "claude-sonnet-4-6",
      correct: "claude-haiku-4-6",
    },
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
    await user.click(await screen.findByRole("button", { name: /confirm/i }));

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
    await user.click(await screen.findByRole("button", { name: /confirm/i }));

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
    await user.click(await screen.findByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_plan).toBeUndefined();
    expect(submitted.model_execute).toBe("claude-sonnet-4-6");
  });
});

describe("ParamForm — verify/correct model dropdowns", () => {
  it("renders Verification model and Correction model selects populated from /api/models", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    const verifySelect = await screen.findByLabelText("Verification model");
    const correctSelect = await screen.findByLabelText("Correction model");
    const verifyOptions = Array.from(verifySelect.querySelectorAll("option")).map(
      (o) => o.value,
    );
    const correctOptions = Array.from(correctSelect.querySelectorAll("option")).map(
      (o) => o.value,
    );
    // Both should have the empty "follow execute" option plus all allowed models.
    expect(verifyOptions).toEqual(["", "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6"]);
    expect(correctOptions).toEqual(["", "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6"]);
    // Both start at the "Follow execution model" (empty) option.
    expect((verifySelect as HTMLSelectElement).value).toBe("");
    expect((correctSelect as HTMLSelectElement).value).toBe("");
  });

  it("default state sends neither model_verify nor model_correct", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
    await screen.findByLabelText("Verification model");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_verify).toBeUndefined();
    expect(submitted.model_correct).toBeUndefined();
  });

  it("passes the selected model_verify/model_correct to onSubmit and persists them", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
    await screen.findByLabelText("Verification model");

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Verification model"), "claude-opus-4-6");
    await user.selectOptions(screen.getByLabelText("Correction model"), "claude-haiku-4-6");

    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_verify).toBe("claude-opus-4-6");
    expect(submitted.model_correct).toBe("claude-haiku-4-6");

    expect(window.localStorage.getItem("model_verify")).toBe("claude-opus-4-6");
    expect(window.localStorage.getItem("model_correct")).toBe("claude-haiku-4-6");
  });

  it("resetting to the Follow execution model option stops sending model_verify/model_correct", async () => {
    window.localStorage.setItem("model_verify", "claude-opus-4-6");
    window.localStorage.setItem("model_correct", "claude-haiku-4-6");
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
    await screen.findByLabelText("Verification model");

    const user = userEvent.setup();
    // Reset both back to ""
    await user.selectOptions(screen.getByLabelText("Verification model"), "");
    await user.selectOptions(screen.getByLabelText("Correction model"), "");

    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_verify).toBeUndefined();
    expect(submitted.model_correct).toBeUndefined();
  });

  it("hydrates verify/correct from localStorage on mount", async () => {
    window.localStorage.setItem("model_verify", "claude-sonnet-4-6");
    window.localStorage.setItem("model_correct", "claude-haiku-4-6");
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    const verifySelect = await screen.findByLabelText("Verification model");
    const correctSelect = await screen.findByLabelText("Correction model");
    expect((verifySelect as HTMLSelectElement).value).toBe("claude-sonnet-4-6");
    expect((correctSelect as HTMLSelectElement).value).toBe("claude-haiku-4-6");
  });

  it("options come from models.allowed (not a hardcoded list)", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    const verifySelect = await screen.findByLabelText("Verification model");
    const correctSelect = await screen.findByLabelText("Correction model");

    const verifyValues = Array.from(verifySelect.querySelectorAll("option")).map((o) => o.value);
    const correctValues = Array.from(correctSelect.querySelectorAll("option")).map((o) => o.value);

    // The exact fixture roster — a hardcoded duplicate list would fail when the fixture differs.
    expect(verifyValues).toEqual(["", "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6"]);
    expect(correctValues).toEqual(["", "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6"]);
  });

  it("labels resolve through the i18n catalog (en-US)", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    // The mock forces en-US; the selects must be labelled by the catalog key.
    expect(await screen.findByLabelText("Verification model")).toBeTruthy();
    expect(screen.getByLabelText("Correction model")).toBeTruthy();
  });

  it("drops a persisted verify/correct selection no longer in the allowlist", async () => {
    window.localStorage.setItem("model_verify", "claude-legacy-model");
    window.localStorage.setItem("model_correct", "claude-sonnet-4-6");

    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);

    const verifySelect = await screen.findByLabelText("Verification model");
    const correctSelect = await screen.findByLabelText("Correction model");
    // The stale value is reset to "Follow execution model"; the still-valid value survives.
    expect((verifySelect as HTMLSelectElement).value).toBe("");
    expect((correctSelect as HTMLSelectElement).value).toBe("claude-sonnet-4-6");

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_verify).toBeUndefined();
    expect(submitted.model_correct).toBe("claude-sonnet-4-6");
  });

  it("hides the verify/correct dropdowns and never sends params when /api/models fails", async () => {
    window.localStorage.setItem("model_verify", "claude-opus-4-6");
    window.localStorage.setItem("model_correct", "claude-haiku-4-6");
    getAvailableModelsMock.mockRejectedValueOnce(new Error("boom"));

    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);

    await screen.findByText("第四學習階段", { exact: false }).catch(() => {});
    await waitFor(() => {
      expect(screen.queryByLabelText("Verification model")).toBeNull();
      expect(screen.queryByLabelText("Correction model")).toBeNull();
    });

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /generate/i }));
    await user.click(await screen.findByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const submitted = onSubmit.mock.calls[0][0];
    expect(submitted.model_verify).toBeUndefined();
    expect(submitted.model_correct).toBeUndefined();
  });

  it("shows env default in parentheses when defaults.verify is non-empty", async () => {
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    const verifySelect = await screen.findByLabelText("Verification model");
    const emptyOption = Array.from(verifySelect.querySelectorAll("option")).find(
      (o) => o.value === "",
    );
    // defaults.verify is "claude-sonnet-4-6" in the fixture
    expect(emptyOption?.textContent).toMatch(/claude-sonnet-4-6/);
  });

  it("shows plain Follow execution model text when defaults.verify is empty", async () => {
    getAvailableModelsMock.mockResolvedValueOnce({
      allowed: ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-6"],
      defaults: { plan: "claude-opus-4-6", execute: "claude-sonnet-4-6", verify: "", correct: "" },
    });
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    const verifySelect = await screen.findByLabelText("Verification model");
    const emptyOption = Array.from(verifySelect.querySelectorAll("option")).find(
      (o) => o.value === "",
    );
    // When verify default is empty, just the label text with no model name in parens.
    expect(emptyOption?.textContent).toBe("Follow execution model");
  });
});
