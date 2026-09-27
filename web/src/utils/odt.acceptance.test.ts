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

  it("(a2) q_RUN_001 (2 received 小題, 1 missing) shows both received subquestions", async () => {
    const snaps = buildSnapshots();
    const snap001 = snaps.find((s) => s.exported.id === "q_RUN_001");
    expect(snap001).toBeDefined();

    const blob = await buildOdtFromSnapshots("test", [snap001!]);
    const xml = await readContentXml(blob);

    // Should render as 題組 (has subquestions)
    expect(xml).toContain("文本 A");
    expect(xml).toContain("核心問題 A");
    // Both delivered subquestions should appear
    expect(xml).toContain("第1題");
    expect(xml).toContain("第3題");
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
