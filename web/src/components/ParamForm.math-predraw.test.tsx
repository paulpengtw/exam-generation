import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const resolveGenerateMock = vi.hoisted(() => vi.fn());

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
    學習表現: [{
      value: "RESOLVER-LP",
      instruction: "resolver performance",
      科目: "數與量",
      admitted_by: { 科目: ["數與量"] },
    }],
    學習內容: [{
      value: "RESOLVER-LC",
      instruction: "resolver content",
      科目: "數與量",
      admitted_by: { 科目: ["數與量"] },
    }],
  })),
  getAvailableModels: vi.fn(async () => ({
    allowed: [],
    defaults: { plan: "", execute: "" },
  })),
  planCoreQuestions: vi.fn(async () => ({ candidates: [] })),
  previewGenerate: vi.fn(async () => ({ prompts: [] })),
  resolveGenerate: resolveGenerateMock,
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

import ParamForm from "./ParamForm";

describe("ParamForm resolver-backed confirmation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    resolveGenerateMock.mockResolvedValue({ payload: {}, drawn: [] });
  });

  it("shows resolver values for blank curriculum fields and submits that exact confirmed payload", async () => {
    const onSubmit = vi.fn();
    const resolvedPayload = {
      subject: "math",
      grade: 7,
      count: 1,
      learning_content: ["RESOLVER-LC"],
      learning_performance: ["RESOLVER-LP"],
      per_question_params: JSON.stringify([{
        seed: 812,
        learning_content: ["RESOLVER-LC"],
        learning_performance: ["RESOLVER-LP"],
      }]),
    };
    const drawn = [
      "learning_content",
      "learning_performance",
      "per_question_params[0].learning_content",
      "per_question_params[0].learning_performance",
      "per_question_params[0].seed",
    ];
    resolveGenerateMock.mockResolvedValueOnce({ payload: resolvedPayload, drawn });

    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ core_question: "固定核心問題" }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "form.btn_generate" }));

    await screen.findByText("RESOLVER-LC");
    expect(screen.getByText("RESOLVER-LP")).toBeInTheDocument();
    expect(resolveGenerateMock).toHaveBeenCalledTimes(1);
    expect(resolveGenerateMock.mock.calls[0][1]).toEqual({});

    fireEvent.click(screen.getByRole("button", { name: "form.btn_confirm_send" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toEqual(expect.objectContaining({
      ...resolvedPayload,
      drawn,
    }));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty("predrawn_fields");
  });

  it("keeps the resolver pending state visible and offers retry after a resolver error", async () => {
    let reject!: (reason: Error) => void;
    const pending = new Promise<never>((_resolve, rejectPromise) => {
      reject = rejectPromise;
    });
    resolveGenerateMock.mockReset();
    resolveGenerateMock.mockReturnValueOnce(pending);

    render(<ParamForm subject="math" onSubmit={vi.fn()} disabled={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "form.btn_generate" }));
    expect(screen.getByRole("status")).toHaveTextContent("form.confirm_resolve_loading");

    reject(new Error("resolver unavailable"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("resolver unavailable"));
    expect(screen.getByRole("button", { name: "form.confirm_resolve_retry" })).toBeInTheDocument();
  });
});
