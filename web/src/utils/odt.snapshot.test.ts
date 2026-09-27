/**
 * TDD tests for buildOdtFromSnapshots (issue #752).
 *
 * Covers:
 * - Draft label in content XML for draft questions
 * - Final label (no draft label) for final questions
 * - Text-only 題組 (shared text but no surviving subquestions) preserved as 題組
 * - Skipped subquestion numbering (1, 3 — gap at 2) preserved
 * - Known-missing subquestion marker at correct position
 * - known-missing image marker at correct position
 * - Final with no terminal evidence → final receipt + unknown processing (not relabeled as draft)
 * - Processing/delivery/review stated separately
 * - PNG images embedded in Pictures/ from imageSources, referenced at correct position
 * - chart_spec_preview → placeholder text (TODO #753)
 * - New revision arriving during export: snapshot is immutable (verified structurally)
 * - Batch: hasDraft = true drives batch filename (verified via singleQuestionOdtFilename/batchOdtFilename)
 * - Legacy/unknown-order items: positionUnknown reflected in _export.index = null
 * - OdtBuildError thrown on invalid base64 in imageSources
 */

import JSZip from "jszip";
import { describe, expect, it } from "vitest";

import type { ExamQuestion, SubQuestion } from "../hooks/useGenerate";
import type { QuestionSnapshot } from "./exportSnapshot";
import type { ExportMeta } from "./exportSnapshot";
import { buildOdtFromSnapshots, OdtBuildError } from "./odt";
import { singleQuestionOdtFilename, batchOdtFilename } from "./exportSnapshot";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function readContentXml(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const file = zip.file("content.xml");
  if (!file) throw new Error("content.xml missing");
  return file.async("string");
}

async function readZipPaths(blob: Blob): Promise<string[]> {
  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  return Object.keys(zip.files);
}

function makeExportMeta(overrides: Partial<ExportMeta> = {}): ExportMeta {
  return {
    format_version: 1,
    exported_at: "2026-09-27T00:00:00.000Z",
    is_draft: false,
    run_id: "run-001",
    index: 0,
    content_revision: 3,
    processing: "ended",
    termination_reason: "normal",
    delivery_status: "complete",
    missing: [],
    review: { status: "passed", content_revision: 3 },
    ...overrides,
  };
}

function makeFlatQuestion(id: string, extra: Partial<ExamQuestion> = {}): ExamQuestion {
  return {
    id,
    情境: ["個人"],
    題型種類: "single",
    題型: "選擇題",
    題目: ["這是題目"],
    正確解題分析: ["這是解析"],
    ...extra,
  };
}

function makeGroupQuestion(
  id: string,
  subquestions: SubQuestion[],
  extra: Partial<ExamQuestion> = {},
): ExamQuestion {
  return {
    id,
    情境: ["公共"],
    題型種類: "題組題",
    題型: "選擇題",
    核心問題: "核心問題",
    文本: "共用文本",
    subquestions,
    題目: ["共用文本"],
    正確解題分析: [],
    ...extra,
  };
}

function makeSubQuestion(seqNo: number, extra: Partial<SubQuestion> = {}): SubQuestion {
  return {
    id: `sq-${seqNo}`,
    序號: seqNo,
    年級: 8,
    科目: ["地理"],
    核心素養: [],
    學習內容: [],
    學習表現: [],
    出題概念: "",
    題型: "選擇題",
    題目: `第${seqNo}題題目`,
    答案: "A",
    答案解析: `第${seqNo}題解析`,
    ...extra,
  };
}

function makeSnapshot(
  question: ExamQuestion,
  metaOverrides: Partial<ExportMeta> = {},
  imageSources: QuestionSnapshot["imageSources"] = {},
): QuestionSnapshot {
  const meta = makeExportMeta(metaOverrides);
  const exported = { ...question, _export: meta };
  return {
    exported,
    captured: question,
    isDraft: meta.is_draft,
    index: meta.index,
    imageSources,
  };
}

// A minimal 1×1 PNG in base64 (3-byte white pixel)
const TINY_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg==";

// ---------------------------------------------------------------------------
// Draft label
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — draft label", () => {
  it("emits 【草稿】 label before draft question content", async () => {
    const q = makeFlatQuestion("q-draft-1");
    const snapshot = makeSnapshot(q, { is_draft: true });
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("【草稿】");
  });

  it("does NOT emit 【草稿】 for a final question", async () => {
    const q = makeFlatQuestion("q-final-1");
    const snapshot = makeSnapshot(q, { is_draft: false });
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).not.toContain("【草稿】");
  });
});

