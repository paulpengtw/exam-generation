/**
 * Regression tests for issue #937: blank/missing 題目 causes partial delivery.
 *
 * These tests drive the full client-side pipeline:
 *   fixture → decoder → evidence reducer → exportSnapshot → ODT
 *
 * Fixtures (both SS and NS) capture a 3-slot 題組 where slot 2 (sq002)
 * was dropped because the mock sub-generator returned blank 題目.
 *
 * Assertions:
 *  1. Decoder replays cleanly (no degradation, no conflict).
 *  2. Evidence state: processing="ended", receipt="final".
 *  3. Delivered subquestions are sq001 and sq003 only.
 *  4. Terminal: delivery_status="partial", missing=[{kind:"subquestion", subquestion_index:1}].
 *  5. JSON snapshot: _export.missing and _export.delivery_status agree.
 *  6. ODT content.xml: contains 第1題, 【缺小題 2】, 第3題 in correct order.
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
import {
  createGenerationStreamDecoder,
} from "./generationStream";
import {
  captureFromEvidence,
  type QuestionSnapshot,
} from "../utils/exportSnapshot";
import { buildOdtFromSnapshots } from "../utils/odt";

// ---------------------------------------------------------------------------
// Helpers (shared with odt.acceptance.test.ts)
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
// Tests parametrised over social_studies and natural_sciences
// ---------------------------------------------------------------------------

const SUBJECTS: Array<{ name: string; fixture: string }> = [
  { name: "social_studies", fixture: "social_partial_delivery.jsonl" },
  { name: "natural_sciences", fixture: "ns_partial_delivery.jsonl" },
];

for (const { name: subjectName, fixture: fixtureName } of SUBJECTS) {
  describe(`Issue #937 partial delivery — ${subjectName}`, () => {
    const fixture = loadFixture(fixtureName);
    const { state, degraded } = replayFixture(fixture);
    const runId = state.runId ?? null;
    const exportedAt = "2026-10-01T00:00:00.000Z";

    // Find the one question in the manifest
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

    it("evidence: missing has exactly 1 subquestion slot at subquestion_index=1", () => {
      const missing = ev!.terminal?.missing ?? [];
      const sqMissing = missing.filter(
        (m) => m.kind === "subquestion",
      );
      expect(sqMissing).toHaveLength(1);
      expect(sqMissing[0].subquestion_index).toBe(1);
      expect(sqMissing[0].subquestion_id).toMatch(/-sq002$/);
    });

    it("delivered subquestions are sq001 and sq003 only", () => {
      const q = ev!.content.question;
      expect(q).toBeDefined();
      const subqs = (q as Record<string, unknown>)["subquestions"] as Array<
        Record<string, unknown>
      > ?? [];
      const ids = subqs.map((s) => s["id"] as string);
      expect(ids).toContain(`${qId}-sq001`);
      expect(ids).toContain(`${qId}-sq003`);
      expect(ids).not.toContain(`${qId}-sq002`);
      expect(ids).toHaveLength(2);
    });

    it("snapshot _export.delivery_status=partial and missing=[sq002]", () => {
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
      const sqMissing = missingSlots.filter((m) => m.kind === "subquestion");
      expect(sqMissing).toHaveLength(1);
      expect(sqMissing[0].subquestion_index).toBe(1);
      expect(sqMissing[0].subquestion_id).toMatch(/-sq002$/);

      // Delivered subquestions in the snapshot
      const subqs = (snap!.exported.subquestions ?? []) as Array<
        Record<string, unknown>
      >;
      const seqNos = subqs.map((s) => s["序號"] as number);
      expect(seqNos).toContain(1);
      expect(seqNos).toContain(3);
      expect(seqNos).not.toContain(2);
    });

    it("ODT: contains 第1題, 缺小題 2, 第3題 in document order", async () => {
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

      // The group layout must appear (文本 and 核心問題)
      expect(xml).toContain("核心問題 937");
      expect(xml).toContain("文本 937");

      // Delivered subquestions
      expect(xml).toContain("第1題");
      expect(xml).toContain("第3題");

      // Missing slot marker — ODT renders "缺小題 N" where N is the 1-based 序號
      expect(xml).toContain("缺小題 2");

      // Ordering: 第1題 → 缺小題 2 → 第3題
      const pos1 = xml.indexOf("第1題");
      const posMissing2 = xml.indexOf("缺小題 2");
      const pos3 = xml.indexOf("第3題");
      expect(pos1).toBeGreaterThan(-1);
      expect(posMissing2).toBeGreaterThan(pos1);
      expect(pos3).toBeGreaterThan(posMissing2);
    });
  });
}
