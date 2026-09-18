/**
 * Issue #840: 學習內容 codes the chosen or remaining 內容領域 would not accept
 * are disabled, never dropped.
 *
 * With a 內容領域 chosen, a civics 學習內容 code it does not admit is shown
 * disabled (never hidden), with the Task 8 hint pattern, in both the
 * request-level 學習內容 list/search and the form's per-小題 學習內容 pickers.
 * Under 內容領域 `隨機`, a civics code is disabled when selecting it would
 * leave no 內容領域 admitting every already-釘選 civics 學習內容 code. A
 * selected code always stays deselectable, even when disabled. Filtering by
 * 科目 is unchanged, and the submit-time request body carries exactly the
 * selected codes (no silent 內容領域 filtering).
 *
 * Admission comes only from `admitted_by["內容領域"]` on the schema payload
 * (ADR 0020) — a row without that tag (歷/地 codes, or an untagged civics
 * code) is unscoped and never disabled by 內容領域.
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

const DOMAIN_A = "Civic Participation";
const DOMAIN_B = "Civic Institutions and Systems";
// LC_A and LC_B admit disjoint 內容領域 sets, so pinning one under 隨機
// disables the other.
const LC_A = "公Aa-Ⅳ-1";
const LC_B = "公Ab-Ⅳ-1";
const LC_UNSCOPED = "公Zz-Ⅳ-1";
const LC_HIST = "歷Aa-Ⅳ-1";

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
    { value: DOMAIN_A, instruction: "" },
    { value: DOMAIN_B, instruction: "" },
  ],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: [],
  學習內容: [
    {
      value: LC_A,
      instruction: "公民參與代碼A",
      科目: "公",
      admitted_by: { 科目: ["公民與社會", "跨科"], 內容領域: [DOMAIN_B] },
    },
    {
      value: LC_B,
      instruction: "公民參與代碼B",
      科目: "公",
      admitted_by: { 科目: ["公民與社會", "跨科"], 內容領域: [DOMAIN_A] },
    },
    {
      value: LC_UNSCOPED,
      instruction: "尚未標記內容領域的公民代碼",
      科目: "公",
      admitted_by: { 科目: ["公民與社會", "跨科"] },
    },
    {
      value: LC_HIST,
      instruction: "歷史代碼",
      科目: "歷",
      admitted_by: { 科目: ["歷史", "跨科"] },
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

function requestLevelLcSearchInput() {
  return screen.getByPlaceholderText("搜尋學習內容...");
}

function readChipCodes(pickerRoot: HTMLElement): string[] {
  return Array.from(pickerRoot.querySelectorAll("span.inline-flex span.font-medium")).map(
    (element) => element.textContent ?? "",
  );
}

describe("#840 學習內容 disabled (never dropped) by the chosen/remaining 內容領域", () => {
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

  it("disables (never hides) request-level 學習內容 codes the chosen 內容領域 does not admit, with a hint, and leaves 歷 codes unrestricted", async () => {
    await renderSocial({ content_domain: DOMAIN_A });

    const lcInput = requestLevelLcSearchInput();
    fireEvent.change(lcInput, { target: { value: LC_A } });
    const disabledOption = await screen.findByText(LC_A);
    const disabledButton = disabledOption.closest("button") as HTMLElement;
    expect(disabledButton).toBeDisabled();

    // Clicking a disabled option must not add it.
    fireEvent.mouseDown(disabledOption);
    expect(screen.queryByText(LC_A)?.closest("span.inline-flex")).toBeNull();

    const pickerRoot = lcInput.parentElement as HTMLElement;
    const hintText = pickerRoot.textContent ?? "";
    expect(hintText).toContain(DOMAIN_A);

    fireEvent.change(lcInput, { target: { value: LC_B } });
    const admittedOption = await screen.findByText(LC_B);
    expect(admittedOption.closest("button")).not.toBeDisabled();

    fireEvent.change(lcInput, { target: { value: LC_UNSCOPED } });
    const unscopedOption = await screen.findByText(LC_UNSCOPED);
    expect(unscopedOption.closest("button")).not.toBeDisabled();

    fireEvent.change(lcInput, { target: { value: LC_HIST } });
    const histOption = await screen.findByText(LC_HIST);
    expect(histOption.closest("button")).not.toBeDisabled();
  });

  it("disables (never hides) the request-level 學習內容 checkbox grid the same way", async () => {
    await renderSocial({ content_domain: DOMAIN_A });

    const heading = screen.getByText("學習內容");
    const toggle = within(heading.parentElement as HTMLElement).getByRole("button", {
      name: "切換勾選模式",
    });
    fireEvent.click(toggle);

    const checkbox = screen.getByRole("checkbox", { name: new RegExp(LC_A) });
    expect(checkbox).toBeDisabled();
    const otherCheckbox = screen.getByRole("checkbox", { name: new RegExp(LC_B) });
    expect(otherCheckbox).not.toBeDisabled();
  });

  it("內容領域 隨機 + 公Aa-Ⅳ-1 selected disables 公Ab-Ⅳ-1 (no shared domain), with a hint, but never the unscoped code", async () => {
    await renderSocial({ learning_content: [LC_A] });

    const lcInput = requestLevelLcSearchInput();
    fireEvent.change(lcInput, { target: { value: LC_B } });
    const disabledOption = await screen.findByText(LC_B);
    expect(disabledOption.closest("button")).toBeDisabled();

    const pickerRoot = lcInput.parentElement as HTMLElement;
    expect(pickerRoot.textContent ?? "").toContain(LC_A);

    fireEvent.change(lcInput, { target: { value: LC_UNSCOPED } });
    const unscopedOption = await screen.findByText(LC_UNSCOPED);
    expect(unscopedOption.closest("button")).not.toBeDisabled();
  });

  it("keeps an already-selected 學習內容 code deselectable even once it becomes disabled", async () => {
    await renderSocial({ content_domain: DOMAIN_A, learning_content: [LC_A] });

    const chip = await screen.findByText(LC_A);
    const chipRoot = chip.closest("span.inline-flex") as HTMLElement;
    const removeButton = within(chipRoot).getByRole("button", { name: "×" });
    expect(removeButton).not.toBeDisabled();

    fireEvent.click(removeButton);
    await waitFor(() => expect(screen.queryByText(LC_A)).not.toBeInTheDocument());
  });

  it("submits the resolve request body with exactly the selected 學習內容 codes despite a 內容領域-disabled pin, once the #841 restored conflict is resolved", async () => {
    await renderSocial({
      subject_filter: "公民與社會",
      content_domain: DOMAIN_A,
      learning_content: [LC_A, LC_B],
    });

    // #841: LC_A only admits DOMAIN_B, so the restored 內容領域 (DOMAIN_A) is a
    // genuine conflict with an already-釘選 code — 產生 stays disabled and
    // neither code is silently dropped or fixed.
    expect(screen.getByRole("button", { name: "產生" })).toBeDisabled();

    fireEvent.change(screen.getByRole("combobox", { name: "內容領域" }), {
      target: { value: "" },
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "產生" })).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "產生" }));

    await waitFor(() => expect(resolveGenerateMock).toHaveBeenCalled());
    const [payload] = resolveGenerateMock.mock.calls[0] as [Record<string, unknown>];
    expect(payload.learning_content).toEqual([LC_A, LC_B]);
  });

  it("disables (never hides) 公Aa-Ⅳ-1 in the second 各小題配置 row's own 學習內容 picker, with a hint", async () => {
    await renderSocial({
      content_domain: DOMAIN_A,
      sub_question_count: 2,
      subquestion_configs: [{}, {}],
    });

    const heading = await screen.findByText("各小題配置");
    const section = heading.closest("div") as HTMLElement;
    const rows = within(section).getAllByPlaceholderText("搜尋學習內容...");
    const secondRowLcInput = rows[1];

    fireEvent.change(secondRowLcInput, { target: { value: LC_A } });
    const disabledOption = await within(section).findByText(LC_A);
    expect(disabledOption.closest("button")).toBeDisabled();

    fireEvent.mouseDown(disabledOption);
    const pickerRoot = secondRowLcInput.parentElement as HTMLElement;
    expect(readChipCodes(pickerRoot)).toEqual([]);
    expect(pickerRoot.textContent ?? "").toContain(DOMAIN_A);

    fireEvent.change(secondRowLcInput, { target: { value: LC_B } });
    const admittedOption = await within(section).findByText(LC_B);
    expect(admittedOption.closest("button")).not.toBeDisabled();
  });
});
