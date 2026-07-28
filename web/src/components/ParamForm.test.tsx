import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn(async () => ({ allowed: [], defaults: { plan: "", execute: "" } })));
const tMock = vi.hoisted(() => {
  const messages: Record<string, string> = {
    "history.prefill_notice": "Some saved parameters are no longer available in the current schema.",
    "form.grade": "Grade",
    "form.difficulty": "Difficulty",
    "form.btn_generate": "Generate",
    "form.btn_confirm_send": "Confirm",
    "form.error_set_type_required": "題型種類 is required.",
  };
  return (key: string) => messages[key] ?? key;
});
vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
}));
vi.mock("../i18n/useT", () => ({
  useT: () => tMock,
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import ParamForm from "./ParamForm";

const FAKE_MATH_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [
    { value: "個人", instruction: "" },
    { value: "社會時事", instruction: "" },
  ],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "textbook", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

describe("ParamForm difficulty dropdown", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);
  });

  it("does not send `difficulty` when left at the default option", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);

    // Wait for schemas to load
    await screen.findByRole("button", { name: /generate/i });

    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    // Confirm dialog opens; click confirm.
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [payload] = onSubmit.mock.calls[0];
    expect(payload.difficulty).toBeUndefined();
  });

  it("sends `difficulty` when the user picks hard", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="math" onSubmit={onSubmit} disabled={false} />);
    await screen.findByRole("button", { name: /generate/i });

    const select = screen.getByLabelText(/difficulty/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "hard" } });

    fireEvent.click(screen.getByRole("button", { name: /generate/i }));
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const [payload] = onSubmit.mock.calls[0];
    expect(payload.difficulty).toBe("hard");
  });
});

describe("ParamForm prefill", () => {
  it("initializes visible fields from initialParams", async () => {
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);

    render(
      <ParamForm
        subject="math"
        disabled={false}
        onSubmit={() => {}}
        initialParams={{ grade: 8, topic: "climate change" }}
      />,
    );

    await waitFor(() =>
      expect(screen.getByDisplayValue("climate change")).toBeInTheDocument(),
    );
    expect((screen.getByLabelText(/Grade/i) as HTMLSelectElement).value).toBe("8");
  });

  it("shows the prefill-notice when initialParams contain values not in the current schema", async () => {
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);

    render(
      <ParamForm
        subject="math"
        disabled={false}
        onSubmit={() => {}}
        initialParams={{
          grade: 8,
          context: ["個人", "已刪除情境"],
          set_type: "已刪除設定",
        }}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/Some saved parameters are no longer available/i),
      ).toBeInTheDocument(),
    );
  });

  it("prevents 發送前確認 when history prefill clears 題型種類", async () => {
    const onSubmit = vi.fn();
    getSchemasMock.mockResolvedValue(FAKE_MATH_SCHEMA);

    render(
      <ParamForm
        subject="math"
        disabled={false}
        onSubmit={onSubmit}
        initialParams={{ grade: 8, set_type: "已刪除題型種類" }}
      />,
    );

    await screen.findByText(/Some saved parameters are no longer available/i);
    fireEvent.click(screen.getByRole("button", { name: /generate/i }));

    expect(await screen.findByText(/題型種類.*required/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirm/i })).not.toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
