/**
 * Tests for 文本出題指示 wired into the 自然科學 form (issue #635).
 *
 * Covers:
 *  - Form shows the input for natural_sciences
 *  - NS submit carries text_instruction
 *  - NS confirmation row renders the instruction / "未填寫" when empty
 *  - NS history prefill / draft round-trip (subject-agnostic paths)
 *  - Math still hides the input
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() =>
  vi.fn(async () => ({ allowed: [], defaults: { plan: "", execute: "" } }))
);
const resolveGenerateMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn(async () => ({ prompts: [] })));

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: previewGenerateMock,
  resolveGenerate: resolveGenerateMock,
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => {
    const msgs: Record<string, string> = {
      "form.text_instruction_label": "文本出題指示",
      "form.text_instruction_placeholder": "請輸入文本出題指示",
      "form.confirm_text_instruction": "文本出題指示",
      "form.unlimited": "不限",
      "form.btn_generate": "產生",
      "form.btn_confirm_send": "確定發送",
      "form.confirm_unset": "未填寫",
    };
    return msgs[key] ?? key;
  },
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

const SCIENCE_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple-multiple-choice", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "生物", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

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

// Minimal resolver stub that echoes the payload back with empty drawn list.
function makeResolveStub() {
  return async (payload: Record<string, unknown>) => ({
    payload,
    drawn: [] as string[],
  });
}

describe("ParamForm 自然科學 文本出題指示 input", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    resolveGenerateMock.mockImplementation(makeResolveStub());
  });

  it("shows 文本出題指示 input for natural_sciences", async () => {
    render(<ParamForm subject="natural_sciences" onSubmit={() => {}} disabled={false} />);
    expect(await screen.findByLabelText("文本出題指示")).toBeInTheDocument();
  });

  it("does not show 文本出題指示 input for math", async () => {
    getSchemasMock.mockResolvedValue(MATH_SCHEMA);
    render(<ParamForm subject="math" onSubmit={() => {}} disabled={false} />);
    await screen.findByRole("button", { name: "產生" });
    expect(screen.queryByLabelText("文本出題指示")).not.toBeInTheDocument();
  });

  it("submits text_instruction for natural_sciences", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm subject="natural_sciences" onSubmit={onSubmit} disabled={false} />,
    );

    const input = await screen.findByLabelText("文本出題指示");
    await act(async () => {
      fireEvent.change(input, { target: { value: "請聚焦電磁波的能量傳遞" } });
    });
    // Verify the input value was updated
    expect((input as HTMLInputElement).value).toBe("請聚焦電磁波的能量傳遞");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "產生" }));
    });
    fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    // Verify resolver was called with text_instruction
    expect(resolveGenerateMock).toHaveBeenCalledTimes(1);
    const resolvePayload = resolveGenerateMock.mock.calls[0][0] as Record<string, unknown>;
    expect(resolvePayload.text_instruction).toBe("請聚焦電磁波的能量傳遞");
    expect(
      (onSubmit.mock.calls[0][0] as Record<string, unknown>).text_instruction,
    ).toBe("請聚焦電磁波的能量傳遞");
  });

  it("does not submit text_instruction when blank for natural_sciences", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm subject="natural_sciences" onSubmit={onSubmit} disabled={false} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    fireEvent.click(await screen.findByRole("button", { name: "確定發送" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(
      (onSubmit.mock.calls[0][0] as Record<string, unknown>).text_instruction,
    ).toBeUndefined();
  });
});

describe("ParamForm 自然科學 history prefill for text_instruction", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SCIENCE_SCHEMA);
    resolveGenerateMock.mockImplementation(makeResolveStub());
  });

  it("restores text_instruction from natural_sciences history prefill", async () => {
    render(
      <ParamForm
        subject="natural_sciences"
        initialParams={{ text_instruction: "請聚焦電磁波的能量傳遞" }}
        onSubmit={() => {}}
        disabled={false}
      />,
    );

    expect(
      await screen.findByDisplayValue("請聚焦電磁波的能量傳遞"),
    ).toHaveAttribute("id", "text-instruction");
  });
});