// ---------------------------------------------------------------------------
// Status labels
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — status labels", () => {
  it("shows processing, delivery and review separately", async () => {
    const q = makeFlatQuestion("q-status");
    const snapshot = makeSnapshot(q, {
      processing: "ended",
      delivery_status: "complete",
      review: { status: "passed", content_revision: 3 },
    });
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("處理：已結束");
    expect(xml).toContain("交付：完整");
    expect(xml).toContain("審題：通過");
  });

  it("final with no terminal keeps final receipt + unknown processing (not relabeled as draft)", async () => {
    // Final receipt = is_draft:false, but termination_reason/delivery_status = null → unknown
    const q = makeFlatQuestion("q-final-no-terminal");
    const snapshot = makeSnapshot(q, {
      is_draft: false,
      processing: "unknown",
      termination_reason: null,
      delivery_status: null,
      review: { status: "unknown", content_revision: null },
    });
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    // Must NOT show draft label
    expect(xml).not.toContain("【草稿】");
    // Must show unknown processing
    expect(xml).toContain("處理：處理狀態未知");
    // Must mention unknown terminal delivery
    expect(xml).toContain("未知（未收到 terminal）");
  });

  it("legacy question with all-unknown evidence shows unknown markers", async () => {
    const q = makeFlatQuestion("q-legacy");
    const snapshot = makeSnapshot(q, {
      is_draft: false,
      processing: "unknown",
      termination_reason: null,
      delivery_status: null,
      run_id: null,
      index: null,
      content_revision: null,
      review: { status: "unknown", content_revision: null },
    });
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("處理：處理狀態未知");
  });
});

// ---------------------------------------------------------------------------
// Math 題組 detection via 題型種類 (fix: isSocialStudies → isGroupQuestion)
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — math 題組 detected by 題型種類", () => {
  it("renders a math 題組 (題型種類=題組題, 0 subquestions, 0 missing) as a 題組 with 文本/核心問題", async () => {
    // Before the fix, this would render as a flat question because
    // isSocialStudies = (subquestions.length > 0) = false.
    // After the fix, isGroupQuestion = true because 題型種類 === "題組題".
    const q: ExamQuestion = {
      id: "q-math-group",
      情境: ["數學文字情境"],
      題型種類: "題組題",
      題型: "選擇題",
      核心問題: "這是數學核心問題",
      文本: "這是數學文本",
      題目: [],
      正確解題分析: [],
    };
    const snapshot = makeSnapshot(q, { delivery_status: "partial" });
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    // Must render 文本 and 核心問題 (group layout), not flat 題目/正確解題分析
    expect(xml).toContain("這是數學核心問題");
    expect(xml).toContain("這是數學文本");
    // Must NOT render the flat question structure
    expect(xml).not.toContain("正確解題分析");
  });

  it("renders a math 題組 with 題型種類=題組題 but no missing slots as 題組", async () => {
    const q: ExamQuestion = {
      id: "q-math-group-no-missing",
      情境: ["建築與藝術"],
      題型種類: "題組題",
      題型: "選擇題",
      核心問題: "幾何核心問題",
      文本: "幾何文本",
      題目: [],
      正確解題分析: [],
    };
    // No missing subquestion slots — only 題型種類 triggers group detection
    const snapshot = makeSnapshot(q, { missing: [] });
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("幾何核心問題");
    expect(xml).toContain("幾何文本");
  });
});

// ---------------------------------------------------------------------------
// Text-only 題組 (no surviving subquestions)
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — text-only 題組", () => {
  it("exports 核心問題 and 文本 even with no subquestions", async () => {
    const q = makeGroupQuestion("q-text-only", [], {
      核心問題: "文本型核心問題",
      文本: "文本內容",
    });
    // The missing list identifies that subquestion slots are missing.
    // subquestion_index is 0-based (server protocol); 序號 = index + 1.
    // slot 0 → 缺小題 1, slot 1 → 缺小題 2.
    const snapshot = makeSnapshot(q, {
      is_draft: true,
      delivery_status: "partial",
      missing: [
        { kind: "subquestion", question_id: "q-text-only", subquestion_index: 0 },
        { kind: "subquestion", question_id: "q-text-only", subquestion_index: 1 },
      ],
    });
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    // Text and core question must be present
    expect(xml).toContain("文本型核心問題");
    expect(xml).toContain("文本內容");
    // Missing subquestion markers
    expect(xml).toContain("缺小題 1");
    expect(xml).toContain("缺小題 2");
    // Draft label present
    expect(xml).toContain("【草稿】");
  });
});

