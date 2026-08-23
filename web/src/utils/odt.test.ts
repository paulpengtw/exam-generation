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

function readMetadataLines(xml: string): string[] {
  return [...xml.matchAll(/<text:p text:style-name="MetaLine">([^<]*)<\/text:p>/g)]
    .map((match) => match[1]);
}

describe("buildExamOdt ICCS metadata", () => {
  it("emits ICCS tags for new social-studies records", async () => {
    const knowing = "Knowing–Defining and Describing";
    const reasoning = "Reasoning and Applying–Interpret information";
    const firstSub: SubQuestion & { 認知歷程: string } = {
      id: "iccs-sq1", 序號: 1, 年級: 8, 科目: ["地理"], 核心素養: [], 學習內容: [], 學習表現: [],
      出題概念: "", 題型: "選擇題", 題目: "第一小題", 答案: "A", 答案解析: "解析一",
      認知歷程: knowing,
    };
    const secondSub: SubQuestion & { 認知歷程: string } = {
      id: "iccs-sq2", 序號: 2, 年級: 9, 科目: ["公民"], 核心素養: [], 學習內容: [], 學習表現: [],
      出題概念: "", 題型: "選擇題", 題目: "第二小題", 答案: "B", 答案解析: "解析二",
      認知歷程: reasoning,
    };
    const question: ExamQuestion & { 內容領域: string; 認知歷程: string[] } = {
      id: "iccs-ss1", 情境: ["公共"], 題型種類: "題組題", 題型: "選擇題",
      內容領域: "Civic Principles", 認知歷程: [knowing, reasoning],
      核心問題: "核心問題", 文本: "文本", subquestions: [firstSub, secondSub],
      題目: ["文本", "第一小題", "第二小題"], 正確解題分析: ["A", "B"],
    };

    const blob = await buildExamOdt("t", [question]);
    const metadataLines = readMetadataLines(await readContentXml(blob));

    expect(metadataLines.some((line) =>
      line.includes("Civic Principles") && line.includes(knowing) && line.includes(reasoning),
    )).toBe(true);
    expect(metadataLines).toContain(`8年級 ｜ 地理 ｜ ${knowing}`);
    expect(metadataLines).toContain(`9年級 ｜ 公民 ｜ ${reasoning}`);
  });

  it("keeps legacy social-studies ODT metadata byte-identical without ICCS fields", async () => {
    const sub: SubQuestion = {
      id: "legacy-sq1", 序號: 1, 年級: 8, 科目: ["地理"], 核心素養: [], 學習內容: [], 學習表現: [],
      出題概念: "", 題型: "選擇題", 題目: "Q?", 答案: "B", 答案解析: "explain",
    };
    const question: ExamQuestion = {
      id: "legacy-ss1", 情境: ["公共"], 題型種類: "題組題", 題型: "選擇題",
      核心問題: "c", 文本: "p", subquestions: [sub], 題目: ["p", "Q?"], 正確解題分析: ["B"],
    };

    const blob = await buildExamOdt("t", [question]);
    const xml = await readContentXml(blob);

    expect(xml).toBe(`<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
  office:version="1.3">
  <office:body>
    <office:text>
      <text:p text:style-name="MetaLine">8年級 ｜ 地理</text:p>
      <text:p text:style-name="Heading2">核心問題</text:p>
      <text:p text:style-name="Standard">c</text:p>
      <text:p text:style-name="Heading2">文本</text:p>
      <text:p text:style-name="Standard">p</text:p>
      <text:p text:style-name="Heading2">第1題</text:p>
      <text:p text:style-name="MetaLine">8年級 ｜ 地理</text:p>
      <text:p text:style-name="Standard">Q?</text:p>
      <text:p text:style-name="MetaLine">答案：B</text:p>
      <text:p text:style-name="MetaLine">解析：explain</text:p>
    </office:text>
  </office:body>
</office:document-content>`);
    expect(xml).not.toContain("內容領域");
    expect(xml).not.toContain("認知歷程");
    expect(xml).not.toContain("undefined");
  });
});

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
