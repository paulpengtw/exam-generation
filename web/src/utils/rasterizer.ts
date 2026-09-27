/**
 * Export-only in-browser rasterizer for chart_spec_preview slots.
 *
 * Converts a frozen chart_spec (captured at click time) to a PNG image for
 * embedding in ODT exports.  Never calls LLM / image-provider services.
 * Never writes back to any live question object.
 *
 * Usage:
 *   import { defaultRasterizer } from "./rasterizer";
 *   const result = await defaultRasterizer(chartSpec);
 *   if (result.ok) { // use result.pngBase64
 *   } else { // show failure message at that slot
 *   }
 *
 * Injectable: pass a custom Rasterizer to buildOdtFromSnapshots({ rasterizer })
 * so jsdom unit tests can inject success / per-image failure stubs without
 * requiring Canvas or URL.createObjectURL.
 *
 * Supported render paths:
 *   - "geometry" (SVG shapes)       → pure SVG → canvas → PNG
 *   - "table" (columns/rows)        → SVG foreignObject wrapping HTML table → canvas → PNG
 *   - "scenario_card" (title/items) → SVG foreignObject wrapping HTML card → canvas → PNG
 *   - anything else                 → { ok: false } immediately (unsupported)
 */

import { classifySpec } from "../components/FigureRenderer";
import type { ChartSpecInput } from "../components/FigureRenderer";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type RasterizerResult =
  | { ok: true; pngBase64: string }
  | { ok: false; error: string };

/** Injectable rasterizer interface. */
export type Rasterizer = (spec: ChartSpecInput) => Promise<RasterizerResult>;

// ---------------------------------------------------------------------------
// Internal constants
// ---------------------------------------------------------------------------

const DEFAULT_WIDTH = 480;
const DEFAULT_HEIGHT = 360;

// ---------------------------------------------------------------------------
// Internal HTML-escape helper (same rule set as odt.ts xmlEscape)
// ---------------------------------------------------------------------------

function esc(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// SVG builders (pure-string; no DOM required)
// ---------------------------------------------------------------------------

type ShapeSpec = {
  type: string;
  points?: [number, number][];
  from?: [number, number];
  to?: [number, number];
  cx?: number;
  cy?: number;
  r?: number;
};

/** Build a self-contained SVG string from geometry shapes. */
export function buildGeometrySvg(shapes: ShapeSpec[]): string {
  const elements = shapes
    .map((shape) => {
      if (shape.type === "polygon" && shape.points) {
        const pts = shape.points.map(([x, y]) => `${x},${y}`).join(" ");
        return `<polygon points="${pts}" fill="none" stroke="#111" stroke-width="1"/>`;
      }
      if (shape.type === "line" && shape.from && shape.to) {
        return (
          `<line x1="${shape.from[0]}" y1="${shape.from[1]}" ` +
          `x2="${shape.to[0]}" y2="${shape.to[1]}" stroke="#111" stroke-width="1"/>`
        );
      }
      if (shape.type === "circle" && shape.cx !== undefined) {
        return (
          `<circle cx="${shape.cx}" cy="${shape.cy ?? 0}" r="${shape.r ?? 1}" ` +
          `fill="none" stroke="#111" stroke-width="1"/>`
        );
      }
      return "";
    })
    .join("");
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" ` +
    `viewBox="0 0 100 100" width="${DEFAULT_WIDTH}" height="${DEFAULT_HEIGHT}">` +
    elements +
    `</svg>`
  );
}

/**
 * Build a pure SVG table (no foreignObject).
 *
 * foreignObject triggers a "tainted canvas" security restriction in Chromium when
 * the SVG is rendered via canvas.toDataURL(), making the PNG export fail.  Using
 * pure SVG rect + text elements avoids the restriction and works in all browsers.
 */
export function buildTableSvg(columns: string[], rows: string[][]): string {
  const CELL_W = Math.max(80, Math.floor(DEFAULT_WIDTH / Math.max(columns.length, 1)));
  const CELL_H = 24;
  const PAD_X = 6;
  const totalCols = columns.length;
  const totalRows = rows.length;
  const svgW = totalCols > 0 ? totalCols * CELL_W : DEFAULT_WIDTH;
  const svgH = Math.max(40, (totalRows + 1) * CELL_H + 8);

  const elements: string[] = [
    `<rect width="${svgW}" height="${svgH}" fill="white"/>`,
  ];

  // Header row
  columns.forEach((col, ci) => {
    const x = ci * CELL_W;
    elements.push(
      `<rect x="${x}" y="0" width="${CELL_W}" height="${CELL_H}" fill="#f9f9f9" stroke="#ccc" stroke-width="0.5"/>`,
      `<text x="${x + PAD_X}" y="${CELL_H / 2}" dominant-baseline="middle" ` +
        `font-family="sans-serif" font-size="11" font-weight="bold" fill="#333">${esc(col)}</text>`,
    );
  });

  // Data rows
  rows.forEach((row, ri) => {
    const y = (ri + 1) * CELL_H;
    row.forEach((cell, ci) => {
      const x = ci * CELL_W;
      elements.push(
        `<rect x="${x}" y="${y}" width="${CELL_W}" height="${CELL_H}" fill="white" stroke="#ccc" stroke-width="0.5"/>`,
        `<text x="${x + PAD_X}" y="${y + CELL_H / 2}" dominant-baseline="middle" ` +
          `font-family="sans-serif" font-size="11" fill="#333">${esc(cell)}</text>`,
      );
    });
  });

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${svgW}" height="${svgH}">` +
    elements.join("") +
    `</svg>`
  );
}

