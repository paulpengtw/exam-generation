/**
 * #444 — 重抽: clearing per-小題 LC/LP on confirmation re-draws from 全域池
 *
 * Test-first, one slice per acceptance criterion:
 *   1. Emptying the LC (or LP) picker immediately fills it with a fresh draw
 *      from the current 全域池, within 預抽 ranges.
 *   2. The redrawn field shows the amber 隨機 badge and sets the auto-drawn flag.
 *   3. 確認送出 sends the redrawn codes (釘選 — backend never re-randomises).
 *   4. Clearing again produces a new draw; sibling field, other 小題/題組, and
 *      the seed are unchanged.
 *   5. The card never renders an empty/unresolved LC or LP state.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
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

// Schema with 4 LC + 4 LP entries for 社會領域.
const SS_SCHEMA = {
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

// Shorthand codes using unicode escape to avoid encoding confusion.
const LC_A = "歷Aa-Ⅳ-1"; // 歷Aa-Ⅳ-1
const LC_B = "歷Ab-Ⅳ-1"; // 歷Ab-Ⅳ-1
const LC_C = "歷Ac-Ⅳ-1"; // 歷Ac-Ⅳ-1
const LP_B = "社1b-Ⅳ-1"; // 社1b-Ⅳ-1

// The global LC pool used in these tests.
// With Math.random always==0, drawRandomSubset(3-item pool, 1, 3):
//   count = floor(0*3)+1 = 1
//   Shuffle (all j=0): [LC_C, LC_B, LC_A] → [LC_B, LC_C, LC_A] → slice(0,1) → [LC_B]
// With Math.random always==0.9:
//   count = floor(0.9*3)+1 = floor(2.7)+1 = 3
//   Shuffle: i=2 j=2(no-op), i=1 j=1(no-op) → [LC_A,LC_B,LC_C]
//   slice(0,3) → [LC_A, LC_B, LC_C]
const GLOBAL_LC_POOL = [LC_A, LC_B, LC_C];

// Base initialParams: 3 explicit global LC codes so perSubqLcPool = learningContent.
// LP global pool is empty (no explicit selection) so perSubqLpPool = finalLp (1-2 drawn items).
const BASE_PARAMS = {
  sub_question_count: 1,
  core_question: "已提供的核心問題",
  subquestion_configs: [{}],
  learning_content: GLOBAL_LC_POOL,
};

async function openConfirmationWith444Setup(
  onSubmit = vi.fn(),
  extraParams: Record<string, unknown> = {},
) {
  // Math.random=0 during handleSubmit for deterministic initial pre-draws.
  const random = vi.spyOn(Math, "random").mockReturnValue(0);
  render(
    <ParamForm
      subject="social_studies"
      onSubmit={onSubmit}
      disabled={false}
      initialParams={{ ...BASE_PARAMS, ...extraParams }}
    />,
  );
  const button = await screen.findByRole("button", { name: "產生" });
  fireEvent.submit(button.closest("form")!);
  await screen.findByRole("heading", { name: "發送前確認設定" });
  random.mockRestore();
  return { onSubmit };
}

/** Get the first 小題 card within the n-th 題組 region (0-indexed). */
function getSubqCard(questionN: number, subqN: number) {
  const label = `第${questionN + 1}題`;
  const question = within(screen.getByRole("region", { name: label }));
  const subqH = question.getByRole("heading", { name: "各小題配置", level: 4 });
  const subqSec = within(subqH.closest("section") as HTMLElement);
  return within(subqSec.getAllByRole("listitem")[subqN]);
}

/** Get the SearchPicker root <div.relative> for the LC field within a card. */
function getLcPickerRoot(card: ReturnType<typeof within>) {
  return card.getByLabelText("學習內容").parentElement as HTMLElement; // div.relative
}

/** Get the SearchPicker root <div.relative> for the LP field within a card. */
function getLpPickerRoot(card: ReturnType<typeof within>) {
  return card.getByLabelText("學習表現").parentElement as HTMLElement; // div.relative
}

/** Click the × remove button for the chip that displays exactly `code`. */
function clickRemoveChip(pickerRoot: HTMLElement, code: string) {
  const codeSpan = within(pickerRoot).getByText(code);
  const chip = codeSpan.closest("span.inline-flex") as HTMLElement;
  fireEvent.click(within(chip).getByRole("button", { name: "×" }));
}

/** Read chip codes currently displayed in a picker root. */
function readChipCodes(pickerRoot: HTMLElement): string[] {
  return Array.from(pickerRoot.querySelectorAll("span.inline-flex span.font-medium"))
    .map((el) => el.textContent ?? "");
}

