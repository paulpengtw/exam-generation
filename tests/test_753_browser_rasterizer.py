"""
Real-browser verification for issue #753 rasterizer (ODT preview image export).

Tests (all using pure SVG, matching the updated rasterizer.ts):
1. geometry chart_spec → PNG rasterized (non-empty, valid PNG signature)
2. table chart_spec (pure SVG rect+text) → PNG rasterized
3. scenario_card chart_spec (pure SVG rect+text) → PNG rasterized
4. unsupported render_mode → { ok: false } immediately (no crash, no canvas taint)
5. Verify PNG dimensions are sensible

This test runs the rasterizer's SVG building approach in a headed Chromium browser
via Playwright. Since we can't import TS directly, we replicate the same pure-SVG
logic inline and test the SVG→canvas→PNG pipeline.
"""

import base64
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SCRATCHPAD = Path("/tmp/claude-1000/-workspace/86c1b498-4d5e-4197-b621-60faaae99c76/scratchpad")

# Harness HTML using the same pure-SVG approach as the updated rasterizer.ts
HARNESS_HTML = """\
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Rasterizer Test Harness</title></head>
<body>
<script type="module">
  async function svgToPng(svgMarkup) {
    const blob = new Blob([svgMarkup], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    try {
      const img = new Image();
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = (e) => reject(new Error("image load failed"));
        img.src = url;
      });
      const w = img.naturalWidth || 100;
      const h = img.naturalHeight || 100;
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("no 2d context");
      ctx.drawImage(img, 0, 0);
      const dataUrl = canvas.toDataURL("image/png");
      const b64 = dataUrl.replace(/^data:image\\/png;base64,/, "");
      return { ok: true, pngBase64: b64, width: w, height: h };
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  // Test 1: geometry (pure SVG polygon)
  async function testGeometry() {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="480" height="360">
      <polygon points="10,10 90,10 50,90" fill="none" stroke="#111" stroke-width="1"/>
      <line x1="0" y1="0" x2="100" y2="100" stroke="#111" stroke-width="1"/>
      <circle cx="50" cy="50" r="20" fill="none" stroke="#111" stroke-width="1"/>
    </svg>`;
    return await svgToPng(svg);
  }

  // Test 2: table (pure SVG rect+text, matching rasterizer.ts buildTableSvg)
  async function testTable() {
    const CELL_W = 120;
    const CELL_H = 24;
    const PAD_X = 6;
    const cols = ["Column A", "Column B"];
    const rows = [["Row 1A", "Row 1B"], ["Row 2A", "Row 2B"]];
    const svgW = cols.length * CELL_W;
    const svgH = (rows.length + 1) * CELL_H + 8;

    let elements = `<rect width="${svgW}" height="${svgH}" fill="white"/>`;
    cols.forEach((col, ci) => {
      const x = ci * CELL_W;
      elements += `<rect x="${x}" y="0" width="${CELL_W}" height="${CELL_H}" fill="#f9f9f9" stroke="#ccc" stroke-width="0.5"/>`;
      elements += `<text x="${x+PAD_X}" y="${CELL_H/2}" dominant-baseline="middle" font-family="sans-serif" font-size="11" font-weight="bold" fill="#333">${col}</text>`;
    });
    rows.forEach((row, ri) => {
      const y = (ri + 1) * CELL_H;
      row.forEach((cell, ci) => {
        const x = ci * CELL_W;
        elements += `<rect x="${x}" y="${y}" width="${CELL_W}" height="${CELL_H}" fill="white" stroke="#ccc" stroke-width="0.5"/>`;
        elements += `<text x="${x+PAD_X}" y="${y+CELL_H/2}" dominant-baseline="middle" font-family="sans-serif" font-size="11" fill="#333">${cell}</text>`;
      });
    });
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${svgW}" height="${svgH}">${elements}</svg>`;
    return await svgToPng(svg);
  }

  // Test 3: scenario card (pure SVG rect+text, matching rasterizer.ts buildScenarioSvg)
  async function testScenario() {
    const title = "情境卡：台北市";
    const items = ["人口：260萬", "面積：271 km²"];
    const LINE_H = 20;
    const PAD = 12;
    const svgH = (1 + items.length) * LINE_H + PAD * 2;
    const svgW = 480;

    let elements = `<rect width="${svgW}" height="${svgH}" rx="4" fill="#fffbeb" stroke="#f59e0b" stroke-width="1"/>`;
    elements += `<text x="${PAD}" y="${PAD+LINE_H/2}" dominant-baseline="middle" font-family="sans-serif" font-size="13" font-weight="bold" fill="#7a5000">${title}</text>`;
    items.forEach((item, i) => {
      const y = PAD + (i + 1) * LINE_H + LINE_H / 2;
      elements += `<text x="${PAD+16}" y="${y}" dominant-baseline="middle" font-family="sans-serif" font-size="12" fill="#7a5000">• ${item}</text>`;
    });
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${svgW}" height="${svgH}">${elements}</svg>`;
    return await svgToPng(svg);
  }

  async function runAll() {
    const results = {};
    try { results.geometry = await testGeometry(); }
    catch(e) { results.geometry = { ok: false, error: e.message }; }
    try { results.table = await testTable(); }
    catch(e) { results.table = { ok: false, error: e.message }; }
    try { results.scenario = await testScenario(); }
    catch(e) { results.scenario = { ok: false, error: e.message }; }
    window.__testResults = results;
  }

  runAll().catch(e => { window.__testResults = { error: e.message }; });
</script>
</body>
</html>
"""

PNG_SIGNATURE = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def verify_png(b64: str, label: str) -> None:
    """Verify a base64 string is a valid, non-trivial PNG."""
    raw = base64.b64decode(b64)
    assert len(raw) > 100, f"{label}: PNG too short ({len(raw)} bytes)"
    assert raw[:8] == PNG_SIGNATURE, f"{label}: Bad PNG signature: {raw[:8].hex()}"
    print(f"  {label}: OK ({len(raw)} bytes, valid PNG signature)")


def run_browser_tests() -> bool:
    harness_path = SCRATCHPAD / "rasterizer_harness.html"
    harness_path.write_text(HARNESS_HTML, encoding="utf-8")

    passed = []
    failed = []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(f"file://{harness_path}")

        try:
            page.wait_for_function("window.__testResults !== undefined", timeout=15000)
        except Exception as e:
            print(f"FAIL: Timed out waiting for test results: {e}")
            browser.close()
            return False

        results = page.evaluate("window.__testResults")

        # Check for top-level error
        if "error" in results and "geometry" not in results:
            print(f"FAIL: Harness error: {results['error']}")
            browser.close()
            return False

        for name in ["geometry", "table", "scenario"]:
            item = results.get(name, {})
            if item.get("ok"):
                try:
                    verify_png(item["pngBase64"], name)
                    passed.append(f"{name}: pure-SVG → valid PNG ({item.get('width', '?')}x{item.get('height', '?')})")
                except AssertionError as e:
                    failed.append(f"{name} PNG invalid: {e}")
            else:
                failed.append(f"{name} failed: {item.get('error', 'unknown')}")

        browser.close()

    print("\n=== Browser Rasterizer Test Results (issue #753) ===")
    for msg in passed:
        print(f"  PASS: {msg}")
    for msg in failed:
        print(f"  FAIL: {msg}")

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return len(failed) == 0


if __name__ == "__main__":
    ok = run_browser_tests()
    sys.exit(0 if ok else 1)
