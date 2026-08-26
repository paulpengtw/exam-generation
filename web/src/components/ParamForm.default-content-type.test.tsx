import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());
const resolveGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
  resolveGenerate: resolveGenerateMock,
}));
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

function resolveConfirmationPayload(payload: Record<string, unknown>) {
  const sourceRows = typeof payload.per_question_params === "string"
    ? JSON.parse(payload.per_question_params) as Record<string, unknown>[]
    : [];
  const base = Object.fromEntries(
    Object.entries(payload).filter(([key]) => ![
      "subject", "count", "per_question_params", "drawn", "redraws",
    ].includes(key)),
  );
  return {
    payload: {
      ...payload,
      per_question_params: JSON.stringify(sourceRows.map((row) => ({ ...base, ...row }))),
    },
    drawn: [],
  };
}

// Schema WITH 含圖片 — used for "default to 含圖片" tests
const SCHEMA_WITH_PICTURE = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "單一題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [
    { value: "含圖片", instruction: "" },
    { value: "純文字", instruction: "" },
  ],
  科目: [{ value: "數與量", instruction: "" }],
  學習表現: [],
  學習內容: [],
};

// Social studies schema with 含圖片
const SS_SCHEMA_WITH_PICTURE = {
  ...SCHEMA_WITH_PICTURE,
  題型種類: [{ value: "題組題", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
};

// Natural sciences schema with 含圖片
const NS_SCHEMA_WITH_PICTURE = {
  ...SS_SCHEMA_WITH_PICTURE,
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
};

// Schema WITHOUT 含圖片 — only 純文字 first
const SCHEMA_WITHOUT_PICTURE = {
  ...SCHEMA_WITH_PICTURE,
  題目內容類型: [{ value: "純文字", instruction: "" }],
};

describe("ParamForm default content_type and image_generation_mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SCHEMA_WITH_PICTURE);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) =>
      resolveConfirmationPayload(payload));
  });

  it.each([
    ["math", SCHEMA_WITH_PICTURE],
    ["social_studies", SS_SCHEMA_WITH_PICTURE],
    ["natural_sciences", NS_SCHEMA_WITH_PICTURE],
  ] as const)(
    "%s fresh mount (no initialParams): submits content_type 含圖片 and image_generation_mode gpt_image",
    async (subject, schema) => {
      getSchemasMock.mockResolvedValue(schema);
      const onSubmit = vi.fn();
      render(
        <ParamForm
          subject={subject}
          onSubmit={onSubmit}
          disabled={false}
        />,
      );
      fireEvent.click(await screen.findByRole("button", { name: "產生" }));
      await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));
      fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

      const payload = onSubmit.mock.calls[0][0];
      expect(payload.image_generation_mode).toBe("gpt_image");

      const perQuestion = JSON.parse(payload.per_question_params);
      expect(perQuestion[0].content_type).toBe("含圖片");
    },
  );

  it("falls back to first schema entry when schema lacks 含圖片", async () => {
    getSchemasMock.mockResolvedValue(SCHEMA_WITHOUT_PICTURE);
    const onSubmit = vi.fn();
    render(
      <ParamForm subject="math" onSubmit={onSubmit} disabled={false} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const payload = onSubmit.mock.calls[0][0];
    const perQuestion = JSON.parse(payload.per_question_params);
    expect(perQuestion[0].content_type).toBe("純文字");
  });

  it("respects initialParams.content_type when supplied (wins over default)", async () => {
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="math"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{ content_type: "graphs/charts/tables" }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await waitFor(() => expect(previewGenerateMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    const payload = onSubmit.mock.calls[0][0];
    const perQuestion = JSON.parse(payload.per_question_params);
    expect(perQuestion[0].content_type).toBe("graphs/charts/tables");
  });
});
