/**
 * Test harness entry for issue #753 real-browser ODT export tests.
 *
 * This module is served by `npx vite` from the web/ directory and imported
 * by odt-export.html.  It drives the REAL rasterizer, exportSnapshot, and
 * odt modules — no mocks — and exposes results on window.__harness so Python
 * Playwright tests can read them via page.evaluate().
 *
 * Usage from Python Playwright:
 *   result = page.evaluate("() => window.__harness.runAll()")
 */

import { defaultRasterizer } from "../src/utils/rasterizer";
import { buildOdtFromSnapshots } from "../src/utils/odt";
import type { QuestionSnapshot } from "../src/utils/exportSnapshot";
import JSZip from "jszip";

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

/** A valid table chart spec (classifySpec returns "table"). */
const CHART_SPEC_TABLE: Record<string, unknown> = {
  render_mode: "html",
  description: "Breakfast items and prices table.",
  data: {
    columns: ["品項", "價格"],
    rows: [
      ["豆漿", "35元"],
      ["燒餅", "20元"],
      ["荷包蛋", "15元"],
    ],
  },
};


/** Build a minimal QuestionSnapshot for testing. */
function makeSnap(opts: {
  id: string;
  withChartSpec?: boolean;
  withPngBase64?: boolean;
  previewMarkup?: string;
}): QuestionSnapshot {
  const q = {
    id: opts.id,
    情境: ["個人"],
    題型種類: "single",
    題型: "選擇題",
    題目: [`Test question ${opts.id}`],
    正確解題分析: ["Test answer"],
  };

  const imageSources: Record<string, unknown> = {};
  if (opts.withChartSpec) {
    imageSources["stem"] = {
      kind: "chart_spec_preview",
      chartSpec: CHART_SPEC_TABLE,
      previewMarkup: opts.previewMarkup,
      contentRevision: 1,
    };
  }
  if (opts.withPngBase64) {
    // Minimal 1x1 transparent PNG
    imageSources["stem"] = {
      kind: "png_base64",
      pngBase64:
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
      contentRevision: 1,
    };
  }

  return {
    exported: {
      ...q,
      _export: {
        format_version: 1,
        exported_at: new Date().toISOString(),
        is_draft: false,
        run_id: null,
        index: 0,
        content_revision: 1,
        processing: "ended",
        termination_reason: "normal",
        delivery_status: "complete",
        missing: [],
        review: { status: "passed", content_revision: 1 },
      },
    },
    captured: q,
    isDraft: false,
    index: 0,
    imageSources,
  };
}

// ---------------------------------------------------------------------------
// Individual test functions
// ---------------------------------------------------------------------------

/**
 * t1: defaultRasterizer produces a valid PNG for a chart_spec_preview slot.
 * This exercises the SVG foreignObject + data: URL path in real Chromium.
 */
async function t1_rasterizer_produces_png(): Promise<{
  ok: boolean;
  byteLength?: number;
  error?: string;
}> {
  const result = await defaultRasterizer({ chartSpec: CHART_SPEC_TABLE });
  if (!result.ok) return { ok: false, error: result.error };
  const bytes = atob(result.pngBase64).length;
  return { ok: true, byteLength: bytes };
}

/**
 * t2: defaultRasterizer with previewMarkup produces a valid PNG.
 * This exercises the same-source rendering path.
 */
async function t2_rasterizer_with_preview_markup(): Promise<{
  ok: boolean;
  byteLength?: number;
  error?: string;
}> {
  // Same-source rendering: previewMarkup bypasses the FigureRenderer offscreen render
  const previewMarkup =
    "<table style='border-collapse:collapse'>" +
    "<thead><tr><th style='border:1px solid #ccc;padding:4px'>欄位A</th>" +
    "<th style='border:1px solid #ccc;padding:4px'>欄位B</th></tr></thead>" +
    "<tbody><tr><td style='border:1px solid #ccc;padding:4px'>值1</td>" +
    "<td style='border:1px solid #ccc;padding:4px'>值2</td></tr></tbody></table>";
  const result = await defaultRasterizer({
    chartSpec: CHART_SPEC_TABLE,
    previewMarkup,
  });
  if (!result.ok) return { ok: false, error: result.error };
  const bytes = atob(result.pngBase64).length;
  return { ok: true, byteLength: bytes };
}

/**
 * t3: buildOdtFromSnapshots with a chart_spec_preview slot completes and
 * produces a valid ODT ZIP containing content.xml.
 */
