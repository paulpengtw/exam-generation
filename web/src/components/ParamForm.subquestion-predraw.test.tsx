import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: vi.fn(),
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (k: string, opts?: Record<string, unknown>) => {
    if (opts && "n" in opts) return `${k}:${String(opts.n)}`;
    return k;
  },
}));

import ParamForm from "./ParamForm";

const NS_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple-multiple-choice", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  question_style: [{ value: "standard", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  學習表現: [
    { value: "tr-IV-1", instruction: "", 科目: "自然科學" },
    { value: "tr-IV-2", instruction: "", 科目: "自然科學" },
    { value: "tr-IV-3", instruction: "", 科目: "自然科學" },
  ],
  學習內容: [
    { value: "INc-IV-1", instruction: "", 科目: "自然科學" },
    { value: "INc-IV-2", instruction: "", 科目: "自然科學" },
    { value: "INc-IV-3", instruction: "", 科目: "自然科學" },
    { value: "INc-IV-4", instruction: "", 科目: "自然科學" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(NS_SCHEMA);
  getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
});

describe("per-子題 pre-draw (natural_sciences)", () => {
  it("fills empty per-小題 learning_content/performance with a random subset before submit", async () => {
    const onSubmit = vi.fn();
    render(<ParamForm subject="natural_sciences" onSubmit={onSubmit} />);
    await screen.findByPlaceholderText("自動 3-7");
    fireEvent.change(screen.getByPlaceholderText("自動 3-7"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /form\.btn_generate/i }));

    const confirmBtn = await screen.findByRole("button", { name: /form\.btn_confirm_send/i });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const payload = onSubmit.mock.calls[0][0];
    expect(typeof payload.subquestion_configs).toBe("string");
    const rows = JSON.parse(payload.subquestion_configs as string);
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      expect(Array.isArray(row.learning_content)).toBe(true);
      expect(row.learning_content.length).toBeGreaterThanOrEqual(1);
      expect(row.learning_content.length).toBeLessThanOrEqual(3);
      expect(Array.isArray(row.learning_performance)).toBe(true);
      expect(row.learning_performance.length).toBeGreaterThanOrEqual(1);
      expect(row.learning_performance.length).toBeLessThanOrEqual(2);
      for (const code of row.learning_content) {
        expect(["INc-IV-1", "INc-IV-2", "INc-IV-3", "INc-IV-4"]).toContain(code);
      }
      for (const code of row.learning_performance) {
        expect(["tr-IV-1", "tr-IV-2", "tr-IV-3"]).toContain(code);
      }
      expect(row).not.toHaveProperty("_lcWasAutoDrawn");
      expect(row).not.toHaveProperty("_lpWasAutoDrawn");
    }
  });
});
