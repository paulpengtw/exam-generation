import JSZip from "jszip";
import { describe, expect, it } from "vitest";

import type { ExamQuestion, SubQuestion } from "../hooks/useGenerate";
import { buildExamOdt } from "./odt";

async function readContentXml(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const file = zip.file("content.xml");
  if (!file) throw new Error("content.xml missing");
  return file.async("string");
}

describe("buildExamOdt distractor section", () => {
  it("emits 誘答分析 rows under a subquestion 解析 for SS/NS", async () => {
    const sub: SubQuestion = {
      id: "sq1", 序號: 1, 年級: 8, 科目: ["地理"], 核心素養: [], 學習內容: [], 學習表現: [],
      出題概念: "", 題型: "選擇題", 題目: "Q?", 答案: "B", 答案解析: "explain",
      評分規準: [], 誘答分析: { A: "trap-A", B: "正確答案：B。" },
    };
    const q: ExamQuestion = {
      id: "ss1", 情境: ["公共"], 題型種類: "題組題", 題型: "選擇題",
      核心問題: "c", 文本: "p", subquestions: [sub], 題目: ["p", "Q?"], 正確解題分析: ["B"],
    };
    const blob = await buildExamOdt("t", [q]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("誘答分析");
    expect(xml).toContain("[A]");
    expect(xml).toContain("trap-A");
    expect(xml).toContain("[B]");
    expect(xml).toContain("正確答案：B。");
  });

  it("emits 誘答分析 rows under 正確解題分析 for math flat questions", async () => {
    const q: ExamQuestion = {
      id: "m1", 情境: ["個人"], 題型種類: "單一題", 題型: "選擇題",
      題目: ["Q? (A) 3 (B) 4"], 正確解題分析: ["B is correct."],
      誘答分析: { A: "trap-A", B: "正確答案：4。" },
    };
    const blob = await buildExamOdt("t", [q]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("誘答分析");
    expect(xml).toContain("[A]");
    expect(xml).toContain("正確答案：4。");
  });

  it("omits the block entirely when 誘答分析 is missing or empty", async () => {
    const q: ExamQuestion = {
      id: "m2", 情境: ["個人"], 題型種類: "單一題", 題型: "選擇題",
      題目: ["Q?"], 正確解題分析: ["A"],
    };
    const blob = await buildExamOdt("t", [q]);
    const xml = await readContentXml(blob);
    expect(xml).not.toContain("誘答分析");
  });
});
