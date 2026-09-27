/**
 * Unit tests for rasterizer.ts (issue #753).
 *
 * The default rasterizer requires Canvas and URL.createObjectURL (browser-only),
 * so we only unit-test the pure SVG-builder helpers and the injectable interface.
 * The defaultRasterizer itself is covered by ODT acceptance tests (odt.acceptance.test.ts)
 * which inject success/failure stubs, and by the Python Playwright browser test.
 */

import { describe, expect, it } from "vitest";

import {
  buildGeometrySvg,
  buildTableSvg,
  buildScenarioSvg,
} from "./rasterizer";
import type { Rasterizer, RasterizerResult } from "./rasterizer";

// ---------------------------------------------------------------------------
// SVG builder tests
// ---------------------------------------------------------------------------

describe("buildGeometrySvg", () => {
  it("produces a valid SVG element wrapping the shapes", () => {
    const svg = buildGeometrySvg([
      { type: "polygon", points: [[0, 0], [100, 0], [50, 100]] },
      { type: "line", from: [0, 0], to: [100, 100] },
      { type: "circle", cx: 50, cy: 50, r: 20 },
    ]);
    expect(svg).toContain('<svg xmlns="http://www.w3.org/2000/svg"');
    expect(svg).toContain('viewBox="0 0 100 100"');
    expect(svg).toContain("<polygon");
    expect(svg).toContain("<line");
    expect(svg).toContain("<circle");
    // No XSS vectors — just geometric markup
  });

  it("handles empty shapes array gracefully", () => {
    const svg = buildGeometrySvg([]);
    expect(svg).toContain('<svg xmlns="http://www.w3.org/2000/svg"');
    expect(svg).not.toContain("<polygon");
  });

  it("skips shapes with unrecognized type", () => {
    const svg = buildGeometrySvg([{ type: "unknown-shape" }]);
    expect(svg).toContain('<svg');
    // No crash; empty content
  });
});

describe("buildTableSvg", () => {
  it("produces pure SVG rect+text table (no foreignObject — avoids tainted canvas)", () => {
    const svg = buildTableSvg(["A", "B"], [["1", "2"], ["3", "4"]]);
    expect(svg).toContain('<svg xmlns="http://www.w3.org/2000/svg"');
    // Pure SVG — no foreignObject or HTML elements
    expect(svg).not.toContain("<foreignObject");
    expect(svg).not.toContain("<table");
    // Uses rect + text
    expect(svg).toContain("<rect");
    expect(svg).toContain("<text");
    // Column headers present
    expect(svg).toContain(">A<");
    expect(svg).toContain(">B<");
    // Cell values present
    expect(svg).toContain(">1<");
    expect(svg).toContain(">2<");
  });

  it("XML-escapes column and cell content", () => {
    const svg = buildTableSvg(["<A>", "\"B\""], [["1&2", "<3>"]]);
    expect(svg).toContain("&lt;A&gt;");
    expect(svg).toContain("&quot;B&quot;");
    expect(svg).toContain("1&amp;2");
    expect(svg).toContain("&lt;3&gt;");
  });

  it("handles empty columns and rows without crashing", () => {
    const svg = buildTableSvg([], []);
    expect(svg).toContain('<svg');
    // Should still produce a valid SVG element
    expect(svg).toContain("<rect");
  });
});

describe("buildScenarioSvg", () => {
  it("produces pure SVG rect+text scenario card (no foreignObject)", () => {
    const svg = buildScenarioSvg("Test Title", ["Item 1", "Item 2"], "fallback");
    expect(svg).toContain('<svg xmlns="http://www.w3.org/2000/svg"');
    expect(svg).not.toContain("<foreignObject");
    // Uses rect + text
    expect(svg).toContain("<rect");
    expect(svg).toContain("<text");
    expect(svg).toContain("Test Title");
    expect(svg).toContain("Item 1");
    expect(svg).toContain("Item 2");
  });

  it("uses description as fallback when title is empty", () => {
    const svg = buildScenarioSvg("", [], "fallback description");
    expect(svg).toContain("fallback description");
  });

  it("XML-escapes title and items", () => {
    const svg = buildScenarioSvg("<script>", ["<b>bold</b>"], "");
    expect(svg).toContain("&lt;script&gt;");
    expect(svg).toContain("&lt;b&gt;bold&lt;/b&gt;");
  });

  it("renders title when items is empty", () => {
    const svg = buildScenarioSvg("Title", [], "");
    expect(svg).toContain("Title");
    // No bullet points for empty items
    expect(svg).not.toContain("• ");
  });
});

// ---------------------------------------------------------------------------
// Injectable Rasterizer interface
// ---------------------------------------------------------------------------

describe("Rasterizer interface", () => {
  it("accepts a stub that returns success", async () => {
    const stub: Rasterizer = async () => ({
      ok: true,
      pngBase64: "fake_png_data",
    });
    const result = await stub({ render_mode: "html", description: "test" });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.pngBase64).toBe("fake_png_data");
    }
  });

  it("accepts a stub that returns failure", async () => {
    const stub: Rasterizer = async () => ({
      ok: false,
      error: "conversion failed",
    });
    const result = await stub({ render_mode: "chart" });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe("conversion failed");
    }
  });

  it("can be typed as a per-image failure stub", async () => {
    const calls: string[] = [];
    const stub: Rasterizer = async (spec) => {
      calls.push(spec.description ?? "no-description");
      return { ok: true, pngBase64: "abc" };
    };
    const r1: RasterizerResult = await stub({ description: "first" });
    const r2: RasterizerResult = await stub({ description: "second" });
    expect(calls).toEqual(["first", "second"]);
    expect(r1.ok).toBe(true);
    expect(r2.ok).toBe(true);
  });
});
