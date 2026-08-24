import JSZip from "jszip";
import { describe, expect, it } from "vitest";

import type { DragDropSpec, ExamQuestion, SliderSpec, SubQuestion } from "../hooks/useGenerate";
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
    expect(metadataLines).toContain(`8年級 ｜ 選擇題 ｜ 地理 ｜ ${knowing}`);
    expect(metadataLines).toContain(`9年級 ｜ 選擇題 ｜ 公民 ｜ ${reasoning}`);
  });

  it("renders native and legacy rubric codes plus a retired legacy type as text", async () => {
    const sub: SubQuestion = {
      id: "legacy-rubric-sq1", 序號: 1, 年級: 8, 科目: ["地理"], 核心素養: [], 學習內容: [], 學習表現: [],
      出題概念: "", 題型: "封閉式建構反應題", 題目: "Q?", 答案: "B", 答案解析: "explain",
      評分規準: [
        { code: "0", 規準說明: "No credit" },
        { code: "1", 規準說明: "Partial credit" },
        { code: "2", 規準說明: "Legacy full credit" },
        { code: "3", 規準說明: "Native advanced" },
        { code: "0X", 規準說明: "Legacy unanswered" },
      ],
    };
    const question: ExamQuestion = {
      id: "legacy-rubric-ss1", 情境: ["公共"], 題型種類: "題組題", 題型: "選擇題",
      核心問題: "c", 文本: "p", subquestions: [sub], 題目: ["p", "Q?"], 正確解題分析: ["B"],
    };

    const xml = await readContentXml(await buildExamOdt("t", [question]));

    for (const text of [
      "封閉式建構反應題", "[0] No credit", "[1] Partial credit", "[2] Legacy full credit",
      "[3] Native advanced", "[0X] Legacy unanswered",
    ]) {
      expect(xml).toContain(text);
    }
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
      <text:p text:style-name="MetaLine">8年級 ｜ 選擇題 ｜ 地理</text:p>
      <text:p text:style-name="Standard">Q?</text:p>
      <text:p text:style-name="MetaLine">答案：B</text:p>
      <text:p text:style-name="MetaLine">解析：explain</text:p>
    </office:text>
  </office:body>
</office:document-content>`);
    expect(xml).not.toContain("內容領域");
    expect(xml).not.toContain("認知歷程");
    expect(xml).not.toContain("undefined");
    expect(xml).not.toContain("以下互動題目未列入紙本輸出");
  });
});

describe("buildExamOdt interactive subquestions", () => {
  it("omits interactive items and appends a web-viewer manifest", async () => {
    const makeSubQuestion = (
      sequence: number,
      type: string,
      text: string,
      interaction?: DragDropSpec | SliderSpec,
    ): SubQuestion => ({
      id: `interactive-sq${sequence}`,
      序號: sequence,
      年級: 8,
      科目: ["地理"],
      核心素養: [],
      學習內容: [],
      學習表現: [],
      出題概念: "",
      題型: type,
      題目: text,
      答案: "答案",
      答案解析: "解析",
      ...(interaction ? { interaction } : {}),
    });
    const question: ExamQuestion = {
      id: "interactive-ss1",
      情境: ["公共"],
      題型種類: "題組題",
      題型: "選擇題",
      核心問題: "核心問題",
      文本: "文本",
      subquestions: [
        makeSubQuestion(1, "選擇題", "紙本小題一"),
        makeSubQuestion(2, "拖放題", "拖放互動題目不應出現在 ODT", {
          draggables: [{ id: "d1", label: "拖曳項目" }],
          targets: [{ id: "t1", label: "放置目標", capacity: 1 }],
          correct_mapping: { d1: "t1" },
          exact_match: true,
          shuffle_draggables: false,
        }),
        makeSubQuestion(3, "選擇題", "紙本小題三"),
        makeSubQuestion(4, "滑桿題", "滑桿互動題目不應出現在 ODT", {
          min: 0,
          max: 100,
          step: 1,
          unit: "%",
          correct_value: 75,
          tolerance: 5,
          show_ticks: true,
        }),
        makeSubQuestion(5, "選擇題", "紙本小題五"),
      ],
      題目: ["文本", "紙本小題一", "拖放互動題目不應出現在 ODT", "紙本小題三", "滑桿互動題目不應出現在 ODT", "紙本小題五"],
      正確解題分析: ["答案"],
    };

    const xml = await readContentXml(await buildExamOdt("t", [question]));
    const manifest = "以下互動題目未列入紙本輸出，請於網頁檢視器作答：第2小題（拖放題）、第4小題（滑桿題）";

    expect(xml).toContain("紙本小題一");
    expect(xml).toContain("紙本小題三");
    expect(xml).toContain("紙本小題五");
    expect(xml).not.toContain("拖放互動題目不應出現在 ODT");
    expect(xml).not.toContain("滑桿互動題目不應出現在 ODT");
    expect(xml).toContain(manifest);
    expect(xml.indexOf("紙本小題五")).toBeLessThan(xml.indexOf(manifest));
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