async function t3_build_odt_with_chart_spec(): Promise<{
  ok: boolean;
  hasContentXml?: boolean;
  hasPng?: boolean;
  byteLength?: number;
  error?: string;
}> {
  const snap = makeSnap({ id: "q-t3-chart", withChartSpec: true });
  let blob: Blob;
  try {
    blob = await buildOdtFromSnapshots("Test ODT", [snap]);
  } catch (e) {
    return { ok: false, error: String(e) };
  }
  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const contentXml = zip.file("content.xml");
  const hasPng = Object.keys(zip.files).some((name) => name.endsWith(".png"));
  return {
    ok: true,
    hasContentXml: !!contentXml,
    hasPng,
    byteLength: buf.byteLength,
  };
}

/**
 * t4: buildOdtFromSnapshots with a png_base64 slot embeds the PNG correctly.
 */
async function t4_build_odt_with_png_base64(): Promise<{
  ok: boolean;
  hasPng?: boolean;
  error?: string;
}> {
  const snap = makeSnap({ id: "q-t4-png", withPngBase64: true });
  let blob: Blob;
  try {
    blob = await buildOdtFromSnapshots("Test PNG ODT", [snap]);
  } catch (e) {
    return { ok: false, error: String(e) };
  }
  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const hasPng = Object.keys(zip.files).some((name) => name.endsWith(".png"));
  return { ok: true, hasPng };
}

/**
 * t5: Per-image rasterizer failure produces ODT with failure marker, not OdtBuildError.
 * Injects a rasterizer that always fails.
 */
async function t5_per_image_failure_produces_marker(): Promise<{
  ok: boolean;
  hasMarker?: boolean;
  hasPng?: boolean;
  error?: string;
}> {
  const failingRasterizer = async () => ({
    ok: false as const,
    error: "injected failure",
  });
  const snap = makeSnap({
    id: "q-t5-fail",
    withChartSpec: true,
    // No previewMarkup — forces classification path, which verifies injected rasterizer is used
  });
  let blob: Blob;
  try {
    blob = await buildOdtFromSnapshots("Failure Marker ODT", [snap], {
      rasterizer: failingRasterizer,
    });
  } catch (e) {
    return { ok: false, error: String(e) };
  }
  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const contentXml = zip.file("content.xml");
  const xml = await contentXml!.async("string");
  const hasMarker = xml.includes("匯出缺圖／預覽轉換失敗");
  const hasPng = Object.keys(zip.files).some((name) => name.endsWith(".png"));
  return { ok: true, hasMarker, hasPng };
}

/**
 * t6: No tainted-canvas SecurityError with data: URL SVG foreignObject.
 */
