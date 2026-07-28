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
    學習內容: [
      { value: "歷Ka-Ⅳ-1", 科目: "歷史" },
      { value: "歷Ka-Ⅳ-2", 科目: "歷史" },
    ],
    question_style: [],
  })),
  getAvailableModels: vi.fn(async () => ({ allowed: [], defaults: { plan: "", execute: "" } })),
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
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

  it("does not 釘選 學習內容 for a multi-question 均衡 batch", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="social_studies" onSubmit={(p) => submitted.push(p)} disabled={false} />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getAllByRole("spinbutton")[0], {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].learning_content).toBeUndefined();
    const perQuestion = JSON.parse(submitted[0].per_question_params as string);
    expect(perQuestion).toHaveLength(3);
    expect(perQuestion.every((item: { learning_content?: string[] }) =>
      item.learning_content === undefined)).toBe(true);
  });

  it("states on 發送前確認 that 均衡 assigns 學習內容 per question", async () => {
    render(
      <ParamForm subject="social_studies" onSubmit={() => {}} disabled={false} />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getAllByRole("spinbutton")[0], {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByText("form.btn_generate"));

    expect(
      await screen.findAllByText("form.confirm_lc_balanced_backend_assignment"),
    ).toHaveLength(3);
  });

  it("sends an explicit 學習內容 selection as a 釘選 under 均衡", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="social_studies" onSubmit={(p) => submitted.push(p)} disabled={false} />,
    );
    await screen.findByText("歷Ka-Ⅳ-1");

    fireEvent.click(screen.getByText("歷Ka-Ⅳ-1"));
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].learning_content).toEqual(["歷Ka-Ⅳ-1"]);
  });
});
