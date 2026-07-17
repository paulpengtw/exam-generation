import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../api/client", () => ({
  getSchemas: vi.fn(async () => ({
    grades: [7, 8, 9],
    情境: [{ value: "個人" }, { value: "公共" }],
    情境子類別: [],
    題型種類: [{ value: "題組題" }],
    題型: [
      { value: "選擇題" },
      { value: "封閉式建構反應題" },
      { value: "開放式建構反應題" },
    ],
    題目內容類型: [{ value: "純文字" }],
    科目: [{ value: "歷史" }, { value: "地理" }, { value: "公民與社會" }, { value: "跨科" }],
    學習表現: [],
    學習內容: [],
    question_style: [],
  })),
  getAvailableModels: vi.fn(async () => ({ allowed: [], defaults: { plan: "", execute: "" } })),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

import ParamForm, { type GenerateParams } from "./ParamForm";

describe("ParamForm coverage_mode dropdown", () => {
  beforeEach(() => vi.clearAllMocks());

  it("defaults coverage_mode to 'balanced' on submit", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="social_studies" onSubmit={(p) => submitted.push(p)} disabled={false} />,
    );

    // Wait for schema-driven state to hydrate.
    await waitFor(() =>
      expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByText("form.btn_generate"));
    // Advance past the confirm step.
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].coverage_mode).toBe("balanced");
  });

  it("sends coverage_mode='random' when the operator picks 隨機", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="social_studies" onSubmit={(p) => submitted.push(p)} disabled={false} />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("form.coverage_mode"), {
      target: { value: "random" },
    });
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].coverage_mode).toBe("random");
  });
});
