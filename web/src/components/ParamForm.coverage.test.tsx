import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("../api/client", () => ({
  getSchemas: vi.fn(async () => ({
    grades: [7, 8, 9],
    情境: [{ value: "個人" }, { value: "公共" }],
    情境子類別: [],
    題型種類: [{ value: "題組題" }],
    題型: [
      { value: "選擇題" },
      { value: "開放式建構反應題" },
    ],
    題目內容類型: [{ value: "純文字" }],
    科目: [{ value: "歷史" }],
    學習表現: [],
    學習內容: [
      { value: "歷Ka-Ⅳ-1", 科目: "歷史", admitted_by: { 科目: ["歷史", "跨科"] } },
      { value: "歷Ka-Ⅳ-2", 科目: "歷史", admitted_by: { 科目: ["歷史", "跨科"] } },
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

  it("釘選s an independently drawn 學習內容 per question for a 均衡 batch", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="social_studies" onSubmit={(p) => submitted.push(p)} disabled={false} />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("form.count"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].learning_content).toBeInstanceOf(Array);
    expect(submitted[0].learning_content!.length).toBeGreaterThanOrEqual(1);
    expect(submitted[0].learning_content!.length).toBeLessThanOrEqual(3);
    expect(submitted[0].learning_content!.every((item) =>
      ["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2"].includes(item))).toBe(true);
    const perQuestion = JSON.parse(submitted[0].per_question_params as string);
    expect(perQuestion).toHaveLength(3);
    for (const item of perQuestion as { learning_content?: string[] }[]) {
      expect(item.learning_content).toBeInstanceOf(Array);
      expect(item.learning_content!.length).toBeGreaterThanOrEqual(1);
      expect(item.learning_content!.length).toBeLessThanOrEqual(3);
      expect(item.learning_content!.every((code) =>
        ["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2"].includes(code))).toBe(true);
    }
  });

  it("shows 預抽'd 學習內容 marked as randomly drawn under 均衡", async () => {
    render(
      <ParamForm subject="social_studies" onSubmit={() => {}} disabled={false} />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText("form.count"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByText("form.btn_generate"));

    await screen.findByText("form.confirm_title");
    expect(screen.queryAllByText("form.confirm_lc_balanced_backend_assignment")).toHaveLength(0);
    expect(await screen.findAllByText("form.confirm_lc_random_pool")).toHaveLength(3);
  });

  it("釘選s a 預抽'd 學習內容 for the default single-question 均衡 request", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="social_studies" onSubmit={(p) => submitted.push(p)} disabled={false} />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("form.coverage_mode")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].learning_content).toBeInstanceOf(Array);
    expect(submitted[0].learning_content!.length).toBeGreaterThanOrEqual(1);
    expect(submitted[0].learning_content!.length).toBeLessThanOrEqual(3);
    expect(submitted[0].learning_content!.every((item) =>
      ["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2"].includes(item))).toBe(true);
    const perQuestion = JSON.parse(submitted[0].per_question_params as string);
    expect(perQuestion).toHaveLength(1);
    expect(perQuestion[0].learning_content).toBeInstanceOf(Array);
    expect(perQuestion[0].learning_content.length).toBeGreaterThanOrEqual(1);
    expect(perQuestion[0].learning_content.length).toBeLessThanOrEqual(3);
    expect(perQuestion[0].learning_content.every((code: string) =>
      ["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2"].includes(code))).toBe(true);
  });

  it("釘選s a 預抽'd 學習內容 under 隨機 too", async () => {
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
    fireEvent.change(screen.getByLabelText("form.count"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByText("form.btn_generate"));
    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].learning_content).toBeInstanceOf(Array);
    expect(submitted[0].learning_content!.length).toBeGreaterThanOrEqual(1);
    expect(submitted[0].learning_content!.length).toBeLessThanOrEqual(3);
    expect(submitted[0].learning_content!.every((item) =>
      ["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2"].includes(item))).toBe(true);
    const perQuestion = JSON.parse(submitted[0].per_question_params as string);
    expect(perQuestion).toHaveLength(3);
    for (const item of perQuestion as { learning_content?: string[] }[]) {
      expect(item.learning_content).toBeInstanceOf(Array);
      expect(item.learning_content!.length).toBeGreaterThanOrEqual(1);
      expect(item.learning_content!.length).toBeLessThanOrEqual(3);
      expect(item.learning_content!.every((code) =>
        ["歷Ka-Ⅳ-1", "歷Ka-Ⅳ-2"].includes(code))).toBe(true);
    }
  });

  it("sends an explicit 學習內容 selection as a 釘選 under 均衡", async () => {
    const submitted: GenerateParams[] = [];
    render(
      <ParamForm subject="social_studies" onSubmit={(p) => submitted.push(p)} disabled={false} />,
    );
    // Switch to checkbox mode (default is search mode)
    fireEvent.click(await screen.findByRole("button", { name: "切換勾選模式" }));
    await screen.findByText("歷Ka-Ⅳ-1");

    fireEvent.click(screen.getByText("歷Ka-Ⅳ-1"));
    fireEvent.click(screen.getByText("form.btn_generate"));

    const learningContentRow = (await screen.findByText("form.confirm_learning_content")).closest("div");
    expect(learningContentRow).not.toBeNull();
    expect(within(learningContentRow!).getByText("form.confirm_lc_selected")).toBeInTheDocument();
    expect(within(learningContentRow!).queryByText("form.confirm_lc_random_pool")).not.toBeInTheDocument();

    fireEvent.click(await screen.findByText("form.btn_confirm_send"));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0].learning_content).toEqual(["歷Ka-Ⅳ-1"]);
  });
});
