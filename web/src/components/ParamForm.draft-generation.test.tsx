import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const getAvailableModelsMock = vi.hoisted(() => vi.fn());

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
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));

import { useAuthStore } from "../store/authStore";
import { useLangStore } from "../store/langStore";
import ParamForm from "./ParamForm";

const DRAFT_KEY = "exam_form_draft_teacher-1";

describe("ParamForm draft generation lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    useLangStore.setState({ lang: "zh-TW" });
    useAuthStore.getState().login("token", {
      id: "teacher-1",
      email: "teacher@example.com",
      created_at: "2026-01-01T00:00:00.000Z",
    });
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("clears the signed-in user's draft when confirmed generation starts", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm subject="math" onSubmit={onSubmit} disabled={false} />,
    );
    await screen.findByRole("button", { name: "產生" });

    vi.useFakeTimers();
    fireEvent.change(screen.getByLabelText("難度"), {
      target: { value: "hard" },
    });
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(localStorage.getItem(DRAFT_KEY)).not.toBeNull();
    vi.useRealTimers();

    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "確定發送" }),
    );

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
  });

  it("cancels a pending draft save when confirmed generation starts", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm subject="math" onSubmit={onSubmit} disabled={false} />,
    );
    await screen.findByRole("button", { name: "產生" });

    vi.useFakeTimers();
    fireEvent.change(screen.getByLabelText("難度"), {
      target: { value: "hard" },
    });
    act(() => vi.advanceTimersByTime(500));

    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
  });

  it("does not recreate a cleared draft when model discovery finishes later", async () => {
    let resolveModels!: (models: {
      allowed: string[];
      defaults: { plan: string; execute: string };
    }) => void;
    getAvailableModelsMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveModels = resolve;
      }),
    );
    render(
      <ParamForm subject="math" onSubmit={() => {}} disabled={false} />,
    );
    await screen.findByRole("button", { name: "產生" });
    vi.useFakeTimers();

    fireEvent.change(screen.getByLabelText("難度"), {
      target: { value: "hard" },
    });
    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    await act(async () => {
      resolveModels({
        allowed: [],
        defaults: { plan: "", execute: "" },
      });
    });
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });

    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
  });
});
