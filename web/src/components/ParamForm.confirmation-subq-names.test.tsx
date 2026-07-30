/**
 * Issue #318 — 確認頁 各小題配置：預抽/已選 學習內容・學習表現 除代號外顯示名稱。
 *
 * 發送前確認的每張小題 card 應以與題目層級相同的格式（monospace 代號 + 「— 名稱」，
 * 無 disc bullet）列出各小題配置的 學習內容 / 學習表現；名稱取自 schemas API 的
 * instruction（學習內容 條目說明 / 學習表現 說明）。schema 池查不到的代號以裸代號
 * 顯示（所見即所送，不得過濾、不崩潰）。
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

// 全域池各只放一個項目，讓 預抽 結果固定，毋須操作 Math.random。
const SS_SCHEMA_WITH_NAMES = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "個人", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [
    { value: "選擇題", instruction: "" },
    { value: "封閉式建構反應題", instruction: "" },
    { value: "開放式建構反應題", instruction: "" },
  ],
  閱讀歷程: [{ value: "擷取訊息", instruction: "" }],
  文本形式: [{ value: "連續文本", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "歷史", instruction: "" }],
  核心素養: [{ value: "社-J-A2", instruction: "" }],
  學習表現: [{ value: "社1a-Ⅳ-1", instruction: "發現生活課題", 科目: "社" }],
  學習內容: [{ value: "歷Ka-Ⅳ-1", instruction: "商朝與人群移動", 科目: "歷史" }],
};

const NS_SCHEMA_WITH_NAMES = {
  學習階段: "第四學習階段",
  grades: [7, 8, 9],
  情境: [{ value: "Personal", instruction: "" }],
  情境子類別: [{ value: "健康", parent: "Personal", instruction: "" }],
  題型種類: [{ value: "題組題", instruction: "" }],
  題型: [{ value: "Simple-multiple-choice", instruction: "" }],
  科學能力: [{ value: "能力一", instruction: "" }],
  題目內容類型: [{ value: "純文字", instruction: "" }],
  科目: [{ value: "自然科學", instruction: "" }],
  學習表現: [{ value: "tr-IV-1", instruction: "能依據觀察分類自然現象", 科目: "自然科學" }],
  學習內容: [{ value: "INc-IV-1", instruction: "宇宙間的尺度概念", 科目: "自然科學" }],
};

// 故意不放進 schema 池的代號 — 未知代號退化案例（仍會照送給後端）。
const UNKNOWN_LC_CODE = "地Ab-Ⅳ-9";

/** 帶各小題配置開啟 發送前確認：第 1 小題明確選擇 LC/LP，第 2、3 小題留空給 預抽。 */
async function openConfirmation(
  subject: string,
  subquestionConfigs: Record<string, unknown>[],
  onSubmit = vi.fn(),
) {
  render(
    <ParamForm
      subject={subject}
      onSubmit={onSubmit}
      disabled={false}
      initialParams={{
        core_question: "已提供的核心問題",
        sub_question_count: 3,
        subquestion_configs: subquestionConfigs,
      }}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "產生" }));
  await screen.findByRole("heading", { name: "發送前確認設定" });
  return onSubmit;
}

function openSocialConfirmation(onSubmit = vi.fn()) {
  return openConfirmation(
    "social_studies",
    [
      { learning_content: ["歷Ka-Ⅳ-1", UNKNOWN_LC_CODE], learning_performance: ["社1a-Ⅳ-1"] },
      {},
      {},
    ],
    onSubmit,
  );
}

/** 第 1 題 region 內第 n 張小題 card。 */
function 小題Card(n: number) {
  const question = within(screen.getByRole("region", { name: "第1題" }));
  return within(question.getByText(`第 ${n} 小題`).closest("li")!);
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getSchemasMock.mockResolvedValue(SS_SCHEMA_WITH_NAMES);
  getAvailableModelsMock.mockResolvedValue({ allowed: [], defaults: { plan: "", execute: "" } });
  planCoreQuestionsMock.mockResolvedValue({ candidates: ["候選核心問題"] });
  previewGenerateMock.mockResolvedValue({ prompts: [] });
});

describe("確認頁 各小題配置：學習內容 代號顯示名稱 (#318)", () => {
  it("小題 card 的每個學習內容代號以「代號 — 條目說明」顯示，格式同題目層級", async () => {
    await openSocialConfirmation();

    // 第 1 小題：使用者明確選擇的代號（已選 heading 保持不變）。
    const card1 = 小題Card(1);
    expect(card1.getByText("學習內容（已選 2 項）")).toBeInTheDocument();
    const explicitCode = card1.getByText("歷Ka-Ⅳ-1");
    expect(explicitCode).toHaveClass("font-mono");
    expect(card1.getByText("— 商朝與人群移動")).toBeInTheDocument();
    expect(explicitCode.closest("ul")).not.toHaveClass("list-disc");

    // 第 2 小題：預抽（隨機抽取）的代號同樣顯示名稱。
    const card2 = 小題Card(2);
    expect(card2.getByText("學習內容（隨機抽取 1 項）")).toBeInTheDocument();
    const predrawnCode = card2.getByText("歷Ka-Ⅳ-1");
    expect(predrawnCode).toHaveClass("font-mono");
    expect(card2.getByText("— 商朝與人群移動")).toBeInTheDocument();
    expect(predrawnCode.closest("ul")).not.toHaveClass("list-disc");
  });
});