describe("ParamForm 重抽 LC/LP (#444)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    getSchemasMock.mockResolvedValue(SS_SCHEMA);
    getAvailableModelsMock.mockResolvedValue({
      allowed: [],
      defaults: { plan: "", execute: "" },
    });
    planCoreQuestionsMock.mockResolvedValue({ candidates: [] });
    previewGenerateMock.mockResolvedValue({ prompts: [] });
  });

  // ── Slices 1 + 2 ─────────────────────────────────────────────────────────────
  // Clearing the LC picker triggers an immediate redraw from perSubqLcPool (the
  // 全域池 used by 預抽), within range 1–3. The amber 隨機 badge persists.
  it("重抽 Crit 1+2 — 清除 LC 後立即從 全域池 重抽，count 在 1–3 內，amber badge 保留", async () => {
    await openConfirmationWith444Setup();
    const card = getSubqCard(0, 0);
    const lcPickerRoot = getLcPickerRoot(card);
    const lcSection = lcPickerRoot.parentElement as HTMLElement;

    // Initial pre-draw (Math.random=0) → LC chip = [LC_B].
    expect(readChipCodes(lcPickerRoot)).toEqual([LC_B]);
    expect(within(lcSection).getByText("隨機抽取")).toHaveClass("text-amber-700");

    // 重抽 trigger: clear the chip. Math.random=0 → draws [LC_B] again.
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    act(() => { clickRemoveChip(lcPickerRoot, LC_B); });
    random.mockRestore();

    // Criterion 1: fresh draw from the 全域池, within range 1–3.
    const redrawnCodes = readChipCodes(lcPickerRoot);
    expect(redrawnCodes.length).toBeGreaterThanOrEqual(1);
    expect(redrawnCodes.length).toBeLessThanOrEqual(3);
    for (const code of redrawnCodes) {
      expect(GLOBAL_LC_POOL).toContain(code);
    }

    // Criterion 2: amber badge still showing.
    expect(within(lcSection).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(within(lcSection).queryByText("使用者選擇")).not.toBeInTheDocument();
  });

  it("重抽 Crit 1+2 — 清除 LP 後立即從 全域池 重抽，amber badge 保留", async () => {
    await openConfirmationWith444Setup();
    const card = getSubqCard(0, 0);
    const lpPickerRoot = getLpPickerRoot(card);
    const lpSection = lpPickerRoot.parentElement as HTMLElement;

    // With Math.random=0: global LP draw from 4-item pool → finalLp=[LP_B].
    // perSubqLpPool=[LP_B]. Per-subq LP draw from 1-item pool → [LP_B].
    expect(readChipCodes(lpPickerRoot)).toEqual([LP_B]);
    expect(within(lpSection).getByText("隨機抽取")).toHaveClass("text-amber-700");

    // 重抽 trigger.
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    act(() => { clickRemoveChip(lpPickerRoot, LP_B); });
    random.mockRestore();

    // 1-item LP pool → redraw still gives [LP_B].
    const redrawnCodes = readChipCodes(lpPickerRoot);
    expect(redrawnCodes.length).toBeGreaterThanOrEqual(1);
    expect(redrawnCodes.length).toBeLessThanOrEqual(2); // LP range 1–2
    // Amber badge preserved.
    expect(within(lpSection).getByText("隨機抽取")).toHaveClass("text-amber-700");
  });

  // ── Slice 3 ──────────────────────────────────────────────────────────────────
  // 確認送出 sends redrawn LC codes verbatim in the 小題 row (釘選).
  it("重抽 Crit 3 — 確認送出將重抽的 LC 代碼原樣傳送（釘選）", async () => {
    const onSubmit = vi.fn();
    await openConfirmationWith444Setup(onSubmit);
    const card = getSubqCard(0, 0);
    const lcPickerRoot = getLcPickerRoot(card);

    // Redraw with Math.random=0.9 → [LC_A, LC_B, LC_C] (3 codes from pool).
    const random = vi.spyOn(Math, "random").mockReturnValue(0.9);
    act(() => { clickRemoveChip(lcPickerRoot, LC_B); });
    random.mockRestore();

    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const perQuestion = JSON.parse(
      onSubmit.mock.calls[0][0].per_question_params,
    ) as Array<{ subquestion_configs: string }>;

    const q1Configs = JSON.parse(
      perQuestion[0].subquestion_configs,
    ) as Array<Record<string, unknown>>;

    const lc = q1Configs[0].learning_content as string[];
    expect(Array.isArray(lc)).toBe(true);
    // Count within 預抽 range 1–3.
    expect(lc.length).toBeGreaterThanOrEqual(1);
    expect(lc.length).toBeLessThanOrEqual(3);
    // All codes from the 全域池.
    for (const code of lc) {
      expect(GLOBAL_LC_POOL).toContain(code);
    }
    // With Math.random=0.9, pool size=3 → count=3, no shuffling → all three.
    expect(lc).toContain(LC_A);
    expect(lc).toContain(LC_B);
    expect(lc).toContain(LC_C);
  });

  // ── Slice 4 ──────────────────────────────────────────────────────────────────
  // Second clear produces a DIFFERENT draw. LP (sibling field) stays unchanged.
  it("重抽 Crit 4 — 再次清除再次重抽（不同結果）；LP 不受影響", async () => {
    await openConfirmationWith444Setup();
    const card = getSubqCard(0, 0);
    const lcPickerRoot = getLcPickerRoot(card);
    const lpPickerRoot = getLpPickerRoot(card);
    const lpSection = lpPickerRoot.parentElement as HTMLElement;

    // Record LP before any LC change.
    const lpBeforeCodes = readChipCodes(lpPickerRoot);
    expect(lpBeforeCodes.length).toBeGreaterThanOrEqual(1);

    // First clear → redraw with Math.random=0 → [LC_B] (1 item).
    const random1 = vi.spyOn(Math, "random").mockReturnValue(0);
    act(() => { clickRemoveChip(lcPickerRoot, LC_B); });
    random1.mockRestore();
    const firstDrawCodes = readChipCodes(lcPickerRoot);
    expect(firstDrawCodes).toEqual([LC_B]); // deterministic

    // Second clear → redraw with Math.random=0.9 → [LC_A,LC_B,LC_C] (3 items).
    const random2 = vi.spyOn(Math, "random").mockReturnValue(0.9);
    act(() => { clickRemoveChip(lcPickerRoot, LC_B); });
    random2.mockRestore();
    const secondDrawCodes = readChipCodes(lcPickerRoot);
    expect(secondDrawCodes).toContain(LC_A);
    expect(secondDrawCodes).toContain(LC_B);
    expect(secondDrawCodes).toContain(LC_C);

    // Criterion 4a: second draw differs from first.
    expect(JSON.stringify(secondDrawCodes)).not.toBe(JSON.stringify(firstDrawCodes));

    // Criterion 4b: LP sibling stays unchanged.
    expect(readChipCodes(lpPickerRoot)).toEqual(lpBeforeCodes);
    expect(within(lpSection).getByText("隨機抽取")).toHaveClass("text-amber-700");
  });

  // ── Slice 4 supplement: other 題組 unaffected ────────────────────────────────
  it("重抽 Crit 4 — 清除第1題 LC 不影響第2題的 LC", async () => {
    await openConfirmationWith444Setup(vi.fn(), { count: 2 });

    const card1 = getSubqCard(0, 0);
    const card2 = getSubqCard(1, 0);
    const lcPickerRoot1 = getLcPickerRoot(card1);
    const lcPickerRoot2 = getLcPickerRoot(card2);

    // Record q2's initial codes before touching q1.
    const q2Initial = readChipCodes(lcPickerRoot2);
    expect(q2Initial.length).toBeGreaterThanOrEqual(1);

    // Clear q1's LC chip and redraw.
    const random = vi.spyOn(Math, "random").mockReturnValue(0.9);
    act(() => { clickRemoveChip(lcPickerRoot1, LC_B); });
    random.mockRestore();

    // q2's chips must be unchanged.
    expect(readChipCodes(lcPickerRoot2)).toEqual(q2Initial);
  });

  // ── Slice 5 ──────────────────────────────────────────────────────────────────
  // The card never renders an empty/unresolved state: after clearing, a chip is
  // immediately present and the badge stays amber.
  it("重抽 Crit 5 — 清除後卡片不出現空白 LC 狀態（badge 保持 amber，chip 非空）", async () => {
    await openConfirmationWith444Setup();
    const card = getSubqCard(0, 0);
    const lcPickerRoot = getLcPickerRoot(card);
    const lcSection = lcPickerRoot.parentElement as HTMLElement;

    // Pre-draw: amber badge + non-empty chips.
    expect(within(lcSection).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(readChipCodes(lcPickerRoot).length).toBeGreaterThanOrEqual(1);

    // Clear trigger.
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    act(() => { clickRemoveChip(lcPickerRoot, LC_B); });
    random.mockRestore();

    // After 重抽: non-empty and amber — never an unresolved hole.
    const afterCodes = readChipCodes(lcPickerRoot);
    expect(afterCodes.length).toBeGreaterThanOrEqual(1);
    expect(within(lcSection).getByText("隨機抽取")).toHaveClass("text-amber-700");
    expect(within(lcSection).queryByText("使用者選擇")).not.toBeInTheDocument();
  });
});
