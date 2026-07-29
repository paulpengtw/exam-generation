import { render, screen, waitFor } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

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

import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import ParamForm from "./ParamForm";

const DRAFT_KEY = "exam_form_draft_teacher-1";

describe("ParamForm route prefill draft behavior", () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    useLangStore.setState({ lang: "zh-TW" });
    useAuthStore.getState().login("token", {
      id: "teacher-1",
      email: "teacher@example.com",
      created_at: "2026-01-01T00:00:00.000Z",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("treats route-prefilled fields as dirty and saves them after the debounce", async () => {
    render(
      <ParamForm
        subject="math"
        initialParams={{ topic: "紀錄帶入的主題", count: 4 }}
        onSubmit={() => {}}
        disabled={false}
      />,
    );
    await screen.findByDisplayValue("紀錄帶入的主題");
    await waitFor(
      () => expect(localStorage.getItem(DRAFT_KEY)).not.toBeNull(),
      { timeout: 1_500 },
    );

    const stored = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null") as {
      fields: { topic: string; count: number };
    };
    expect(stored.fields).toMatchObject({
      topic: "紀錄帶入的主題",
      count: 4,
    });
  });
});
