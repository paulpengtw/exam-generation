import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const REQUEST_LEVEL_FIELDS = [
  "count",
  "subject",
  "per_question_params",
  "max_retries",
  "core_question_callback",
] as const;

vi.mock("../api/client", () => ({
  getSchemas: vi.fn(async () => ({
    學習階段: "第四學習階段",
    grades: [7, 8, 9],
    情境: [{ value: "個人", instruction: "" }],
    題型種類: [{ value: "單一題", instruction: "" }],
    題型: [{ value: "選擇題", instruction: "" }],
    數學思考: [{ value: "形成", instruction: "" }],
    question_style: [{ value: "課本", instruction: "" }],
    題目內容類型: [{ value: "純文字", instruction: "" }],
    科目: [{ value: "數與量", instruction: "" }],
    學習表現: [],
    學習內容: [],
  })),
  getAvailableModels: vi.fn(async () => ({
    allowed: [],
    defaults: { plan: "", execute: "" },
  })),
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

import ParamForm, { type FormParams } from "./ParamForm";

describe("ParamForm per-question request contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("keeps request-level fields out of every per-question parameter object", async () => {
    const submitted: FormParams[] = [];
    render(
      <ParamForm subject="math" onSubmit={(params) => submitted.push(params)} disabled={false} />,
    );

    await screen.findByText("form.btn_generate");
    const countInput = screen.getByLabelText("form.count");
    fireEvent.change(countInput, { target: { value: "3" } });
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].count).toBe(3);
    const perQuestion = JSON.parse(
      submitted[0].per_question_params as string,
    ) as Record<string, unknown>[];
    expect(perQuestion).toHaveLength(3);
    for (const item of perQuestion) {
      for (const field of REQUEST_LEVEL_FIELDS) {
        expect(item).not.toHaveProperty(field);
      }
    }
  });

  it.each(["social_studies", "natural_sciences"] as const)(
    "shows the pre-checked core-question callback checkbox for %s",
    async (subject) => {
      render(
        <ParamForm subject={subject} onSubmit={() => {}} disabled={false} />,
      );

      const checkbox = await screen.findByRole("checkbox", {
        name: "form.core_question_callback",
      });
      expect(checkbox).toBeChecked();
    },
  );

  it("sends true for the checked social-studies callback option", async () => {
    const submitted: FormParams[] = [];
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={(params) => submitted.push(params)}
        disabled={false}
      />,
    );

    await screen.findByRole("checkbox", {
      name: "form.core_question_callback",
    });
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].core_question_callback).toBe(true);
  });

  it("sends false when the natural-sciences callback option is unchecked", async () => {
    const submitted: FormParams[] = [];
    render(
      <ParamForm
        subject="natural_sciences"
        onSubmit={(params) => submitted.push(params)}
        disabled={false}
      />,
    );

    const checkbox = await screen.findByRole("checkbox", {
      name: "form.core_question_callback",
    });
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].core_question_callback).toBe(false);
  });

  it("does not render or send the callback option for math", async () => {
    const submitted: FormParams[] = [];
    render(
      <ParamForm
        subject="math"
        onSubmit={(params) => submitted.push(params)}
        disabled={false}
        initialParams={{ core_question_callback: true }}
      />,
    );

    await screen.findByText("form.btn_generate");
    expect(
      screen.queryByRole("checkbox", { name: "form.core_question_callback" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0]).not.toHaveProperty("core_question_callback");
  });
});
