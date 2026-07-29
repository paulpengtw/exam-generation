import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));

import { useLangStore } from "../store/langStore";
import { useAuthStore } from "../store/authStore";
import ParamForm from "./ParamForm";

const MATH_SCHEMA = {
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
};

const DRAFT_KEY = "exam_form_draft_teacher-1";

function signIn(): void {
  useAuthStore.getState().login("token", {
    id: "teacher-1",
    email: "teacher@example.com",
    created_at: "2026-01-01T00:00:00.000Z",
  });
}

async function renderForm(): Promise<HTMLInputElement> {
  render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
  await screen.findByRole("button", { name: "產生" });
  return screen.getByPlaceholderText(
    "例如：氣候變遷與都市規劃",
  ) as HTMLInputElement;
}

describe("ParamForm draft persistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useAuthStore.setState({ token: null, user: null });
    useLangStore.setState({ lang: "zh-TW" });
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    signIn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("persists a typed field for the signed-in user after one second", async () => {
    const topicInput = await renderForm();
    vi.useFakeTimers();

    fireEvent.change(topicInput, { target: { value: "臺灣河川" } });
    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });

    const stored = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null") as {
      fields: { topic: string };
    };
    expect(stored.fields.topic).toBe("臺灣河川");
  });

  it("does not persist an untouched form", async () => {
    await renderForm();
    vi.useFakeTimers();

    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });

    expect(localStorage.getItem(DRAFT_KEY)).toBeNull();
  });

  it("coalesces multiple keystrokes within one second into one draft save", async () => {
    const topicInput = await renderForm();
    const setItemSpy = vi.spyOn(localStorage, "setItem");
    vi.useFakeTimers();

    fireEvent.change(topicInput, { target: { value: "臺" } });
    act(() => vi.advanceTimersByTime(400));
    fireEvent.change(topicInput, { target: { value: "臺灣" } });
    act(() => vi.advanceTimersByTime(400));
    fireEvent.change(topicInput, { target: { value: "臺灣史" } });
    act(() => vi.advanceTimersByTime(999));

    expect(
      setItemSpy.mock.calls.filter(([key]) => key === DRAFT_KEY),
    ).toHaveLength(0);

    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    expect(
      setItemSpy.mock.calls.filter(([key]) => key === DRAFT_KEY),
    ).toHaveLength(1);
    const stored = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null") as {
      fields: { topic: string };
    };
    expect(stored.fields.topic).toBe("臺灣史");
  });

  it("does not save when delayed model reconciliation only changes defaults", async () => {
    let resolveModels!: (models: {
      allowed: string[];
      defaults: { plan: string; execute: string };
    }) => void;
    getAvailableModelsMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveModels = resolve;
      }),
    );
    localStorage.setItem("model_plan", "retired-model");
    await renderForm();
    vi.useFakeTimers();

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

  it("still saves user input made while model discovery is pending", async () => {
    let resolveModels!: (models: {
      allowed: string[];
      defaults: { plan: string; execute: string };
    }) => void;
    getAvailableModelsMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveModels = resolve;
      }),
    );
    const topicInput = await renderForm();
    vi.useFakeTimers();
    fireEvent.change(topicInput, { target: { value: "等待模型時輸入" } });

    await act(async () => {
      resolveModels({
        allowed: [],
        defaults: { plan: "", execute: "" },
      });
    });
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });

    const stored = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null") as {
      fields: { topic: string };
    };
    expect(stored.fields.topic).toBe("等待模型時輸入");
  });
});
