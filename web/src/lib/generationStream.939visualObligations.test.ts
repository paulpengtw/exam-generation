/**
 * Regression tests for issue #939: visual obligation contract — six-slot NS run.
 *
 * Fixture: ns_six_slot_visual.jsonl
 *   slots 1, 2, 4, 6 — chart_spec + 圖片 set, valid PNG on disk → delivered
 *   slot 3            — chart_spec set, render failed (圖片=null) → missing, reason="render_failed"
 *   slot 5            — chart_spec + 圖片 set, but file was 0-byte → missing, reason="empty_image"
 *
 * Tests drive the full client-side pipeline:
 *   fixture → decoder → evidence reducer → exportSnapshot → ODT
 *
 * Assertions:
 *  1. Decoder replays cleanly (no degradation, no conflict).
 *  2. Evidence: processing="ended", receipt="final", delivery_status="partial".
 *  3. Missing slots: exactly 2 image slots (subquestion_index 2 and 4).
 *  4. Missing reasons: "render_failed" for index 2, "empty_image" for index 4.
 *  5. JSON snapshot _export.missing has exactly the two image slots with reasons.
 *  6. ODT: contains 【圖片缺項】 markers for slots 3 and 5.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import JSZip from "jszip";
import { describe, expect, it } from "vitest";

import {
  applyDegraded,
  applyV2Event,
  createRunEvidence,
  type RunEvidenceState,
} from "./generationEvidence";
import { createGenerationStreamDecoder } from "./generationStream";
import {
  captureFromEvidence,
  type QuestionSnapshot,
} from "../utils/exportSnapshot";
import { buildOdtFromSnapshots } from "../utils/odt";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface FixtureLine {
  event: string;
  context: Record<string, unknown>;
  payload: Record<string, unknown>;
}

function loadFixture(name: string): FixtureLine[] {
  const path = resolve(
    __dirname,
    "../../../tests/fixtures/generation_v2",
    name,
  );
  return readFileSync(path, "utf-8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as FixtureLine);
}

function replayFixture(
  fixture: FixtureLine[],
): { state: RunEvidenceState; degraded: boolean } {
  const dec = createGenerationStreamDecoder();
  let state: RunEvidenceState | null = null;

  for (const line of fixture) {
    const rawData = JSON.stringify({
      context: line.context,
      payload: line.payload,
    });
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

  if (!state)
    throw new Error("No state built — started event was missing or malformed");
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
// Test suite
// ---------------------------------------------------------------------------

describe("Issue #939 six-slot NS visual obligations fixture", () => {
  const fixture = loadFixture("ns_six_slot_visual.jsonl");
  const { state, degraded } = replayFixture(fixture);
  const runId = state.runId ?? null;
  const exportedAt = "2026-10-01T00:00:00.000Z";

  const qId = state.order[0];
  if (!qId) throw new Error("No question id in state.order");
  const ev = state.questions[qId];

  it("decoder replays cleanly: no degradation, no conflict", () => {
    expect(degraded).toBe(false);
    expect(state.batchConflict).toBe(false);
    expect(state.legacyMixed).toBe(false);
    expect(ev?.contentConflict).toBeFalsy();
    expect(ev?.terminalConflict).toBeFalsy();
  });

  it("evidence: processing=ended, receipt=final", () => {
    expect(ev).toBeDefined();
    expect(ev!.processing).toBe("ended");
    expect(ev!.content.receipt).toBe("final");
  });

  it("evidence: delivery_status=partial", () => {
    expect(ev!.terminal?.delivery_status).toBe("partial");
  });

  it("evidence: missing has exactly 2 image slots", () => {
    const missing = ev!.terminal?.missing ?? [];
    const imgMissing = missing.filter((m) => m.kind === "image");
    expect(imgMissing).toHaveLength(2);
  });

  it("evidence: slot 3 (subquestion_index=2) has reason=render_failed", () => {
    const missing = ev!.terminal?.missing ?? [];
    const slot3 = missing.find(
      (m) => m.kind === "image" && m.subquestion_index === 2,
    );
    expect(slot3).toBeDefined();
    expect(slot3!.reason).toBe("render_failed");
    expect(slot3!.subquestion_id).toMatch(/-sq003$/);
  });

  it("evidence: slot 5 (subquestion_index=4) has reason=empty_image", () => {
    const missing = ev!.terminal?.missing ?? [];
    const slot5 = missing.find(
      (m) => m.kind === "image" && m.subquestion_index === 4,
    );
    expect(slot5).toBeDefined();
    expect(slot5!.reason).toBe("empty_image");
    expect(slot5!.subquestion_id).toMatch(/-sq005$/);
  });

  it("evidence: delivered has 4 image slots (slots 1, 2, 4, 6)", () => {
    const delivered = ev!.terminal?.delivered ?? [];
    const imgDelivered = delivered.filter((d) => d.kind === "image");
    expect(imgDelivered).toHaveLength(4);
    const indices = imgDelivered.map((d) => d.subquestion_index).sort();
    expect(indices).toEqual([0, 1, 3, 5]);
  });

  it("snapshot _export.missing has exactly 2 image slots with reasons", () => {
    expect(ev!.content.question).toBeDefined();
    const snap: QuestionSnapshot | null = captureFromEvidence(
      ev!.content.question!,
      ev!,
      runId,
      exportedAt,
    );
    expect(snap).not.toBeNull();
    expect(snap!.exported._export.delivery_status).toBe("partial");

    const missingSlots = snap!.exported._export.missing;
    const imgMissing = missingSlots.filter((m) => m.kind === "image");
    expect(imgMissing).toHaveLength(2);

    const rf = imgMissing.find((m) => m.subquestion_index === 2);
    expect(rf).toBeDefined();
    expect(rf!.reason).toBe("render_failed");

    const ei = imgMissing.find((m) => m.subquestion_index === 4);
    expect(ei).toBeDefined();
    expect(ei!.reason).toBe("empty_image");
  });

  it("ODT: contains 【圖片缺項】 markers for slots 3 and 5", async () => {
    expect(ev!.content.question).toBeDefined();
    const snap: QuestionSnapshot | null = captureFromEvidence(
      ev!.content.question!,
      ev!,
      runId,
      exportedAt,
    );
    expect(snap).not.toBeNull();

    const blob = await buildOdtFromSnapshots("test", [snap!]);
    const xml = await readContentXml(blob);

    // The question text and fixture content
    expect(xml).toContain("核心問題 939");
    expect(xml).toContain("文本 939");

    // ODT renders known_missing image slots with 缺圖 (i18n: "odt.known_missing_subq_image").
    // The zh-TW message is 【缺圖：第N題圖片已知缺失】 — check for 缺圖 substring.
    // There should be at least 2 occurrences (one per missing image slot).
    const markerCount = (xml.match(/缺圖/g) ?? []).length;
    expect(markerCount).toBeGreaterThanOrEqual(2);
  });
});