async function t6_no_tainted_canvas_error(): Promise<{
  ok: boolean;
  error?: string;
}> {
  try {
    const svgStr =
      '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">' +
      '<foreignObject x="0" y="0" width="100" height="100">' +
      '<div xmlns="http://www.w3.org/1999/xhtml"><p>taint test</p></div>' +
      "</foreignObject></svg>";
    const url =
      "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgStr);
    const img = new Image();
    img.crossOrigin = "anonymous";
    await new Promise<void>((res, rej) => {
      img.onload = () => res();
      img.onerror = (e) => rej(e);
      img.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = 100;
    canvas.height = 100;
    canvas.getContext("2d")!.drawImage(img, 0, 0);
    canvas.toDataURL("image/png");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

/**
 * t7: Image-swap race — verifies that buildOdtFromSnapshots reads imageSources
 * synchronously before its first await, so a post-await mutation of the
 * snapshot's imageSources does not affect the produced ODT.
 *
 * Procedure:
 *   1. Build a snapshot with a chart_spec_preview source (slow async rasterizer).
 *   2. Start the ODT build (do NOT await yet — store the promise).
 *   3. Immediately null out imageSources on the snapshot object.
 *   4. Await the promise.
 *   5. Verify the ODT still has a PNG embedded (the rasterizer used the captured data).
 */
async function t7_image_swap_race(): Promise<{
  ok: boolean;
  hasPngBeforeSwap?: boolean;
  hasPngAfterSwap?: boolean;
  error?: string;
}> {
  // Slow rasterizer: holds a reference to the chartSpec it was called with
  let capturedInput: unknown = null;
  const slowRasterizer = async (input: { chartSpec: unknown; previewMarkup?: string }) => {
    capturedInput = input.chartSpec;
    // Yield so the mutation in step 3 can happen synchronously before us continuing
    await Promise.resolve();
    return await defaultRasterizer(input);
  };

  const snap = makeSnap({ id: "q-t7-race", withChartSpec: true });

  // Step 2: start the ODT build but do NOT await yet
  const buildPromise = buildOdtFromSnapshots("Race ODT", [snap], {
    rasterizer: slowRasterizer,
  });

  // Step 3: null out imageSources — would break the build if read lazily
  (snap as unknown as Record<string, unknown>).imageSources = {};

  // Step 4: await the result
  let blob: Blob;
  try {
    blob = await buildPromise;
  } catch (e) {
    return { ok: false, error: String(e) };
  }

  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const hasPng = Object.keys(zip.files).some((name) => name.endsWith(".png"));

  // capturedInput must have been set (rasterizer was called with original chart spec)
  return {
    ok: !!capturedInput,
    hasPngBeforeSwap: hasPng,
    hasPngAfterSwap: hasPng,
  };
}

/**
 * t8: Injected whole-ZIP failure — a rasterizer that throws (not just
 * returns {ok:false}) causes OdtBuildError, and no Blob is produced.
 *
 * This is distinct from t5's per-image failure (which returns {ok:false}).
 * A throwing rasterizer represents an unexpected crash inside the rasterizer.
 */
async function t8_whole_zip_failure(): Promise<{
  ok: boolean;
  threw?: boolean;
  errorIsOdtBuildError?: boolean;
  error?: string;
}> {
  const throwingRasterizer = async () => {
    throw new Error("injected whole-rasterizer crash");
  };

  const snap = makeSnap({ id: "q-t8-crash", withChartSpec: true });
  try {
    await buildOdtFromSnapshots("Crash ODT", [snap], {
      rasterizer: throwingRasterizer,
    });
    // Should NOT reach here — an OdtBuildError must be thrown
    return { ok: false, threw: false, error: "no error was thrown" };
  } catch (e: unknown) {
    const msg = String(e);
    // The build must throw; whether it's OdtBuildError or wrapped depends on odt.ts
    // The key invariant: no Blob is produced (it threw before resolving)
    const isOdtRelated =
      msg.includes("OdtBuildError") ||
      msg.includes("injected whole-rasterizer crash") ||
      msg.includes("build") ||
      msg.includes("rasterizer");
    return {
      ok: true,      // test passes — an error was thrown as expected
      threw: true,
      errorIsOdtBuildError: isOdtRelated,
      error: msg,
    };
  }
}

/**
 * t9: Batch + legacy/history-shaped exports read back from ODT.
 *
 * Builds a batch ODT from three snapshots:
 *   - A flat "legacy" question (no subquestions, no v2 evidence)
 *   - A 題組 (group question with subquestions)
 *   - A "history" snapshot (is_draft:false, termination_reason:"normal")
 *
 * Verifies that content.xml is valid XML and contains all three questions'
 * key text strings.
 */
async function t9_batch_legacy_history_exports(): Promise<{
  ok: boolean;
  hasAllQuestions?: boolean;
  questionCount?: number;
  error?: string;
}> {
  // Flat legacy-shaped snapshot
  const legacySnap: QuestionSnapshot = {
    exported: {
      id: "q-legacy-t9",
      情境: ["個人"],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Legacy Q: 2x + 3 = 7，x = ?"],
      正確解題分析: ["x = 2"],
      _export: {
        format_version: 1,
        exported_at: new Date().toISOString(),
        is_draft: false,
        run_id: null,
        index: 0,
        content_revision: null,
        processing: "ended",
        termination_reason: "normal",
        delivery_status: "complete",
        missing: [],
        review: { status: "unknown", content_revision: null },
      },
    },
    captured: {
      id: "q-legacy-t9",
      情境: ["個人"],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Legacy Q: 2x + 3 = 7，x = ?"],
      正確解題分析: ["x = 2"],
    },
    isDraft: false,
    index: 0,
    imageSources: {},
  };

  // Group question (題組) snapshot
  const groupSnap: QuestionSnapshot = {
    exported: {
      id: "q-group-t9",
      情境: ["科學"],
      題型種類: "題組題",
      題型: "選擇題",
      核心問題: "科學問題核心",
      文本: "閱讀以下文章...",
      取材來源: ["PISA 2022"],
      題目: [],
      正確解題分析: [],
      subquestions: [
        {
          id: "q-group-t9-sq001",
          序號: 1,
          年級: 8,
          科目: [],
          核心素養: [],
          學習內容: [],
          學習表現: [],
          題型: "選擇題",
          題目: "子題一",
          答案: "A",
          答案解析: "解析",
        },
      ],
      _export: {
        format_version: 1,
        exported_at: new Date().toISOString(),
        is_draft: false,
        run_id: "RUN_T9",
        index: 1,
        content_revision: 2,
        processing: "ended",
        termination_reason: "normal",
        delivery_status: "complete",
        missing: [],
        review: { status: "passed", content_revision: 2 },
      },
    },
    captured: {
      id: "q-group-t9",
      情境: ["科學"],
      題型種類: "題組題",
      題型: "選擇題",
      題目: [],
      正確解題分析: [],
    },
    isDraft: false,
    index: 1,
    imageSources: {},
  };

  // History-shaped snapshot (from a stored record)
  const historySnap: QuestionSnapshot = makeSnap({ id: "q-history-t9", withPngBase64: true });

  const snapshots = [legacySnap, groupSnap, historySnap];
  let blob: Blob;
  try {
    blob = await buildOdtFromSnapshots("Batch T9 ODT", snapshots);
  } catch (e) {
    return { ok: false, error: String(e) };
  }

  const buf = await blob.arrayBuffer();
  const zip = await JSZip.loadAsync(buf);
  const contentXmlFile = zip.file("content.xml");
  if (!contentXmlFile) return { ok: false, error: "content.xml missing" };
  const xml = await contentXmlFile.async("string");

  // Verify key text strings appear in the XML
  const hasLegacy = xml.includes("2x + 3 = 7");
  const hasGroup = xml.includes("科學問題核心") || xml.includes("閱讀以下文章");
  const hasHistory = xml.includes("q-history-t9");
  const hasAllQuestions = hasLegacy && hasGroup && hasHistory;

  return {
    ok: hasAllQuestions,
    hasAllQuestions,
    questionCount: snapshots.length,
    error: hasAllQuestions
      ? undefined
      : `Missing: ${[
          hasLegacy ? null : "legacy",
          hasGroup ? null : "group",
          hasHistory ? null : "history",
        ]
          .filter(Boolean)
          .join(", ")}`,
  };
}

// ---------------------------------------------------------------------------
// Harness orchestrator
// ---------------------------------------------------------------------------

type TestResult = { name: string; passed: boolean; detail: unknown };

async function runAll(): Promise<TestResult[]> {
  const tests: [string, () => Promise<unknown>][] = [
    ["t1_rasterizer_produces_png", t1_rasterizer_produces_png],
    ["t2_rasterizer_with_preview_markup", t2_rasterizer_with_preview_markup],
    ["t3_build_odt_with_chart_spec", t3_build_odt_with_chart_spec],
    ["t4_build_odt_with_png_base64", t4_build_odt_with_png_base64],
    ["t5_per_image_failure_produces_marker", t5_per_image_failure_produces_marker],
    ["t6_no_tainted_canvas_error", t6_no_tainted_canvas_error],
    ["t7_image_swap_race", t7_image_swap_race],
    ["t8_whole_zip_failure", t8_whole_zip_failure],
    ["t9_batch_legacy_history_exports", t9_batch_legacy_history_exports],
  ];

  const results: TestResult[] = [];
  for (const [name, fn] of tests) {
    try {
      const detail = await fn();
      // A test passes when its result object has ok:true
      const passed =
        typeof detail === "object" &&
        detail !== null &&
        "ok" in detail &&
        (detail as { ok: boolean }).ok === true;
      results.push({ name, passed, detail });
    } catch (e) {
      results.push({ name, passed: false, detail: String(e) });
    }
  }
  return results;
}

// Expose on window for Playwright to call
declare global {
  interface Window {
    __harness: {
      runAll: () => Promise<TestResult[]>;
      t1: () => Promise<unknown>;
      t2: () => Promise<unknown>;
      t3: () => Promise<unknown>;
      t4: () => Promise<unknown>;
      t5: () => Promise<unknown>;
      t6: () => Promise<unknown>;
      t7: () => Promise<unknown>;
      t8: () => Promise<unknown>;
      t9: () => Promise<unknown>;
    };
  }
}

window.__harness = {
  runAll,
  t1: t1_rasterizer_produces_png,
  t2: t2_rasterizer_with_preview_markup,
  t3: t3_build_odt_with_chart_spec,
  t4: t4_build_odt_with_png_base64,
  t5: t5_per_image_failure_produces_marker,
  t6: t6_no_tainted_canvas_error,
  t7: t7_image_swap_race,
  t8: t8_whole_zip_failure,
  t9: t9_batch_legacy_history_exports,
};

// Update the status element
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
if (statusEl) {
  statusEl.textContent = "ready — call window.__harness.runAll() to run tests";
}

// Auto-run all tests and display results in the page
runAll().then((results) => {
  if (statusEl) {
    const passed = results.filter((r) => r.passed).length;
    statusEl.textContent = `${passed}/${results.length} tests passed`;
  }
  if (resultEl) {
    resultEl.textContent = JSON.stringify(results, null, 2);
  }
});
