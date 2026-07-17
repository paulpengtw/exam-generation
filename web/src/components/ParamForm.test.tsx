import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getSchemasMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
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
});
