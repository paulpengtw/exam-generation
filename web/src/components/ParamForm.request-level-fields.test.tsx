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
  resolveGenerate: vi.fn(async (payload: Record<string, unknown>) => {
    const rawRows = payload.per_question_params;
    const rows = typeof rawRows === "string"
      ? JSON.parse(rawRows) as Record<string, unknown>[]
      : [];
    const resolvedRows = rows.map((row) => ({
      ...row,
      ...(payload.core_competency !== undefined
        ? { core_competency: payload.core_competency }
        : {}),
      ...(payload.math_thinking !== undefined
        ? { math_thinking: payload.math_thinking }
        : {}),
    }));
    return {
      payload: {
        ...payload,
        per_question_params: JSON.stringify(resolvedRows),
      },
      drawn: [],
    };
  }),
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

  it("forwards resolved competency and math thinking pins without form controls", async () => {
    const submitted: FormParams[] = [];
    const { container } = render(
      <ParamForm
        subject="math"
        onSubmit={(params) => submitted.push(params)}
        disabled={false}
        initialParams={{
          core_competency: ["數-J-A2"],
          math_thinking: ["運用"],
        }}
      />,
    );

    await screen.findByText("form.btn_generate");
    expect(screen.queryByLabelText("form.core_competency")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("form.math_thinking")).not.toBeInTheDocument();
    for (const control of container.querySelectorAll("input, select, textarea")) {
      expect(["core_competency", "math_thinking"]).not.toContain(control.getAttribute("name"));
    }

    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].core_competency).toEqual(["數-J-A2"]);
    expect(submitted[0].math_thinking).toEqual(["運用"]);
    expect(JSON.parse(submitted[0].per_question_params as string)[0]).toEqual(
      expect.objectContaining({
        core_competency: ["數-J-A2"],
        math_thinking: ["運用"],
      }),
    );
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