// ---------------------------------------------------------------------------
// Skipped subquestion numbering (gap at 2)
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — subquestion number gaps", () => {
  it("preserves original 序號 1 and 3 with gap at 2 (missing)", async () => {
    const sq1 = makeSubQuestion(1);
    const sq3 = makeSubQuestion(3);
    const q = makeGroupQuestion("q-gap", [sq1, sq3]);
    // subquestion_index is 0-based; slot 1 (0-based) → 序號 2 (1-based).
    // Delivered are sq1 (序號=1) and sq3 (序號=3); the gap is at 序號=2.
    const snapshot = makeSnapshot(q, {
      missing: [
        { kind: "subquestion", question_id: "q-gap", subquestion_index: 1 },
      ],
    });
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("第1題");
    expect(xml).toContain("第3題");
    // Missing sq2 marker appears between them
    expect(xml).toContain("缺小題 2");
    // The marker for sq2 must appear between sq1 and sq3
    const idx1 = xml.indexOf("第1題");
    const idx2 = xml.indexOf("缺小題 2");
    const idx3 = xml.indexOf("第3題");
    expect(idx1).toBeLessThan(idx2);
    expect(idx2).toBeLessThan(idx3);
  });

  it("renders subquestions in 序號 order even if array is out of order", async () => {
    const sq3 = makeSubQuestion(3);
    const sq1 = makeSubQuestion(1);
    const q = makeGroupQuestion("q-reorder", [sq3, sq1]); // out of order
    const snapshot = makeSnapshot(q);
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    const idx1 = xml.indexOf("第1題");
    const idx3 = xml.indexOf("第3題");
    expect(idx1).toBeLessThan(idx3);
  });
});

// ---------------------------------------------------------------------------
// Known-missing items
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — known-missing markers", () => {
  it("shows 缺圖 marker for known_missing stem image", async () => {
    const q = makeFlatQuestion("q-missing-img");
    const snapshot = makeSnapshot(
      q,
      { missing: [{ kind: "image", question_id: "q-missing-img" }] },
      { stem: { kind: "known_missing", contentRevision: 3 } },
    );
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("缺圖");
  });

  it("shows 缺圖 marker for known_missing subquestion image", async () => {
    const sq1 = makeSubQuestion(1);
    const q = makeGroupQuestion("q-sq-missing-img", [sq1]);
    const snapshot = makeSnapshot(
      q,
      { missing: [{ kind: "image", question_id: "q-sq-missing-img", subquestion_index: 1 }] },
      { sq1: { kind: "known_missing", contentRevision: 3 } },
    );
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("缺圖");
    expect(xml).toContain("第1題圖片已知缺失");
  });
});

