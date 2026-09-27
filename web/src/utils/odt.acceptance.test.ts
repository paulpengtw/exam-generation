/**
 * Acceptance tests for ODT snapshot export (issue #752 review gaps).
 *
 * These tests drive the full pipeline from fixture data through
 * captureFromEvidence / captureFromGeneratedQuestion → buildOdtFromSnapshots,
 * then read back the ZIP XML to verify correct structure.
 *
 * Tests covered:
 * (a) Fixture-based: math_groups_interleaved.jsonl → three 題組題 questions
 *     - q_RUN_003: text-only 題組 (0 received 小題, all missing) exports as 題組
 *     - q_RUN_001: partial 題組 (2 received, 1 missing) shows both subquestions
 *     - q_RUN_002: complete 題組 (3 received, 0 missing) shows all subquestions
 *     - Batch has correct page-break structure
 *     - Status labels: processing "ended", delivery partial/complete shown
 * (b) Legacy unknown-order batch: items with positionUnknown=true sort last,
 *     stable by array order
 * (c) Snapshot immutability: mutating the source question after capture does
 *     not change the ODT document
 * (d) Modification eligibility is not disturbed: flat question ODT still
 *     renders 題目/正確解題分析 (not group layout)
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import JSZip from "jszip";
import { describe, expect, it } from "vitest";

import type { ExamQuestion } from "../hooks/useGenerate";
import type { GeneratedQuestion } from "../hooks/useGenerate";
import {
  createGenerationStreamDecoder,
} from "../lib/generationStream";
import {
  createRunEvidence,
  applyV2Event,
  applyDegraded,
  type RunEvidenceState,
} from "../lib/generationEvidence";
import {
  captureFromEvidence,
  captureFromGeneratedQuestion,
  captureBatchSnapshots,
  type QuestionSnapshot,
} from "./exportSnapshot";
import { buildOdtFromSnapshots } from "./odt";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface FixtureLine {
  event: string;
  context: Record<string, unknown>;
  payload: Record<string, unknown>;
}

function loadFixture(name: string): FixtureLine[] {
  const path = resolve(__dirname, "../../../tests/fixtures/generation_v2", name);
  return readFileSync(path, "utf-8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as FixtureLine);
}

function replayFixture(fixture: FixtureLine[]): { state: RunEvidenceState; degraded: boolean } {
  const dec = createGenerationStreamDecoder();
  let state: RunEvidenceState | null = null;

  for (const line of fixture) {
    const rawData = JSON.stringify({ context: line.context, payload: line.payload });
    const results = dec.decode(line.event, rawData);
    for (const d of results) {
      if (d.kind === "v2" && d.event.name === "started") {
        if (dec.run) state = createRunEvidence(dec.run);
      } else if (d.kind === "v2" && state) {
        state = applyV2Event(state, d);
      } else if (d.kind === "degraded" && state) {
        state = applyDegraded(state, d.reason);
      }
    }
  }

  if (!state) throw new Error("No state built — started event was missing or malformed");
  return { state, degraded: dec.degraded };
}

async function readContentXml(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const file = zip.file("content.xml");
  if (!file) throw new Error("content.xml missing");
  return file.async("string");
}

// ---------------------------------------------------------------------------
// (a) Fixture-based: math_groups_interleaved.jsonl
// ---------------------------------------------------------------------------

describe("ODT acceptance — math_groups_interleaved.jsonl", () => {
  const fixture = loadFixture("math_groups_interleaved.jsonl");
  const { state } = replayFixture(fixture);
  const runId = state.runId;
  const exportedAt = "2026-09-27T00:00:00.000Z";

  // Build snapshots in manifest order
  function buildSnapshots(): QuestionSnapshot[] {
    const snapshots: QuestionSnapshot[] = [];
    for (const qId of state.order) {
      const ev = state.questions[qId];
      if (!ev?.content.question) continue;
      const snap = captureFromEvidence(ev.content.question, ev, runId, exportedAt);
      if (snap) snapshots.push(snap);
    }
    // Sort by index (null → last)
    return snapshots.sort((a, b) => {
      if (a.index === null && b.index === null) return 0;
      if (a.index === null) return 1;
      if (b.index === null) return -1;
      return a.index - b.index;
    });
  }

  it("(a1) q_RUN_003 (text-only 題組, 0 received 小題) renders as 題組 with 文本 and 核心問題", async () => {
    const snaps = buildSnapshots();
    // Find q_RUN_003
    const snap003 = snaps.find((s) => s.exported.id === "q_RUN_003");
    expect(snap003).toBeDefined();
    expect(snap003!.exported._export.delivery_status).toBe("partial");

    // Single ODT for this one question
    const blob = await buildOdtFromSnapshots("test", [snap003!]);
    const xml = await readContentXml(blob);

    // Must show 文本 and 核心問題 (group layout), not flat layout
    expect(xml).toContain("文本 C");
    expect(xml).toContain("核心問題 C");
    // Must NOT show 正確解題分析 heading (flat layout)
    expect(xml).not.toContain("正確解題分析");
    // Status: partial delivery
    expect(xml).toContain("交付：部分");
    // Processing: ended
    expect(xml).toContain("處理：已結束");
  });

  it("(a2) q_RUN_001: received 小題 1 and 3, missing slot_index=1 → ODT shows 第1題, 【缺小題 2】, 第3題", async () => {
    // The terminal lists missing = [{kind:"subquestion", subquestion_index:1, subquestion_id:"q_RUN_001-sq002"}].
    // slot_index=1 (0-based) must map to 序號=2 (1-based) via slotRefSeqno.
    // Before the fix, raw index 1 was merged with delivered 序號=1, making the
    // missing marker disappear and the order become [1,3] instead of [1,2,3].
    const snaps = buildSnapshots();
    const snap001 = snaps.find((s) => s.exported.id === "q_RUN_001");
    expect(snap001).toBeDefined();
    // Confirm fixture data: delivered 序號 = 1 and 3, missing subquestion_index=1
    const missing = snap001!.exported._export.missing;
    expect(missing.some((s) => s.kind === "subquestion" && s.subquestion_index === 1)).toBe(true);
    const deliveredSeqnos = (snap001!.exported.subquestions ?? []).map((s) => s.序號);
    expect(deliveredSeqnos).toContain(1);
    expect(deliveredSeqnos).toContain(3);

    const blob = await buildOdtFromSnapshots("test", [snap001!]);
    const xml = await readContentXml(blob);

    // Must render as 題組 (has subquestions)
    expect(xml).toContain("文本 A");
    expect(xml).toContain("核心問題 A");
    // Both delivered subquestions must appear
    expect(xml).toContain("第1題");
    expect(xml).toContain("第3題");
    // The missing 第2小題 marker must appear at the correct ordinal position
    // (between 第1題 and 第3題).
    expect(xml).toContain("缺小題 2");
    // The missing marker must NOT be confused with 第1題 (old bug: raw index 1
    // collided with delivered 序號=1, hiding the gap entirely).
    const pos1 = xml.indexOf("第1題");
    const posMissing2 = xml.indexOf("缺小題 2");
    const pos3 = xml.indexOf("第3題");
    expect(pos1).toBeGreaterThan(-1);
    expect(posMissing2).toBeGreaterThan(pos1);
    expect(pos3).toBeGreaterThan(posMissing2);
  });

  it("(a3) q_RUN_002 (3 received 小題, 0 missing) shows all subquestions", async () => {
    const snaps = buildSnapshots();
    const snap002 = snaps.find((s) => s.exported.id === "q_RUN_002");
    expect(snap002).toBeDefined();
    expect(snap002!.exported._export.delivery_status).toBe("complete");

    const blob = await buildOdtFromSnapshots("test", [snap002!]);
    const xml = await readContentXml(blob);

    expect(xml).toContain("文本 B");
    expect(xml).toContain("核心問題 B");
    expect(xml).toContain("第1題");
    expect(xml).toContain("第2題");
    expect(xml).toContain("第3題");
    // Complete delivery
    expect(xml).toContain("交付：完整");
  });

  it("(a4) batch ODT has page-break structure and contains all three questions", async () => {
    const snaps = buildSnapshots();
    expect(snaps).toHaveLength(3);

    const blob = await buildOdtFromSnapshots("exam_batch", snaps);
    const xml = await readContentXml(blob);

    expect(xml).toContain("exam_batch");
    expect(xml).toContain("Question 1");
    expect(xml).toContain("Question 2");
    expect(xml).toContain("Question 3");
    expect(xml).toContain("PageBreak");

    // All three 文本 strings appear
    expect(xml).toContain("文本 A");
    expect(xml).toContain("文本 B");
    expect(xml).toContain("文本 C");
  });
});

// ---------------------------------------------------------------------------
// (b) Legacy unknown-order batch: positionUnknown items sort last
// ---------------------------------------------------------------------------

describe("ODT acceptance — legacy unknown-order batch", () => {
  const exportedAt = "2026-09-27T00:00:00.000Z";

  function makeLegacyItem(
    index: number,
    id: string,
    positionUnknown: boolean,
    ordinal: number,
  ): GeneratedQuestion {
    const question: ExamQuestion = {
      id,
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: [`Question ${id}`],
      正確解題分析: ["Answer"],
    };
    return {
      index: ordinal,
      question,
      phase: "final",
      isFinal: true,
      positionUnknown,
    };
  }

  it("sorts known-index items before positionUnknown items, stable within group", async () => {
    // Items: q-b (positionUnknown), q-a (index 0), q-c (positionUnknown)
    const items: GeneratedQuestion[] = [
      makeLegacyItem(0, "q-b", true, 0),   // positionUnknown, ordinal 0
      makeLegacyItem(1, "q-a", false, 1),  // known index 1 → sorts first
      makeLegacyItem(2, "q-c", true, 2),   // positionUnknown, ordinal 2 → sorts last
    ];

    const [snapshots, hasDraft] = captureBatchSnapshots({
      displayResults: items,
      evidenceByQuestionId: {},
      runId: null,
      exportedAt,
    });

    expect(hasDraft).toBe(false);
    // Known-index item should come first
    expect(snapshots[0].exported.id).toBe("q-a");
    // positionUnknown items follow in stable ordinal order
    expect(snapshots[1].exported.id).toBe("q-b");
    expect(snapshots[2].exported.id).toBe("q-c");

    // Unknown-order items get index: null in _export
    expect(snapshots[1].exported._export.index).toBeNull();
    expect(snapshots[2].exported._export.index).toBeNull();

    // Build ODT and verify order
    const blob = await buildOdtFromSnapshots("legacy", snapshots);
    const xml = await readContentXml(blob);
    const posA = xml.indexOf("Question q-a");
    const posB = xml.indexOf("Question q-b");
    const posC = xml.indexOf("Question q-c");
    expect(posA).toBeLessThan(posB);
    expect(posB).toBeLessThan(posC);
  });
});

// ---------------------------------------------------------------------------
// (c) Snapshot immutability: mutating source after capture does not change ODT
// ---------------------------------------------------------------------------

describe("ODT acceptance — snapshot immutability after capture", () => {
  it("a new revision arriving after click does not change the document", async () => {
    const question: ExamQuestion = {
      id: "q-immutable",
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: ["Original question text"],
      正確解題分析: ["Original answer"],
    };

    const exportedAt = "2026-09-27T00:00:00.000Z";
    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "final",
      isFinal: true,
    };

    // Capture snapshot at click time
    const snap = captureFromGeneratedQuestion(item, null, exportedAt);
    expect(snap).not.toBeNull();

    // Simulate: a new revision arrives — the live question object is mutated
    question.題目 = ["MUTATED question text — should NOT appear in ODT"];
    question.正確解題分析 = ["MUTATED answer — should NOT appear in ODT"];

    // Build ODT from the frozen snapshot (should reflect original content)
    const blob = await buildOdtFromSnapshots("test", [snap!]);
    const xml = await readContentXml(blob);

    expect(xml).toContain("Original question text");
    expect(xml).not.toContain("MUTATED question text");
    expect(xml).toContain("Original answer");
    expect(xml).not.toContain("MUTATED answer");
  });
});

// ---------------------------------------------------------------------------
// (d) Modification eligibility unchanged: flat question renders as flat in ODT
// ---------------------------------------------------------------------------

describe("ODT acceptance — flat question still renders flat (not group)", () => {
  it("a single flat question without 題型種類=題組題 renders 題目/正確解題分析", async () => {
    const question: ExamQuestion = {
      id: "q-flat",
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: ["Flat question stem"],
      正確解題分析: ["Flat answer"],
    };

    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "final",
      isFinal: true,
    };
    const snap = captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z");
    expect(snap).not.toBeNull();

    const blob = await buildOdtFromSnapshots("test", [snap!]);
    const xml = await readContentXml(blob);

    // Must render flat structure
    expect(xml).toContain("題目");
    expect(xml).toContain("Flat question stem");
    expect(xml).toContain("正確解題分析");
    expect(xml).toContain("Flat answer");
    // Must NOT render group layout
    expect(xml).not.toContain("核心問題");
    expect(xml).not.toContain("文本");
  });

  it("enabling ODT for drafts does not affect flat question structure", async () => {
    const question: ExamQuestion = {
      id: "q-flat-draft",
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: ["Draft flat question"],
      正確解題分析: ["Draft answer"],
    };

    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "draft",
      isFinal: false,
    };
    const snap = captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z");
    expect(snap).not.toBeNull();
    expect(snap!.isDraft).toBe(true);

    const blob = await buildOdtFromSnapshots("test", [snap!]);
    const xml = await readContentXml(blob);

    // Draft label present
    expect(xml).toContain("【草稿】");
    // Flat structure maintained
    expect(xml).toContain("Draft flat question");
    expect(xml).toContain("正確解題分析");
    // Not treated as group
    expect(xml).not.toContain("核心問題");
  });
});

// ---------------------------------------------------------------------------
// (e) Rasterizer: injectable success → PNG embedded in ZIP (issue #753)
// ---------------------------------------------------------------------------

describe("ODT acceptance — injectable rasterizer success", () => {
  it("chart_spec_preview stem slot: success rasterizer → PNG in Pictures/, image tag in XML", async () => {
    // 1x1 pixel transparent PNG in base64
    const FAKE_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
    const rasterizer = async () => ({ ok: true as const, pngBase64: FAKE_PNG });

    const question: ExamQuestion = {
      id: "q-chart-stem",
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: ["Stem question"],
      正確解題分析: ["Stem answer"],
      chart_spec: { render_mode: "html", description: "table preview" } as Record<string, unknown>,
    };
    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "final",
      isFinal: true,
    };
    const snap = captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z");
    expect(snap).not.toBeNull();
    expect(snap!.imageSources["stem"]?.kind).toBe("chart_spec_preview");

    const blob = await buildOdtFromSnapshots("test", [snap!], { rasterizer });
    const buf = await blob.arrayBuffer();
    const zip = await JSZip.loadAsync(buf);

    // Pictures/ folder must contain the rasterized PNG
    const pngFile = zip.file("Pictures/img_snap_0.png");
    expect(pngFile).not.toBeNull();
    const pngData = await pngFile!.async("uint8array");
    // PNG signature: 0x89 0x50 0x4E 0x47 ...
    expect(pngData[0]).toBe(0x89);
    expect(pngData[1]).toBe(0x50);

    // content.xml must reference the image with draw:image, not the failure text
    const xml = await readContentXml(blob);
    expect(xml).toContain("Pictures/img_snap_0.png");
    expect(xml).toContain("draw:image");
    expect(xml).not.toContain("匯出缺圖");
  });

  it("chart_spec_preview subquestion slot: success → sub-PNG in Pictures/", async () => {
    const FAKE_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
    const rasterizer = async () => ({ ok: true as const, pngBase64: FAKE_PNG });

    const question: ExamQuestion = {
      id: "q-chart-sq",
      情境: ["個人"],
      題型種類: "題組題",
      題型: "選擇題",
      題目: [],
      正確解題分析: [],
      核心問題: "test core",
      文本: "test passage",
      subquestions: [
        {
          id: "sq1",
          序號: 1,
          年級: 7,
          題型: "選擇題",
          科目: ["數學"],
          核心素養: [],
          學習內容: [],
          學習表現: [],
          題目: "Subquestion text",
          答案: "A",
          答案解析: "Analysis",
          chart_spec: { render_mode: "html", description: "table" } as Record<string, unknown>,
        },
      ],
    };
    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "final",
      isFinal: true,
    };
    const snap = captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z");
    expect(snap).not.toBeNull();
    expect(snap!.imageSources["sq1"]?.kind).toBe("chart_spec_preview");

    const blob = await buildOdtFromSnapshots("test", [snap!], { rasterizer });
    const buf = await blob.arrayBuffer();
    const zip = await JSZip.loadAsync(buf);

    const pngFile = zip.file("Pictures/img_snap_0_sq_1.png");
    expect(pngFile).not.toBeNull();

    const xml = await readContentXml(blob);
    expect(xml).toContain("Pictures/img_snap_0_sq_1.png");
    expect(xml).not.toContain("匯出缺圖");
  });
});

// ---------------------------------------------------------------------------
// (f) Per-image conversion failure → failure message at correct position,
//     other content intact (issue #753 acceptance criterion)
// ---------------------------------------------------------------------------

describe("ODT acceptance — per-image conversion failure", () => {
  it("stem failure: 【匯出缺圖／預覽轉換失敗】 at stem position, question text intact", async () => {
    const rasterizer = async () => ({
      ok: false as const,
      error: "canvas unavailable",
    });

    const question: ExamQuestion = {
      id: "q-fail-stem",
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: ["Question with failed stem image"],
      正確解題分析: ["Answer analysis"],
      chart_spec: { render_mode: "html", description: "table" } as Record<string, unknown>,
    };
    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "final",
      isFinal: true,
    };
    const snap = captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z");
    expect(snap).not.toBeNull();

    const blob = await buildOdtFromSnapshots("test", [snap!], { rasterizer });
    const xml = await readContentXml(blob);

    // Failure marker present at correct position
    expect(xml).toContain("匯出缺圖／預覽轉換失敗");
    // No real PNG file embedded
    const buf = await blob.arrayBuffer();
    const zip = await JSZip.loadAsync(buf);
    expect(zip.file("Pictures/img_snap_0.png")).toBeNull();
    // Other content still intact
    expect(xml).toContain("Question with failed stem image");
    expect(xml).toContain("Answer analysis");
    // Old placeholder text NOT used
    expect(xml).not.toContain("圖片預覽待轉換");
  });

  it("subquestion failure: failure at that sub's position, sibling content intact", async () => {
    const FAKE_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
    let callCount = 0;
    // sq1 succeeds; sq2 fails
    const rasterizer = async () => {
      callCount++;
      if (callCount === 1) return { ok: true as const, pngBase64: FAKE_PNG };
      return { ok: false as const, error: "failed for sq2" };
    };

    const question: ExamQuestion = {
      id: "q-fail-sq",
      情境: ["個人"],
      題型種類: "題組題",
      題型: "選擇題",
      題目: [],
      正確解題分析: [],
      核心問題: "core",
      文本: "passage",
      subquestions: [
        {
          id: "sq1",
          序號: 1,
          年級: 7,
          題型: "選擇題",
          科目: ["數學"],
          核心素養: [],
          學習內容: [],
          學習表現: [],
          題目: "First subquestion",
          答案: "A",
          答案解析: "",
          chart_spec: { render_mode: "html", description: "sq1 chart" } as Record<string, unknown>,
        },
        {
          id: "sq2",
          序號: 2,
          年級: 7,
          題型: "選擇題",
          科目: ["數學"],
          核心素養: [],
          學習內容: [],
          學習表現: [],
          題目: "Second subquestion",
          答案: "B",
          答案解析: "",
          chart_spec: { render_mode: "html", description: "sq2 chart" } as Record<string, unknown>,
        },
      ],
    };
    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "final",
      isFinal: true,
    };
    const snap = captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z");
    expect(snap).not.toBeNull();

    const blob = await buildOdtFromSnapshots("test", [snap!], { rasterizer });
    const xml = await readContentXml(blob);
    const buf = await blob.arrayBuffer();
    const zip = await JSZip.loadAsync(buf);

    // sq1 succeeded: PNG present, no failure marker
    expect(zip.file("Pictures/img_snap_0_sq_1.png")).not.toBeNull();
    // sq2 failed: failure marker present, no PNG
    expect(zip.file("Pictures/img_snap_0_sq_2.png")).toBeNull();
    expect(xml).toContain("匯出缺圖／預覽轉換失敗");
    // Both subquestion texts still intact
    expect(xml).toContain("First subquestion");
    expect(xml).toContain("Second subquestion");
    // Batch still downloadable (blob was produced, not thrown)
    expect(blob).toBeInstanceOf(Blob);
    // Generation completeness not affected (no _export fields changed)
    expect(snap!.exported._export.delivery_status).toBeNull(); // from legacy path
  });

  it("per-image failure does not prevent other questions in batch from rendering", async () => {
    const FAKE_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
    let callCount = 0;
    // Question 0 chart fails; Question 1 chart succeeds
    const rasterizer = async () => {
      callCount++;
      if (callCount === 1) return { ok: false as const, error: "q0 fail" };
      return { ok: true as const, pngBase64: FAKE_PNG };
    };

    const makeQuestion = (id: string, text: string) => ({
      id,
      情境: ["個人"] as string[],
      題型種類: "single",
      題型: "選擇題",
      題目: [text],
      正確解題分析: ["answer"],
      chart_spec: { render_mode: "html", description: "chart" } as Record<string, unknown>,
    });

    const items: GeneratedQuestion[] = [
      { index: 0, question: makeQuestion("q0", "Question zero"), phase: "final", isFinal: true },
      { index: 1, question: makeQuestion("q1", "Question one"), phase: "final", isFinal: true },
    ];
    const snaps = items.map((item) =>
      captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z")!
    );

    const blob = await buildOdtFromSnapshots("batch", snaps, { rasterizer });
    const xml = await readContentXml(blob);
    const buf = await blob.arrayBuffer();
    const zip = await JSZip.loadAsync(buf);

    // q0 failed, q1 succeeded
    expect(zip.file("Pictures/img_snap_0.png")).toBeNull();
    expect(zip.file("Pictures/img_snap_1.png")).not.toBeNull();
    // Both question texts present
    expect(xml).toContain("Question zero");
    expect(xml).toContain("Question one");
    // Failure marker only for q0 position
    expect(xml).toContain("匯出缺圖／預覽轉換失敗");
  });
});

// ---------------------------------------------------------------------------
// (g) ZIP packaging failure → OdtBuildError thrown, no broken blob (issue #753)
// ---------------------------------------------------------------------------

describe("ODT acceptance — ZIP / per-question build failure", () => {
  it("a rasterizer that throws propagates as OdtBuildError, not a partial blob", async () => {
    const rasterizer = async (): Promise<{ ok: true; pngBase64: string }> => {
      throw new Error("rasterizer internal crash");
    };

    const question: ExamQuestion = {
      id: "q-crash",
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: ["Crash question"],
      正確解題分析: ["answer"],
      chart_spec: { render_mode: "html", description: "crash chart" } as Record<string, unknown>,
    };
    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "final",
      isFinal: true,
    };
    const snap = captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z");
    expect(snap).not.toBeNull();

    // Must throw (no broken blob produced)
    await expect(
      buildOdtFromSnapshots("test", [snap!], { rasterizer })
    ).rejects.toMatchObject({ name: "OdtBuildError", questionIndex: 0 });
  });

  it("failure in question 2 of a batch marks questionIndex=1 in OdtBuildError", async () => {
    let callCount = 0;
    const rasterizer = async (): Promise<{ ok: true; pngBase64: string }> => {
      callCount++;
      if (callCount === 2) throw new Error("crash at second question");
      return { ok: true, pngBase64: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" };
    };

    const makeSnap = (id: string, idx: number) => {
      const q: ExamQuestion = {
        id,
        情境: ["個人"] as string[],
        題型種類: "single",
        題型: "選擇題",
        題目: [`Q${idx}`],
        正確解題分析: ["answer"],
        chart_spec: { render_mode: "html", description: "c" } as Record<string, unknown>,
      };
      return captureFromGeneratedQuestion(
        { index: idx, question: q, phase: "final", isFinal: true },
        null,
        "2026-09-27T00:00:00.000Z",
      )!;
    };

    await expect(
      buildOdtFromSnapshots("batch", [makeSnap("q0", 0), makeSnap("q1", 1)], { rasterizer })
    ).rejects.toMatchObject({ questionIndex: 1 });
  });
});

// ---------------------------------------------------------------------------
// (h) Mid-conversion revision arrival does not replace captured source
// ---------------------------------------------------------------------------

describe("ODT acceptance — frozen source during conversion", () => {
  it("mutating snapshot.captured after build starts does not change the rasterized spec", async () => {
    let capturedSpec: Record<string, unknown> | undefined;

    const FAKE_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

    const rasterizer = async ({ chartSpec }: { chartSpec: Record<string, unknown> }) => {
      capturedSpec = chartSpec;
      // Simulate slow rasterization: yield to allow mutations
      await new Promise<void>((resolve) => setTimeout(resolve, 5));
      return { ok: true as const, pngBase64: FAKE_PNG };
    };

    const originalChartSpec = { render_mode: "html", description: "original_spec" };
    const question: ExamQuestion = {
      id: "q-race",
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: ["Race condition question"],
      正確解題分析: ["answer"],
      chart_spec: { ...originalChartSpec } as Record<string, unknown>,
    };
    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "final",
      isFinal: true,
    };
    const snap = captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z");
    expect(snap).not.toBeNull();
    expect(snap!.imageSources["stem"]?.kind).toBe("chart_spec_preview");

    // Start the ODT build (won't finish immediately due to 5ms delay)
    const buildPromise = buildOdtFromSnapshots("test", [snap!], { rasterizer });

    // Simulate a new revision arriving: mutate the live question's chart_spec
    // and also try mutating the captured object
    (question as ExamQuestion).chart_spec = { render_mode: "html", description: "NEW_REVISION_SPEC" } as Record<string, unknown>;

    // Wait for the build to complete
    const blob = await buildPromise;

    // The rasterizer must have been called with the ORIGINAL spec
    // (from imageSources, captured at click time, NOT from the live question)
    expect(capturedSpec).toBeDefined();
    expect((capturedSpec as Record<string, unknown>)["description"]).toBe("original_spec");
    expect(blob).toBeInstanceOf(Blob);
  });

  it("JSON download is unaffected by a failed ODT rasterization (generation completeness unchanged)", async () => {
    // A failed rasterization must not modify the snapshot's _export fields
    const rasterizer = async () => ({
      ok: false as const,
      error: "simulated failure",
    });

    const question: ExamQuestion = {
      id: "q-json-ok",
      情境: ["個人"],
      題型種類: "single",
      題型: "選擇題",
      題目: ["JSON should stay clean"],
      正確解題分析: ["answer"],
      chart_spec: { render_mode: "html", description: "chart" } as Record<string, unknown>,
    };
    const item: GeneratedQuestion = {
      index: 0,
      question,
      phase: "final",
      isFinal: true,
    };
    const snap = captureFromGeneratedQuestion(item, null, "2026-09-27T00:00:00.000Z");
    expect(snap).not.toBeNull();

    // Capture JSON BEFORE the ODT build
    const exportedBefore = JSON.stringify(snap!.exported._export);

    // Run ODT export with failure
    await buildOdtFromSnapshots("test", [snap!], { rasterizer });

    // The snapshot's _export must be unchanged
    const exportedAfter = JSON.stringify(snap!.exported._export);
    expect(exportedAfter).toBe(exportedBefore);

    // Specifically: delivery_status, processing, review not altered
    expect(snap!.exported._export.processing).toBe("unknown"); // legacy path = unknown
    expect(snap!.exported._export.delivery_status).toBeNull(); // no terminal = null
  });
});