describe("確認頁 各小題配置：學習表現 代號顯示名稱 (#318)", () => {
  it("小題 card 的每個學習表現代號以「代號 — 說明」顯示，格式同題目層級", async () => {
    await openSocialConfirmation();

    // 第 1 小題：使用者明確選擇的代號（已選 heading 保持不變）。
    const card1 = 小題Card(1);
    expect(card1.getByText("學習表現（已選 1 項）")).toBeInTheDocument();
    const explicitCode = card1.getByText("社1a-Ⅳ-1");
    expect(explicitCode).toHaveClass("font-mono");
    expect(card1.getByText("— 發現生活課題")).toBeInTheDocument();
    expect(explicitCode.closest("ul")).not.toHaveClass("list-disc");

    // 第 3 小題：預抽（隨機抽取）的代號同樣顯示名稱。
    const card3 = 小題Card(3);
    expect(card3.getByText("學習表現（隨機抽取 1 項）")).toBeInTheDocument();
    const predrawnCode = card3.getByText("社1a-Ⅳ-1");
    expect(predrawnCode).toHaveClass("font-mono");
    expect(card3.getByText("— 發現生活課題")).toBeInTheDocument();
    expect(predrawnCode.closest("ul")).not.toHaveClass("list-disc");
  });

  it("自然科學共用同一確認元件：小題 card 亦顯示 學習內容/學習表現 名稱", async () => {
    getSchemasMock.mockResolvedValue(NS_SCHEMA_WITH_NAMES);
    await openConfirmation("natural_sciences", [
      { learning_content: ["INc-IV-1"], learning_performance: ["tr-IV-1"] },
      {},
      {},
    ]);

    const card1 = 小題Card(1);
    expect(card1.getByText("INc-IV-1")).toHaveClass("font-mono");
    expect(card1.getByText("— 宇宙間的尺度概念")).toBeInTheDocument();
    expect(card1.getByText("tr-IV-1")).toHaveClass("font-mono");
    expect(card1.getByText("— 能依據觀察分類自然現象")).toBeInTheDocument();
  });
});

describe("確認頁 各小題配置：schema 池查不到的代號 (#318)", () => {
  it("未知代號退化為裸代號顯示 — 不崩潰、不顯示佔位文字、不被過濾", async () => {
    await openSocialConfirmation();

    const card1 = 小題Card(1);
    const unknownCode = card1.getByText(UNKNOWN_LC_CODE);
    expect(unknownCode).toBeInTheDocument();
    expect(unknownCode).toHaveClass("font-mono");
    // 只有裸代號：沒有「— 名稱」、也沒有任何佔位字樣。
    expect(unknownCode.closest("li")!.textContent).toBe(UNKNOWN_LC_CODE);
    // 未知代號不得被過濾掉 — 顯示的代號會照送給後端（所見即所送），已選數量仍計 2 項。
    expect(card1.getByText("學習內容（已選 2 項）")).toBeInTheDocument();
  });

  it("顯示名稱是純顯示變更：送出的 subquestion_configs 仍是裸代號陣列", async () => {
    const onSubmit = await openSocialConfirmation();
    fireEvent.click(screen.getByRole("button", { name: "確定發送" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const rows = JSON.parse(onSubmit.mock.calls[0][0].subquestion_configs as string);
    expect(rows).toHaveLength(3);
    // 明確選擇的代號原樣送出（含 schema 池查不到的代號），名稱不進 payload。
    expect(rows[0].learning_content).toEqual(["歷Ka-Ⅳ-1", UNKNOWN_LC_CODE]);
    expect(rows[0].learning_performance).toEqual(["社1a-Ⅳ-1"]);
    // 預抽 slot 仍是裸代號，內部旗標不序列化。
    for (const row of rows.slice(1)) {
      expect(row.learning_content).toEqual(["歷Ka-Ⅳ-1"]);
      expect(row.learning_performance).toEqual(["社1a-Ⅳ-1"]);
    }
    for (const row of rows) {
      expect(row).not.toHaveProperty("_lcWasAutoDrawn");
      expect(row).not.toHaveProperty("_lpWasAutoDrawn");
    }
  });
});
