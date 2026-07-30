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

const SCIENCE_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple-multiple-choice", instruction: "" }],
  數學思考: [],
  question_style: [],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [],
  科學能力: [{ value: "能力一", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

const NO_MODELS = { allowed: [], defaults: { plan: "", execute: "" } };

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(MATH_SCHEMA);
  getAvailableModelsMock.mockResolvedValue(NO_MODELS);
});

describe("ParamForm — Reporting Scale selection (自然科學)", () => {
  // ── Slice 1: control visibility ─────────────────────────────────────────────
  describe("control visibility", () => {
    it("renders Reporting Scale select for natural_sciences, no Difficulty", async () => {
      getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
      render(<ParamForm subject="natural_sciences" onSubmit={() => {}} disabled={false} />);
      await screen.findByLabelText("Reporting Scale");
      expect(screen.queryByLabelText("Difficulty")).not.toBeInTheDocument();
    });

    it("renders Difficulty select for math, no Reporting Scale 題組-level control", async () => {
      render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
      await screen.findByLabelText("Difficulty");
      expect(screen.queryByLabelText("Reporting Scale")).not.toBeInTheDocument();
    });
  });

  // ── Slice 3: no reporting_scale when left at random ─────────────────────────
  describe("generate request params", () => {
    it("sends no reporting_scale when left at random for natural_sciences", async () => {
      getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(<ParamForm subject="natural_sciences" onSubmit={onSubmit} disabled={false} />);
      await screen.findByLabelText("Reporting Scale");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.reporting_scale).toBeUndefined();
    });

    // ── Slice 4: set level 4 ────────────────────────────────────────────────
    it("sends reporting_scale '4' and no difficulty when level 4 is selected for natural_sciences", async () => {
      getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
      const onSubmit = vi.fn();
      const user = userEvent.setup();
      render(<ParamForm subject="natural_sciences" onSubmit={onSubmit} disabled={false} />);
      const select = await screen.findByLabelText("Reporting Scale");
      await user.selectOptions(select, "4");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await user.click(await screen.findByRole("button", { name: /confirm/i }));
      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      const submitted = onSubmit.mock.calls[0][0] as Record<string, unknown>;
      expect(submitted.reporting_scale).toBe("4");
      expect(submitted.difficulty).toBeUndefined();
    });
  });

  // ── Slice 5: 発送前確認 shows Reporting Scale row ──────────────────────────
  describe("confirmation screen", () => {
    it("shows Reporting Scale row, no Difficulty row in confirmation for natural_sciences", async () => {
      getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
      const user = userEvent.setup();
      render(<ParamForm subject="natural_sciences" onSubmit={vi.fn()} disabled={false} />);
      await screen.findByLabelText("Reporting Scale");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await screen.findByRole("heading", { name: /review settings/i });
      expect(screen.getByText("Reporting Scale", { selector: "dt" })).toBeInTheDocument();
      expect(screen.queryByText("Difficulty", { selector: "dt" })).not.toBeInTheDocument();
    });

    it("prints selected level in confirmation when a level is set", async () => {
      getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
      const user = userEvent.setup();
      render(<ParamForm subject="natural_sciences" onSubmit={vi.fn()} disabled={false} />);
      const select = await screen.findByLabelText("Reporting Scale");
      await user.selectOptions(select, "4");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await screen.findByRole("heading", { name: /review settings/i });
      const dt = screen.getByText("Reporting Scale", { selector: "dt" });
      expect(dt.parentElement).toHaveTextContent("4");
    });

    it("prints (random) in confirmation when Reporting Scale is unset", async () => {
      getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
      const user = userEvent.setup();
      render(<ParamForm subject="natural_sciences" onSubmit={vi.fn()} disabled={false} />);
      await screen.findByLabelText("Reporting Scale");
      await user.click(screen.getByRole("button", { name: /generate/i }));
      await screen.findByRole("heading", { name: /review settings/i });
      const dt = screen.getByText("Reporting Scale", { selector: "dt" });
      expect(dt.parentElement).toHaveTextContent("(random)");
    });
  });
});