// ---------------------------------------------------------------------------
// PNG images in Pictures/
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — PNG image embedding", () => {
  it("embeds stem PNG from imageSources[stem] into Pictures/", async () => {
    const q = makeFlatQuestion("q-img");
    const snapshot = makeSnapshot(
      q,
      {},
      { stem: { kind: "png_base64", pngBase64: TINY_PNG_BASE64, contentRevision: 3 } },
    );
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const paths = await readZipPaths(blob);
    expect(paths.some((p) => p.startsWith("Pictures/"))).toBe(true);
    // Verify it references the image in content.xml
    const xml = await readContentXml(blob);
    expect(xml).toContain("Pictures/");
  });

  it("embeds per-subquestion PNG from imageSources[sq1] into Pictures/", async () => {
    const sq1 = makeSubQuestion(1);
    const q = makeGroupQuestion("q-sq-img", [sq1]);
    const snapshot = makeSnapshot(
      q,
      {},
      { sq1: { kind: "png_base64", pngBase64: TINY_PNG_BASE64, contentRevision: 3 } },
    );
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const paths = await readZipPaths(blob);
    expect(paths.some((p) => p.startsWith("Pictures/") && p.includes("_sq_"))).toBe(true);
  });

  it("does NOT embed image from question.image_base64 when imageSources is empty", async () => {
    // Simulate: question has image_base64 set (live state), but snapshot was taken without it
    const q = makeFlatQuestion("q-no-src-img", { image_base64: TINY_PNG_BASE64 });
    // imageSources is empty (capture missed the image for some reason)
    const snapshot = makeSnapshot(q, {}, {});
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const paths = await readZipPaths(blob);
    // No picture should be embedded because imageSources is empty
    expect(paths.filter((p) => p.startsWith("Pictures/"))).toHaveLength(0);
  });

  it("uses imageSources PNG even when question.image_base64 differs (revision binding)", async () => {
    // Simulate old snapshot at revision 3 with a specific image
    // but question.image_base64 has been updated to a newer version
    const oldPng = TINY_PNG_BASE64;
    const q = makeFlatQuestion("q-rev-bind", { image_base64: "different_base64" });
    const snapshot = makeSnapshot(
      q,
      { content_revision: 3 },
      { stem: { kind: "png_base64", pngBase64: oldPng, contentRevision: 3 } },
    );
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const paths = await readZipPaths(blob);
    // Should have the embedded image from imageSources
    expect(paths.some((p) => p.startsWith("Pictures/"))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// chart_spec_preview placeholder
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — chart_spec_preview placeholder", () => {
  it("emits placeholder text for chart_spec_preview stem (TODO #753)", async () => {
    const q = makeFlatQuestion("q-preview");
    const snapshot = makeSnapshot(
      q,
      {},
      { stem: { kind: "chart_spec_preview", chartSpec: { type: "bar" }, contentRevision: 3 } },
    );
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("圖片預覽待轉換");
    // No PNG in Pictures/
    const paths = await readZipPaths(blob);
    expect(paths.filter((p) => p.startsWith("Pictures/"))).toHaveLength(0);
  });

  it("emits placeholder text for chart_spec_preview on subquestion (TODO #753)", async () => {
    const sq1 = makeSubQuestion(1);
    const q = makeGroupQuestion("q-sq-preview", [sq1]);
    const snapshot = makeSnapshot(
      q,
      {},
      { sq1: { kind: "chart_spec_preview", chartSpec: { type: "pie" }, contentRevision: 3 } },
    );
    const blob = await buildOdtFromSnapshots("test", [snapshot]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("圖片預覽待轉換");
  });
});

// ---------------------------------------------------------------------------
// Filename helpers
// ---------------------------------------------------------------------------

describe("ODT filename helpers", () => {
  it("singleQuestionOdtFilename: draft gets 草稿_ prefix", () => {
    expect(singleQuestionOdtFilename("q123", true)).toBe("草稿_q123.odt");
  });

  it("singleQuestionOdtFilename: final has no prefix", () => {
    expect(singleQuestionOdtFilename("q123", false)).toBe("q123.odt");
  });

  it("singleQuestionOdtFilename: empty id uses 'question' fallback", () => {
    expect(singleQuestionOdtFilename("", true)).toBe("草稿_question.odt");
  });

  it("batchOdtFilename: hasDraft gives 含草稿_ prefix", () => {
    const name = batchOdtFilename(true);
    expect(name).toMatch(/^含草稿_batch_/);
    expect(name).toMatch(/\.odt$/);
  });

  it("batchOdtFilename: all final has no prefix", () => {
    const name = batchOdtFilename(false);
    expect(name).toMatch(/^batch_/);
    expect(name).toMatch(/\.odt$/);
  });
});

// ---------------------------------------------------------------------------
// Batch snapshot: hasDraft, ordering
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — batch", () => {
  it("exports multiple questions in order, adds PageBreak between them", async () => {
    const q1 = makeFlatQuestion("q-batch-1");
    const q2 = makeFlatQuestion("q-batch-2");
    const snap1 = makeSnapshot(q1, { index: 0 });
    const snap2 = makeSnapshot(q2, { index: 1 });
    const blob = await buildOdtFromSnapshots("Batch Title", [snap1, snap2]);
    const xml = await readContentXml(blob);
    expect(xml).toContain("Batch Title");
    expect(xml).toContain("Question 1");
    expect(xml).toContain("Question 2");
    expect(xml).toContain("PageBreak");
  });

  it("batch with mixed draft/final includes draft label only on draft question", async () => {
    const q1 = makeFlatQuestion("q-mixed-draft");
    const q2 = makeFlatQuestion("q-mixed-final");
    const snap1 = makeSnapshot(q1, { is_draft: true, index: 0 });
    const snap2 = makeSnapshot(q2, { is_draft: false, index: 1 });
    const blob = await buildOdtFromSnapshots("Mixed", [snap1, snap2]);
    const xml = await readContentXml(blob);
    // draft label appears exactly once
    const occurrences = (xml.match(/【草稿】/g) ?? []).length;
    expect(occurrences).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// OdtBuildError on invalid base64 in imageSources
// ---------------------------------------------------------------------------

describe("buildOdtFromSnapshots — error handling", () => {
  it("throws OdtBuildError when imageSources contains invalid base64", async () => {
    const q = makeFlatQuestion("q-bad-b64");
    const snapshot = makeSnapshot(
      q,
      {},
      { stem: { kind: "png_base64", pngBase64: "not valid base64 *", contentRevision: 3 } },
    );
    await expect(buildOdtFromSnapshots("test", [snapshot])).rejects.toBeInstanceOf(OdtBuildError);
    await expect(buildOdtFromSnapshots("test", [snapshot])).rejects.toMatchObject({
      questionIndex: 0,
    });
  });
});
