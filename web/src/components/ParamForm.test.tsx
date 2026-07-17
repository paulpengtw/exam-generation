import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("../api/client", () => ({
  getSchemas: () =>
    Promise.resolve({
      學習階段: "第四學習階段",
      grades: [7, 8, 9],
      情境: [{ value: "個人", instruction: "" }],
      題型種類: [{ value: "單一題", instruction: "" }],
      題型: [{ value: "選擇題", instruction: "" }],
      數學思考: [{ value: "形成", instruction: "" }],
      question_style: [{ value: "text_only", instruction: "" }],
      題目內容類型: [{ value: "純文字", instruction: "" }],
    }),
}));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

import ParamForm from "./ParamForm";

describe("ParamForm difficulty dropdown", () => {
  beforeEach(() => vi.clearAllMocks());

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
