/**
 * Export-only in-browser rasterizer for chart_spec_preview slots.
 *
 * Converts a frozen chart_spec (captured at click time) to a PNG image for
 * embedding in ODT exports.  Never calls LLM / image-provider services.
 * Never writes back to any live question object.
 *
 * Usage:
 *   import { defaultRasterizer } from "./rasterizer";
 *   const result = await defaultRasterizer({ chartSpec });
 *   if (result.ok) { // use result.pngBase64
 *   } else { // show failure message at that slot
 *   }
 *
 * Same-source rendering: when previewMarkup is provided (captured from the
 * mounted FigureRenderer DOM at click time), it is used directly instead of
 * re-rendering offscreen. This ensures the ODT image matches what the user saw.
 *
 * Tainted-canvas fix: uses data:image/svg+xml;charset=utf-8 URL (NOT blob: URL).
 * Chromium does NOT taint canvas for data-URL SVG with foreignObject.
 *
 * Injectable: pass a custom Rasterizer to buildOdtFromSnapshots({ rasterizer })
 * so jsdom unit tests can inject success / per-image failure stubs without
 * requiring Canvas or URL.createObjectURL.
 */

import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import FigureRenderer from "../components/FigureRenderer";
import type { ChartSpecInput } from "../components/FigureRenderer";
import { classifySpec } from "../components/FigureRenderer";
import { serializeElementToMarkup } from "./domCapture";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type RasterizerResult =
  | { ok: true; pngBase64: string }
  | { ok: false; error: string };

export interface RasterizeInput {
  chartSpec: ChartSpecInput;
  previewMarkup?: string;
}

/** Injectable rasterizer interface. */
export type Rasterizer = (input: RasterizeInput) => Promise<RasterizerResult>;

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
// Kept for backwards compatibility and for use in unit tests.
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
 * Kept for backwards compatibility with tests.
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
 * Kept for backwards compatibility with tests.
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
// Offscreen React rendering (browser-only)
// ---------------------------------------------------------------------------

/**
 * Render FigureRenderer offscreen for a given spec and capture its HTML markup.
 * Requires a real browser environment (document, createRoot, etc.).
 */
async function renderFigureToMarkup(spec: ChartSpecInput): Promise<string> {
  const container = document.createElement("div");
  container.style.cssText =
    "position:absolute;left:-9999px;top:-9999px;width:480px;visibility:hidden";
  document.body.appendChild(container);
  try {
    const root = createRoot(container);
    flushSync(() => {
      root.render(createElement(FigureRenderer, { spec }));
    });
    // Wait one microtask for any sync effects
    await Promise.resolve();
    const child = container.firstElementChild;
    if (!child) throw new Error("FigureRenderer rendered nothing");
    return serializeElementToMarkup(child);
  } finally {
    document.body.removeChild(container);
  }
}

// ---------------------------------------------------------------------------
// HTML markup → canvas → PNG via SVG foreignObject + data: URL
// ---------------------------------------------------------------------------

/**
 * Rasterize HTML markup to PNG using SVG foreignObject + data: URL.
 * Uses data:image/svg+xml;charset=utf-8 (NOT blob URL) to avoid Chromium tainted-canvas.
 *
 * This is the key fix for #753: Chromium does NOT taint canvas for data-URL SVG
 * with foreignObject, while blob: URLs DO trigger the tainted-canvas restriction.
 */
export async function markupToPng(
  htmlMarkup: string,
  width: number = DEFAULT_WIDTH,
  height: number = DEFAULT_HEIGHT,
): Promise<string> {
  // Build SVG with foreignObject wrapping XHTML content
  const svgStr = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">`,
    `<foreignObject x="0" y="0" width="${width}" height="${height}">`,
    `<div xmlns="http://www.w3.org/1999/xhtml" style="width:${width}px;min-height:${height}px;background:white;box-sizing:border-box;padding:8px">`,
    htmlMarkup,
    `</div>`,
    `</foreignObject>`,
    `</svg>`,
  ].join("");

  // Use data: URL (not blob:) — Chromium does NOT taint canvas for data-URL SVG with foreignObject
  const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgStr)}`;

  const img = new Image();
  img.crossOrigin = "anonymous";
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error("SVG foreignObject image failed to load"));
    img.src = dataUrl;
  });

  const w = img.naturalWidth || width;
  const h = img.naturalHeight || height;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2d context unavailable");
  ctx.drawImage(img, 0, 0);
  const result = canvas.toDataURL("image/png");
  return result.replace(/^data:image\/png;base64,/, "");
}

// ---------------------------------------------------------------------------
// Default rasterizer
// ---------------------------------------------------------------------------

/**
 * Default in-browser rasterizer using DOM capture + SVG foreignObject approach.
 *
 * When previewMarkup is provided (captured from the mounted FigureRenderer DOM),
 * it is used directly. Otherwise, FigureRenderer is rendered offscreen.
 *
 * Replace with an injectable stub in tests (jsdom has no real Canvas / createRoot).
 */
export const defaultRasterizer: Rasterizer = async ({ chartSpec, previewMarkup }) => {
  try {
    // Unsupported specs fail immediately
    const category = classifySpec(chartSpec);
    if (category === "unsupported") {
      return {
        ok: false,
        error: `unsupported render_mode: ${chartSpec.render_mode ?? "unknown"}`,
      };
    }

    // Get the HTML markup: use pre-captured if available, else render offscreen
    let markup: string;
    if (previewMarkup) {
      markup = previewMarkup;
    } else {
      markup = await renderFigureToMarkup(chartSpec);
    }

    const pngBase64 = await markupToPng(markup);
    return { ok: true, pngBase64 };
  } catch (e: unknown) {
    return {
      ok: false,
      error: e instanceof Error ? e.message : String(e),
    };
  }
};
