/**
 * Issue #839: the form disables 科目 and 內容領域 options the 釘選 codes do not
 * allow, with a hint.
 *
 * The 釘選 codes are the form's 學習內容/學習表現 selections plus each 各小題配置
 * row's own pins. Admission comes only from `admitted_by` tags on the schema
 * payload (ADR 0020) — never a prefix table. A 科目/內容領域 option that some
 * 釘選 code does not admit is shown disabled (never hidden); `全部`/`隨機` stay
 * enabled; a hint line under the control names the constraining codes,
 * prefixed with `小題 N:` for codes sourced from a 各小題配置 row, and is
 * associated with the control via `aria-describedby`. 發送前確認 is unchanged
 * (ADR 0021) except that `CONFIRMATION_PARENT_CHILDREN` no longer treats
 * 學習表現 as a child of 內容領域 (#833: 學習表現 has no 內容領域 parent).
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
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

const LC_CIVIC = "公Bn-Ⅳ-3";
const LC_ROW = "公Aa-Ⅳ-1";
const LP_CIVIC = "公1c-Ⅳ-1";
const DOMAIN_CIVIC = "Civic Institutions and Systems";
const DOMAIN_OTHER = "Civic Participation";

const BASE_SOCIAL_SCHEMA = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [
    { value: "歷史", instruction: "" },
    { value: "地理", instruction: "" },
    { value: "公民與社會", instruction: "" },
    { value: "跨科", instruction: "" },
  ],
  內容領域: [
    { value: DOMAIN_CIVIC, instruction: "" },
    { value: DOMAIN_OTHER, instruction: "" },
  ],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: [
    { value: LP_CIVIC, instruction: "", 科目: "公", admitted_by: { 科目: ["公民與社會", "跨科"] } },
  ],
  學習內容: [
    {
      value: LC_CIVIC,
      instruction: "",
      科目: "公",
      admitted_by: { 科目: ["公民與社會", "跨科"], 內容領域: [DOMAIN_CIVIC] },
    },
    {
      value: LC_ROW,
      instruction: "",
      科目: "公",
      admitted_by: { 科目: ["公民與社會", "跨科"] },
    },
  ],
  digital_only_question_types: [],
};

async function renderSocial(initialParams: Record<string, unknown> = {}) {
  render(
    <ParamForm
      subject="social_studies"
      onSubmit={vi.fn()}
      disabled={false}
      initialParams={initialParams}
    />,
  );
  await screen.findByRole("button", { name: "產生" });
}

function subjectSelect() {
  return screen.getByRole("combobox", { name: "科目" });
}

function domainSelect() {
  return screen.getByRole("combobox", { name: "內容領域" });
}

function subjectOption(name: string) {
  return within(subjectSelect()).getByRole("option", { name });
}

function domainOption(name: string) {
  return within(domainSelect()).getByRole("option", { name });
}

describe("#839 科目/內容領域 narrowing by 釘選 codes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(BASE_SOCIAL_SCHEMA);
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

  it("disables 歷史/地理 and hints 公Bn-Ⅳ-3 when the group-level 學習內容 pins it", async () => {
    await renderSocial({ learning_content: [LC_CIVIC] });

    await waitFor(() => expect(subjectOption("歷史")).toBeDisabled());
    expect(subjectOption("地理")).toBeDisabled();
    expect(subjectOption("公民與社會")).not.toBeDisabled();
    expect(subjectOption("跨科")).not.toBeDisabled();
    expect(subjectOption("全部（隨機）")).not.toBeDisabled();

    const hint = document.getElementById(subjectSelect().getAttribute("aria-describedby") ?? "");
    expect(hint?.textContent).toContain(LC_CIVIC);
  });

  it("re-enables everything and removes the hint once 公Bn-Ⅳ-3 is deselected", async () => {
    await renderSocial({ learning_content: [LC_CIVIC] });
    await waitFor(() => expect(subjectOption("歷史")).toBeDisabled());

    const chip = screen.getByText(LC_CIVIC).closest("span.inline-flex") as HTMLElement;
    fireEvent.click(within(chip).getByRole("button", { name: "×" }));

    await waitFor(() => expect(subjectOption("歷史")).not.toBeDisabled());
    expect(subjectOption("地理")).not.toBeDisabled();
    expect(subjectSelect().getAttribute("aria-describedby")).toBeNull();
    expect(screen.queryByText(LC_CIVIC)).not.toBeInTheDocument();
  });

  it("disables 歷史/地理 and hints 公1c-Ⅳ-1 when the group-level 學習表現 pins it", async () => {
    await renderSocial({ learning_performance: [LP_CIVIC] });

    await waitFor(() => expect(subjectOption("歷史")).toBeDisabled());
    expect(subjectOption("地理")).toBeDisabled();
    expect(subjectOption("公民與社會")).not.toBeDisabled();
    expect(subjectOption("跨科")).not.toBeDisabled();

    const hint = document.getElementById(subjectSelect().getAttribute("aria-describedby") ?? "");
    expect(hint?.textContent).toContain(LP_CIVIC);
  });

  it('hints "小題 2: 公Aa-Ⅳ-1" and disables 歷史/地理 when only the second 各小題配置 row pins it', async () => {
    await renderSocial({
      sub_question_count: 2,
      subquestion_configs: [{}, { learning_content: [LC_ROW] }],
    });

    await waitFor(() => expect(subjectOption("歷史")).toBeDisabled());
    expect(subjectOption("地理")).toBeDisabled();
    expect(subjectOption("公民與社會")).not.toBeDisabled();

    const hint = document.getElementById(subjectSelect().getAttribute("aria-describedby") ?? "");
    expect(hint?.textContent).toContain(`小題 2: ${LC_ROW}`);
  });

  it("公民與社會 + 公Bn-Ⅳ-3: only its 內容領域 and 全部（隨機） remain enabled", async () => {
    await renderSocial({ subject_filter: "公民與社會", learning_content: [LC_CIVIC] });

    await waitFor(() => expect(domainOption(DOMAIN_OTHER)).toBeDisabled());
    expect(domainOption(DOMAIN_CIVIC)).not.toBeDisabled();
    expect(domainOption("全部（隨機）")).not.toBeDisabled();
  });

  it("跨科 + 公Bn-Ⅳ-3 also narrows 內容領域", async () => {
    // 跨科 is one of the ICCS-domain-filtered subjects too.
    await renderSocial({ subject_filter: "跨科", learning_content: [LC_CIVIC] });
    await waitFor(() => expect(domainOption(DOMAIN_OTHER)).toBeDisabled());
    expect(domainOption(DOMAIN_CIVIC)).not.toBeDisabled();
  });

  it("a 歷 code never narrows 內容領域, even under 跨科", async () => {
    // A 歷 code carries no 內容領域 admission tag, so pinning it never narrows 內容領域.
    getSchemasMock.mockResolvedValue({
      ...BASE_SOCIAL_SCHEMA,
      學習內容: [
        ...BASE_SOCIAL_SCHEMA.學習內容,
        { value: "歷Ka-Ⅳ-1", instruction: "", 科目: "歷", admitted_by: { 科目: ["歷史", "跨科"] } },
      ],
    });
    await renderSocial({ subject_filter: "跨科", learning_content: ["歷Ka-Ⅳ-1"] });
    expect(domainOption(DOMAIN_CIVIC)).not.toBeDisabled();
    expect(domainOption(DOMAIN_OTHER)).not.toBeDisabled();
  });

  it("associates the 科目 hint with the control via aria-describedby (accessible description)", async () => {
    await renderSocial({ learning_content: [LC_CIVIC] });
    await waitFor(() => expect(subjectOption("歷史")).toBeDisabled());

    expect(
      screen.getByRole("combobox", { name: "科目", description: new RegExp(LC_CIVIC) }),
    ).toBeInTheDocument();
  });

  it("associates the 內容領域 hint with the control via aria-describedby (accessible description)", async () => {
    await renderSocial({ subject_filter: "公民與社會", learning_content: [LC_CIVIC] });
    await waitFor(() => expect(domainOption(DOMAIN_OTHER)).toBeDisabled());

    expect(
      screen.getByRole("combobox", { name: "內容領域", description: new RegExp(LC_CIVIC) }),
    ).toBeInTheDocument();
  });

  it("keeps every 科目 and 內容領域 value selectable on 發送前確認 despite main-form narrowing", async () => {
    resolveGenerateMock.mockResolvedValueOnce({
      payload: {
        subject: "social_studies",
        grade: 8,
        count: 1,
        per_question_params: JSON.stringify([{
          subject_filter: ["公民與社會"],
          content_domain: DOMAIN_CIVIC,
          learning_content: [LC_CIVIC],
          subquestion_configs: JSON.stringify([
            { question_type: "選擇題", learning_content: [LC_CIVIC] },
          ]),
        }]),
      },
      drawn: [
        "per_question_params[0].內容領域",
        "per_question_params[0].科目",
      ],
      cleared: [],
    });

    await renderSocial({ subject_filter: "公民與社會", learning_content: [LC_CIVIC] });
    await waitFor(() => expect(subjectOption("歷史")).toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "產生" }));
    await screen.findByRole("heading", { name: "發送前確認設定" });

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const subjectDt = question.getByText("科目", { selector: "dt" });
    fireEvent.click(within(subjectDt.parentElement as HTMLElement).getByRole("button", { name: "編輯" }));
    const subjectMulti = screen.getByRole("listbox", { name: "科目" });
    const subjectOptions = within(subjectMulti).getAllByRole("option");
    expect(subjectOptions.map((option) => option.textContent)).toEqual(["歷史", "地理", "公民與社會", "跨科"]);
    subjectOptions.forEach((option) => expect(option).not.toBeDisabled());

    const domainRow = question.getByText(`內容領域: ${DOMAIN_CIVIC}`).parentElement as HTMLElement;
    fireEvent.click(within(domainRow).getByRole("button", { name: "編輯" }));
    const domainCombo = within(domainRow).getByRole("combobox", { name: "內容領域" });
    const domainOptions = within(domainCombo).getAllByRole("option");
    expect(domainOptions.map((option) => option.textContent)).toEqual(["未填寫", DOMAIN_CIVIC, DOMAIN_OTHER]);
    domainOptions.forEach((option) => expect(option).not.toBeDisabled());
  });

  it("does not clear a drawn 學習表現 when 內容領域 is edited (學習表現 is not a child of 內容領域)", async () => {
    resolveGenerateMock
      .mockResolvedValueOnce({
        payload: {
          subject: "social_studies",
          grade: 8,
          count: 1,
          per_question_params: JSON.stringify([{
            subject_filter: ["公民與社會"],
            content_domain: DOMAIN_CIVIC,
            learning_content: [LC_CIVIC],
            learning_performance: [LP_CIVIC],
            subquestion_configs: [
              {
                question_type: "選擇題",
                learning_content: [LC_CIVIC],
                learning_performance: [LP_CIVIC],
              },
            ],
          }]),
        },
        drawn: [
          "per_question_params[0].內容領域",
          "per_question_params[0].學習內容",
          "per_question_params[0].subquestion_configs[0].learning_content",
          "per_question_params[0].subquestion_configs[0].learning_performance",
        ],
        cleared: [],
      })
      .mockResolvedValueOnce({
        payload: {
          subject: "social_studies",
          grade: 8,
          count: 1,
          per_question_params: JSON.stringify([{
            subject_filter: ["公民與社會"],
            content_domain: DOMAIN_OTHER,
            learning_content: [LC_ROW],
            learning_performance: [LP_CIVIC],
            subquestion_configs: [
              {
                question_type: "選擇題",
                learning_content: [LC_ROW],
                learning_performance: [LP_CIVIC],
              },
            ],
          }]),
        },
        drawn: ["per_question_params[0].學習內容"],
        cleared: [],
      });

    render(
      <ParamForm
        subject="social_studies"
        onSubmit={vi.fn()}
        disabled={false}
        initialParams={{ subject_filter: "公民與社會" }}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "產生" }));
    await screen.findByRole("heading", { name: "發送前確認設定" });

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const domainRow = question.getByText(`內容領域: ${DOMAIN_CIVIC}`).parentElement as HTMLElement;
    fireEvent.click(within(domainRow).getByRole("button", { name: "編輯" }));
    fireEvent.change(within(domainRow).getByRole("combobox", { name: "內容領域" }), {
      target: { value: DOMAIN_OTHER },
    });

    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalledTimes(2));
    const [resubmitted] = resolveGenerateMock.mock.calls[1] as [Record<string, unknown>];
    const row = JSON.parse(resubmitted.per_question_params as string)[0] as Record<string, unknown>;
    const nestedConfigs = typeof row.subquestion_configs === "string"
      ? JSON.parse(row.subquestion_configs) as Array<Record<string, unknown>>
      : row.subquestion_configs as Array<Record<string, unknown>>;
    expect(nestedConfigs[0]).not.toHaveProperty("learning_content");
    expect(nestedConfigs[0]).toHaveProperty("learning_performance", [LP_CIVIC]);
  });
});
