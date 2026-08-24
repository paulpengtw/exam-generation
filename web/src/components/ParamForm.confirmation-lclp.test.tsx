/**
 * #443 — 確認頁修改: 學習內容/學習表現 editable on confirmation cards
 *
 * Test-first, one slice per acceptance criterion:
 *   1. Each card renders 學習內容 and 學習表現 SearchPickers (full subject-filtered pools).
 *   2. Explicit selection replaces resolved codes, clears auto-drawn flag, flips badge.
 *   3. 確認送出 sends explicit codes verbatim (強制值 semantics).
 *   4. Sibling field and other 小題/題組 stay untouched.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSchemasMock = vi.hoisted(() => vi.fn());
const getAvailableModelsMock = vi.hoisted(() => vi.fn());
const planCoreQuestionsMock = vi.hoisted(() => vi.fn());
const previewGenerateMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({
  getSchemas: getSchemasMock,
  getAvailableModels: getAvailableModelsMock,
  planCoreQuestions: planCoreQuestionsMock,
  previewGenerate: previewGenerateMock,
}));
vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) => selector({ lang: "zh-TW" }),
}));

import ParamForm from "./ParamForm";

// Schema with LC/LP pool entries for 社會領域.
const SS_SCHEMA_WITH_CURRICULUM = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "選擇題", instruction: "" }],
  數學思考: [{ value: "形成", instruction: "" }],
  question_style: [{ value: "課本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: [
    { value: "社1a-Ⅳ-1", instruction: "理解公民意識", 科目: "社" },
    { value: "社1b-Ⅳ-1", instruction: "應用公民知識", 科目: "社" },
    { value: "社1c-Ⅳ-1", instruction: "分析社會現象", 科目: "社" },
    { value: "社1d-Ⅳ-1", instruction: "評估公民行動", 科目: "社" },
  ],
  學習內容: [
    { value: "歷Aa-Ⅳ-1", instruction: "古代文明的發展", 科目: "歷史" },
    { value: "歷Ab-Ⅳ-1", instruction: "中世紀歐洲的演變", 科目: "歷史" },
    { value: "歷Ac-Ⅳ-1", instruction: "近代民族國家興起", 科目: "歷史" },
    { value: "歷Ad-Ⅳ-1", instruction: "現代世界局勢", 科目: "歷史" },
  ],
};

async function openConfirmation(
  subject = "social_studies",
  initialParams: Record<string, unknown> = {},
  onSubmit = vi.fn(),
) {
  render(
    <ParamForm
      subject={subject}
      onSubmit={onSubmit}
      disabled={false}
      initialParams={initialParams}
    />,
  );
  const button = await screen.findByRole("button", { name: "產生" });
  fireEvent.submit(button.closest("form")!);
  return screen.findByRole("heading", { name: "發送前確認設定" });
}

describe("ParamForm 確認頁 LC/LP 可編輯 (#443)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SS_SCHEMA_WITH_CURRICULUM);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  // ── Slice 1 ──────────────────────────────────────────────────────────────────
  // Each card renders 學習內容 and 學習表現 SearchPickers over the full
  // subject-filtered pools (NOT limited to the 全域池).
  it("各小題卡片渲染學習內容和學習表現 SearchPicker（全科目課綱池）", async () => {
    await openConfirmation("social_studies", {
      count: 2,
      sub_question_count: 2,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}, {}],
    });

    for (const questionName of ["第1題", "第2題"]) {
      const question = within(screen.getByRole("region", { name: questionName }));
      // Scope to "各小題配置" section to avoid picking up question-level LP/LC <li> items
      const subqHeading = question.getByRole("heading", { name: "各小題配置", level: 4 });
      const subqSection = within(subqHeading.closest("section") as HTMLElement);
      const cards = subqSection.getAllByRole("listitem");
      expect(cards).toHaveLength(2);

      for (const card of cards) {
        const c = within(card);
        // SearchPicker inputs render via label–input association
        expect(c.getByLabelText("學習內容")).toBeInTheDocument();
        expect(c.getByLabelText("學習表現")).toBeInTheDocument();
        // Placeholders match the zh-TW locale
        expect(c.getByPlaceholderText("搜尋學習內容...")).toBeInTheDocument();
        expect(c.getByPlaceholderText("搜尋學習表現...")).toBeInTheDocument();
      }
    }
  });

  // ── Slice 2 ──────────────────────────────────────────────────────────────────
  // Explicit selection replaces the resolved codes for that 小題 only, clears
  // that field's auto-drawn flag, and flips the badge to user-supplied.
  // The sibling field (LP) badge must stay amber.
  it("明確選擇後清除預抽旗標，LC badge 翻轉為使用者選擇，同小題 LP badge 不受影響", async () => {
    // With Math.random() == 0, drawRandomSubset of 2-item pool yields pool[1].
    // So: subquestion LC 預抽 = ["歷Ab-Ⅳ-1"], LP 預抽 = ["社1b-Ⅳ-1"].
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    await openConfirmation("social_studies", {
      sub_question_count: 1,
      core_question: "已提供的核心問題",
      subquestion_configs: [{}],  // no explicit LC/LP → auto-draw
    });
    random.mockRestore();

    const question = within(screen.getByRole("region", { name: "第1題" }));
    const subqH = question.getByRole("heading", { name: "各小題配置", level: 4 });
    const subqSec = within(subqH.closest("section") as HTMLElement);
    const card = within(subqSec.getAllByRole("listitem")[0]);

    // LC input and its section container
    const lcInput = card.getByLabelText("學習內容");
    const lcPickerRoot = lcInput.parentElement!; // div.relative (SearchPicker root)
    const lcSection = lcPickerRoot.parentElement!; // outer wrapper containing badge + picker

    // LP input and its section container
    const lpInput = card.getByLabelText("學習表現");
    const lpPickerRoot = lpInput.parentElement!;
    const lpSection = lpPickerRoot.parentElement!;

    // Both badges start amber because codes were 預抽 (auto-drawn).
    expect(within(lcSection as HTMLElement).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(within(lpSection as HTMLElement).getByText("隨機抽取")).toHaveClass("text-amber-700");

    // "歷Aa-Ⅳ-1" is NOT in the auto-drawn set, so it appears in the dropdown.
    fireEvent.change(lcInput, { target: { value: "歷Aa" } });
    const lcOption = await card.findByText("歷Aa-Ⅳ-1");
    fireEvent.mouseDown(lcOption.closest("button")!);

    // LC badge flips to green 使用者選擇.
    expect(within(lcSection as HTMLElement).queryByText("隨機抽取")).not.toBeInTheDocument();
    expect(within(lcSection as HTMLElement).getByText("使用者選擇")).toHaveClass("text-green-700");

    // LP badge stays amber — sibling field must not be affected.
    expect(within(lpSection as HTMLElement).getByText("隨機抽取")).toHaveClass("text-amber-700");
  });

  // ── Slice 3 ──────────────────────────────────────────────────────────────────
  // 確認送出 sends the explicit codes verbatim in the correct 小題 row
  // (強制值 semantics). Untouched rows must NOT materialise inherited pools.
  it("確認送出將明確選擇的 LC 代碼原樣包含在對應小題，明確選擇不外溢到其他小題或其他題組", async () => {
    // Math.random=0 → drawRandomSubset of ["歷Aa-Ⅳ-1","歷Ab-Ⅳ-1"] picks pool[1] = "歷Ab-Ⅳ-1"
    // so "歷Aa-Ⅳ-1" is never auto-drawn and is always available in the picker dropdown.
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          count: 2,
          sub_question_count: 2,
          core_question: "已提供的核心問題",
          subquestion_configs: [
            { question_type: "選擇題", instruction: "指示一" },
            { question_type: "選擇題", instruction: "指示二" },
          ],
        }}
      />,
    );
    {
      const btn = await screen.findByRole("button", { name: "產生" });
      fireEvent.submit(btn.closest("form")!);
    }
    await screen.findByRole("heading", { name: "發送前確認設定" });
    random.mockRestore();

    // Select LC "歷Ac-Ⅳ-1" on first 小題 of first 題組.
    // With Math.random=0 and 4-item pool, drawRandomSubset always draws pool[1]="歷Ab-Ⅳ-1".
    // Dedup alternative is "歷Aa-Ⅳ-1" (first non-Ab). "歷Ac-Ⅳ-1" is never auto-drawn.
    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    const firstSubqH = firstQuestion.getByRole("heading", { name: "各小題配置", level: 4 });
    const firstSubqSec = within(firstSubqH.closest("section") as HTMLElement);
    const firstCard = within(firstSubqSec.getAllByRole("listitem")[0]);
    const lcInput = firstCard.getByLabelText("學習內容");
    fireEvent.change(lcInput, { target: { value: "歷Ac" } });
    const option = await firstCard.findByText("歷Ac-Ⅳ-1");
    fireEvent.mouseDown(option.closest("button")!);

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const perQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ subquestion_configs: string }>;

    // First 題組: first 小題 carries the explicit LC verbatim.
    const q1Configs = JSON.parse(perQuestion[0].subquestion_configs) as Array<Record<string, unknown>>;
    expect(q1Configs[0].learning_content).toContain("歷Ac-Ⅳ-1");
    // Other fields on the same row are unchanged.
    expect(q1Configs[0].question_type).toBe("選擇題");
    expect(q1Configs[0].instruction).toBe("指示一");

    // Second 小題 of first 題組: untouched — explicit "歷Ac-Ⅳ-1" did NOT bleed into it.
    // (auto-drawn code "歷Ab-Ⅳ-1" may still be present from the pre-draw)
    const q1Cfg1Lc = q1Configs[1].learning_content as string[] | undefined;
    expect(q1Cfg1Lc).not.toContain("歷Ac-Ⅳ-1");

    // Second 題組: explicit "歷Ac-Ⅳ-1" must not appear on any row.
    const q2Configs = JSON.parse(perQuestion[1].subquestion_configs) as Array<Record<string, unknown>>;
    const q2Cfg0Lc = q2Configs[0].learning_content as string[] | undefined;
    const q2Cfg1Lc = q2Configs[1].learning_content as string[] | undefined;
    expect(q2Cfg0Lc).not.toContain("歷Ac-Ⅳ-1");
    expect(q2Cfg1Lc).not.toContain("歷Ac-Ⅳ-1");
  });

  // ── Slice 4 ──────────────────────────────────────────────────────────────────
  // The sibling field (LC vs LP) and other 小題/題組 stay untouched.
  it("修改某小題的 LP 不影響同小題的 LC，也不影響其他小題或其他題組的 LP", async () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    const onSubmit = vi.fn();
    render(
      <ParamForm
        subject="social_studies"
        onSubmit={onSubmit}
        disabled={false}
        initialParams={{
          count: 2,
          sub_question_count: 2,
          core_question: "已提供的核心問題",
          subquestion_configs: [{}, {}],
        }}
      />,
    );
    {
      const btn = await screen.findByRole("button", { name: "產生" });
      fireEvent.submit(btn.closest("form")!);
    }
    await screen.findByRole("heading", { name: "發送前確認設定" });
    random.mockRestore();

    const firstQuestion = within(screen.getByRole("region", { name: "第1題" }));
    const secondQuestion = within(screen.getByRole("region", { name: "第2題" }));

    // Scope to "各小題配置" section to avoid picking up question-level LP/LC <li> items
    const fSubqH1 = firstQuestion.getByRole("heading", { name: "各小題配置", level: 4 });
    const fSubqSec1 = within(fSubqH1.closest("section") as HTMLElement);
    const firstCard = within(fSubqSec1.getAllByRole("listitem")[0]);
    const secondCard = within(fSubqSec1.getAllByRole("listitem")[1]);

    const fSubqH2 = secondQuestion.getByRole("heading", { name: "各小題配置", level: 4 });
    const fSubqSec2 = within(fSubqH2.closest("section") as HTMLElement);

    const lcInput1 = firstCard.getByLabelText("學習內容");
    const lcSection1 = lcInput1.parentElement!.parentElement!;
    const lpInput1 = firstCard.getByLabelText("學習表現");
    const lpSection1 = lpInput1.parentElement!.parentElement!;
    const lpInput2 = secondCard.getByLabelText("學習表現");
    const lpSection2 = lpInput2.parentElement!.parentElement!;
    const lpInput_q2 = within(fSubqSec2.getAllByRole("listitem")[0]).getByLabelText("學習表現");
    const lpSection_q2 = lpInput_q2.parentElement!.parentElement!;

    // All start amber (auto-drawn with no explicit selection).
    expect(within(lcSection1 as HTMLElement).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(within(lpSection1 as HTMLElement).getByText("隨機抽取")).toHaveClass("text-amber-700");

    // Explicitly select LP on first card of first question ("社1c-Ⅳ-1" is not auto-drawn or dedup-picked).
    // Math.random=0 draws pool[1]="社1b-Ⅳ-1"; dedup alternative is "社1a-Ⅳ-1"; "社1c" is safe.
    fireEvent.change(lpInput1, { target: { value: "社1c" } });
    const lpOption = await firstCard.findByText("社1c-Ⅳ-1");
    fireEvent.mouseDown(lpOption.closest("button")!);

    // LP badge on first card flips to green.
    expect(within(lpSection1 as HTMLElement).queryByText("隨機抽取")).not.toBeInTheDocument();
    expect(within(lpSection1 as HTMLElement).getByText("使用者選擇")).toHaveClass("text-green-700");

    // LC badge on the SAME card stays amber — sibling field unaffected.
    expect(within(lcSection1 as HTMLElement).getByText("隨機抽取")).toHaveClass("text-amber-700");

    // LP badge on SECOND 小題 of first 題組 stays amber — other 小題 unaffected.
    expect(within(lpSection2 as HTMLElement).getByText("隨機抽取")).toHaveClass("text-amber-700");

    // LP badge on first 小題 of SECOND 題組 stays amber — other 題組 unaffected.
    expect(within(lpSection_q2 as HTMLElement).getByText("隨機抽取")).toHaveClass("text-amber-700");

    // Submit and verify LP code lands verbatim on the correct row only.
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));
    const perQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ subquestion_configs: string }>;

    const q1 = JSON.parse(perQuestion[0].subquestion_configs) as Array<Record<string, unknown>>;
    // First card: explicit LP present.
    expect((q1[0].learning_performance as string[]).includes("社1c-Ⅳ-1")).toBe(true);
    // LC on first card: auto-drawn codes still present (not cleared by LP change).
    expect(q1[0]).toHaveProperty("learning_content");

    // Second 題組: explicit "社1c-Ⅳ-1" must not appear on any row
    // (auto-drawn codes may still be present, but not the user's explicit pick).
    const q2 = JSON.parse(perQuestion[1].subquestion_configs) as Array<Record<string, unknown>>;
    const q2Lp = q2[0].learning_performance as string[] | undefined;
    expect(q2Lp).not.toContain("社1c-Ⅳ-1");
  });
});
