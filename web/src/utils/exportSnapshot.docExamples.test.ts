/**
 * test(754): Validate _export examples from docs/generation-event-protocol.md
 * against the TypeScript ExportMeta type from exportSnapshot.ts.
 *
 * Extracts every ```json block from the protocol document that contains an
 * "_export" key and checks that every required field is present and has the
 * correct type/value.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

// ---------------------------------------------------------------------------
// Document parsing
// ---------------------------------------------------------------------------

const PROTOCOL_DOC = resolve(
  __dirname,
  "../../../docs/generation-event-protocol.md"
);

function extractJsonBlocks(markdown: string): string[] {
  const blocks: string[] = [];
  const re = /```json\n([\s\S]*?)```/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(markdown)) !== null) {
    blocks.push(m[1]);
  }
  return blocks;
}

function isSkippable(raw: string): boolean {
  return raw.includes("...") || raw.includes("< ") || raw.includes("<prefix>");
}

interface ExportMetaShape {
  format_version: unknown;
  exported_at: unknown;
  is_draft: unknown;
  run_id: unknown;
  index: unknown;
  content_revision: unknown;
  processing: unknown;
  termination_reason: unknown;
  delivery_status: unknown;
  missing: unknown;
  review: unknown;
}

function extractExportMetas(): Array<{ label: string; meta: ExportMetaShape }> {
  const doc = readFileSync(PROTOCOL_DOC, "utf-8");
  const blocks = extractJsonBlocks(doc);
  const results: Array<{ label: string; meta: ExportMetaShape }> = [];
  blocks.forEach((raw, i) => {
    if (isSkippable(raw)) return;
    let obj: unknown;
    try {
      obj = JSON.parse(raw);
    } catch {
      return;
    }
    if (
      typeof obj === "object" &&
      obj !== null &&
      "_export" in obj &&
      typeof (obj as Record<string, unknown>)["_export"] === "object"
    ) {
      results.push({
        label: `block_${i}`,
        meta: (obj as Record<string, unknown>)["_export"] as ExportMetaShape,
      });
    }
  });
  return results;
}

function extractEnvelopes(): Array<{ label: string; ctx: unknown; payload: unknown }> {
  const doc = readFileSync(PROTOCOL_DOC, "utf-8");
  const blocks = extractJsonBlocks(doc);
  const results: Array<{ label: string; ctx: unknown; payload: unknown }> = [];
  blocks.forEach((raw, i) => {
    if (isSkippable(raw)) return;
    let obj: unknown;
    try {
      obj = JSON.parse(raw);
    } catch {
      return;
    }
    if (
      typeof obj === "object" &&
      obj !== null &&
      "context" in obj &&
      "payload" in obj
    ) {
      const o = obj as Record<string, unknown>;
      results.push({ label: `block_${i}`, ctx: o["context"], payload: o["payload"] });
    }
  });
  return results;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

const VALID_PROCESSING = ["waiting", "running", "ended", "unknown"] as const;
const VALID_TERMINATION = ["normal", "failed", "cancelled"] as const;
const VALID_DELIVERY = ["complete", "partial", "none", "unknown"] as const;
const VALID_REVIEW_STATUS = ["passed", "failed", "skipped", "unknown"] as const;

const REQUIRED_EXPORT_KEYS: (keyof ExportMetaShape)[] = [
  "format_version",
  "exported_at",
  "is_draft",
  "run_id",
  "index",
  "content_revision",
  "processing",
  "termination_reason",
  "delivery_status",
  "missing",
  "review",
];

describe("docs/generation-event-protocol.md _export examples", () => {
  const metas = extractExportMetas();

  it("should find at least one _export example in the document", () => {
    expect(metas.length).toBeGreaterThanOrEqual(1);
  });

  metas.forEach(({ label, meta }) => {
    describe(`${label}`, () => {
      it("has all required fields", () => {
        for (const key of REQUIRED_EXPORT_KEYS) {
          expect(meta, `${label} missing '${key}'`).toHaveProperty(key);
        }
      });

      it("format_version is 1", () => {
        expect(meta.format_version).toBe(1);
      });

      it("exported_at is a string", () => {
        expect(typeof meta.exported_at).toBe("string");
      });

      it("is_draft is a boolean", () => {
        expect(typeof meta.is_draft).toBe("boolean");
      });

      it("processing is a valid value", () => {
        expect(VALID_PROCESSING).toContain(meta.processing);
      });

      it("termination_reason is valid or null", () => {
        if (meta.termination_reason !== null) {
          expect(VALID_TERMINATION).toContain(meta.termination_reason);
        }
      });

      it("delivery_status is valid or null", () => {
        if (meta.delivery_status !== null) {
          expect(VALID_DELIVERY).toContain(meta.delivery_status);
        }
      });

      it("missing is an array", () => {
        expect(Array.isArray(meta.missing)).toBe(true);
      });

      it("review.status is valid", () => {
        const review = meta.review as Record<string, unknown> | null;
        expect(review).toBeTruthy();
        expect(VALID_REVIEW_STATUS).toContain(review!["status"]);
      });
    });
  });
});

describe("docs/generation-event-protocol.md envelope examples", () => {
  const envelopes = extractEnvelopes();

  it("should find at least 2 envelope examples in the document", () => {
    expect(envelopes.length).toBeGreaterThanOrEqual(2);
  });

  envelopes.forEach(({ label, ctx }) => {
    it(`${label} context has run_id and event_seq >= 1`, () => {
      const c = ctx as Record<string, unknown>;
      expect(typeof c["run_id"]).toBe("string");
      expect(c["run_id"]).toBeTruthy();
      const seq = c["event_seq"];
      expect(typeof seq).toBe("number");
      expect(seq as number).toBeGreaterThanOrEqual(1);
    });
  });
});