/**
 * Build a pure SVG scenario card (no foreignObject).
 *
 * Uses rect + text elements to avoid the tainted-canvas restriction.
 */
export function buildScenarioSvg(
  title: string,
  items: string[],
  description: string,
): string {
  const displayTitle = title || description;
  const LINE_H = 20;
  const PAD = 12;
  const totalLines = 1 + items.length;
  const svgH = totalLines * LINE_H + PAD * 2;
  const svgW = DEFAULT_WIDTH;

  const elements: string[] = [
    `<rect width="${svgW}" height="${svgH}" rx="4" fill="#fffbeb" stroke="#f59e0b" stroke-width="1"/>`,
    `<text x="${PAD}" y="${PAD + LINE_H / 2}" dominant-baseline="middle" ` +
      `font-family="sans-serif" font-size="13" font-weight="bold" fill="#7a5000">${esc(displayTitle)}</text>`,
  ];

  items.forEach((item, i) => {
    const y = PAD + (i + 1) * LINE_H + LINE_H / 2;
    elements.push(
      `<text x="${PAD + 16}" y="${y}" dominant-baseline="middle" ` +
        `font-family="sans-serif" font-size="12" fill="#7a5000">• ${esc(item)}</text>`,
    );
  });

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${svgW}" height="${svgH}">` +
    elements.join("") +
    `</svg>`
  );
}

// ---------------------------------------------------------------------------
// SVG → canvas → PNG (browser-only; requires DOM + Canvas API)
// ---------------------------------------------------------------------------

/**
 * Render an SVG markup string to a PNG and return it as a base64 string.
 * Requires a real browser environment: URL.createObjectURL, new Image(), canvas.
 * Throws when any of those are unavailable (e.g. jsdom without canvas).
 */
export async function svgMarkupToPng(svgMarkup: string): Promise<string> {
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    throw new Error("URL.createObjectURL is unavailable (non-browser environment)");
  }
  const blob = new Blob([svgMarkup], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("SVG image failed to load"));
      img.src = url;
    });
    const w = img.naturalWidth || DEFAULT_WIDTH;
    const h = img.naturalHeight || DEFAULT_HEIGHT;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas 2d context unavailable");
    ctx.drawImage(img, 0, 0);
    const dataUrl = canvas.toDataURL("image/png");
    return dataUrl.replace(/^data:image\/png;base64,/, "");
  } finally {
    URL.revokeObjectURL(url);
  }
}

// ---------------------------------------------------------------------------
// Default rasterizer
// ---------------------------------------------------------------------------

/**
 * Default in-browser rasterizer.  Classify the spec → build SVG → render PNG.
 * Returns { ok: false } for unsupported render modes or on any rendering error.
 *
 * Replace with an injectable stub in tests (jsdom has no real Canvas / ObjectURL).
 */
export const defaultRasterizer: Rasterizer = async (spec) => {
  try {
    const category = classifySpec(spec);
    const data = (spec.data ?? {}) as Record<string, unknown>;

    let svgMarkup: string;

    if (category === "geometry") {
      svgMarkup = buildGeometrySvg(
        (data.shapes as ShapeSpec[] | undefined) ?? [],
      );
    } else if (category === "table") {
      svgMarkup = buildTableSvg(
        (data.columns as string[] | undefined) ?? [],
        (data.rows as string[][] | undefined) ?? [],
      );
    } else if (category === "scenario_card") {
      const d = data as { title?: string; items?: string[] };
      svgMarkup = buildScenarioSvg(
        d.title ?? "",
        d.items ?? [],
        spec.description ?? "",
      );
    } else {
      return {
        ok: false,
        error: `unsupported render_mode: ${spec.render_mode ?? "unknown"}`,
      };
    }

    const pngBase64 = await svgMarkupToPng(svgMarkup);
    return { ok: true, pngBase64 };
  } catch (e: unknown) {
    return {
      ok: false,
      error: e instanceof Error ? e.message : String(e),
    };
  }
};
