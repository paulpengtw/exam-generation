import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const REQUEST_LEVEL_FIELDS = [
  "count",
  "subject",
  "per_question_params",
  "max_retries",
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
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "3" } });
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
});
