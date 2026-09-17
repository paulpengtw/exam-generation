/**
 * Issue #833: 學習表現 is no longer restricted by 內容領域.
 *
 * The only stage-4 公 學習表現 code, 公1c-Ⅳ-1, maps to no ICCS 內容領域. Before this
 * fix, ParamForm's `iccsDomainMappedCodes` / `filteredLpPool` / `restrictCodesToIccsDomain`
 * hid it from the per-小題 學習表現 pickers and silently dropped it at submit whenever a
 * 內容領域 was chosen under 公民與社會/跨科. 學習內容 filtering is untouched by this ticket.
 *
 * TDD cycles:
 *   1. Red: per-小題 學習表現 picker (各小題配置, main form) hides 公1c-Ⅳ-1 once a
 *      內容領域 is chosen under 公民與社會 → Green after removing filteredLpPool.
 *   2. Red: same under 跨科 → Green.
 *   3. Regression: the request-level 學習表現 list already offers it regardless of
 *      內容領域 — must keep doing so.
 *   4. Red: submitting sends the resolve request body with 學習表現 codes unchanged
 *      whatever 內容領域 is chosen → Green.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  useLangStore: (selector: (state: { lang: string }) => unknown) => selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

const DOMAIN = "Civic Roles and Identities";
const STAGE4_PUBLIC_LP = "公1c-Ⅳ-1";
const SHARED_LP = "社1a-Ⅳ-1";

function buildSchema() {
  return {
    學習階段: "第四學習階段",
    grades: [7, 8, 9],
    情境: [{ value: "個人", instruction: "" }],
    題型種類: [{ value: "題組題", instruction: "" }],
    題型: [{ value: "選擇題", instruction: "" }],
    認知歷程: [{ value: "Knowing–Defining and Describing", instruction: "" }],
    內容領域: [{ value: DOMAIN, instruction: "" }],
    題目內容類型: [{ value: "純文字", instruction: "" }],
    科目: [
      { value: "公民與社會", instruction: "" },
      { value: "跨科", instruction: "" },
    ],
    核心素養: [{ value: "社-J-A2", instruction: "" }],
    學習表現: [
      {
        value: STAGE4_PUBLIC_LP,
        instruction: "法律與政治的基本概念",
        科目: "公",
        // No 內容領域 key: 學習表現 rows never carry one (ADR 0020).
        admitted_by: { 科目: ["公民與社會", "跨科"] },
      },
      {
        value: SHARED_LP,
        instruction: "共享社會領域表現",
        科目: "社",
        admitted_by: { 科目: ["歷史", "地理", "公民與社會", "跨科"] },
      },
    ],
    學習內容: [
      {
        value: "公Ad-Ⅳ-1",
        instruction: "人權普遍性保障原則",
        科目: "公",
        admitted_by: { 科目: ["公民與社會", "跨科"], 內容領域: [DOMAIN] },
      },
    ],
    內容領域_mapping: {},
    digital_only_question_types: [],
  };
}

describe("#833 學習表現 is no longer restricted by 內容領域", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(buildSchema());
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "", verify: "", correct: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
    resolveGenerateMock.mockImplementation(async (payload: Record<string, unknown>) => ({
      payload,
      drawn: [],
    }));
  });

  it.each([
    ["公民與社會"],
    ["跨科"],
  ])("%s: per-小題 學習表現 picker offers and accepts 公1c-Ⅳ-1 under a chosen 內容領域", async (subjectFilterValue) => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          subject_filter: subjectFilterValue,
          content_domain: DOMAIN,
          sub_question_count: 1,
          subquestion_configs: [{}],
        }}
      />,
    );

    const heading = await screen.findByText("各小題配置");
    const section = heading.closest("div") as HTMLElement;
    const lpInput = within(section).getByPlaceholderText("搜尋學習表現...");

    fireEvent.change(lpInput, { target: { value: STAGE4_PUBLIC_LP } });
    const option = await within(section).findByText(STAGE4_PUBLIC_LP);
    fireEvent.mouseDown(option);

    await waitFor(() =>
      expect(within(section).getAllByText(STAGE4_PUBLIC_LP).length).toBeGreaterThan(0),
    );
  });

  it("request-level 學習表現 list still offers 公1c-Ⅳ-1 regardless of 內容領域", async () => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          subject_filter: "公民與社會",
          content_domain: DOMAIN,
        }}
      />,
    );

    const lpInput = await screen.findByPlaceholderText("搜尋學習表現...");
    fireEvent.change(lpInput, { target: { value: STAGE4_PUBLIC_LP } });
    expect(await screen.findByText(STAGE4_PUBLIC_LP)).toBeInTheDocument();
  });

  it("submits the resolve request body with 學習表現 codes unchanged whatever 內容領域 is chosen", async () => {
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{
          subject_filter: "公民與社會",
          content_domain: DOMAIN,
          learning_performance: [STAGE4_PUBLIC_LP],
        }}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "產生" }));

    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalled());
    const [payload] = resolveGenerateMock.mock.calls[0] as [Record<string, unknown>];
    expect(payload.learning_performance).toEqual([STAGE4_PUBLIC_LP]);
  });
});
