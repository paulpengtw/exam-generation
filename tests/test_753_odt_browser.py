"""
Real-browser tests for issue #753: ODT export rasterization.

Tests in two groups:
1. Raw SVG foreignObject + data-URL rasterization (no modules needed).
2. End-to-end ODT export via the real modules served by the vite dev server
   (rasterizer.ts, odt.ts, exportSnapshot.ts).

The second group requires the vite dev server running at HARNESS_URL (default
http://localhost:5173/test-harness/odt-export.html).  If the server is not
reachable, those tests are skipped.
"""
import os
import subprocess
import time
import urllib.request
import urllib.error
import pytest
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HARNESS_URL = os.environ.get(
    "HARNESS_URL",
    "http://localhost:5173/test-harness/odt-export.html",
)
VITE_STARTUP_TIMEOUT = 20  # seconds to wait for vite to be ready


# ---------------------------------------------------------------------------
# Raw SVG foreignObject tests (no vite needed)
# ---------------------------------------------------------------------------

TABLE_HTML = (
    "<table style='border-collapse:collapse;font-size:14px'>"
    "<thead><tr>"
    "<th style='border:1px solid #ccc;padding:4px 8px;background:#f5f5f5'>欄位A</th>"
    "<th style='border:1px solid #ccc;padding:4px 8px;background:#f5f5f5'>欄位B</th>"
    "</tr></thead>"
    "<tbody><tr>"
    "<td style='border:1px solid #ccc;padding:4px 8px'>值1</td>"
    "<td style='border:1px solid #ccc;padding:4px 8px'>值2</td>"
    "</tr></tbody>"
    "</table>"
)

SCENARIO_HTML = (
    "<div style='border:1px solid #f59e0b;background:#fffbeb;"
    "border-radius:4px;padding:12px'>"
    "<div style='font-weight:bold;color:#7a5000;font-size:13px'>"
    "情境卡：早餐菜單</div>"
    "<ul style='margin:4px 0 0 16px;padding:0;color:#7a5000;font-size:12px'>"
    "<li>豆漿 35元</li><li>燒餅 20元</li>"
    "</ul></div>"
)

_RASTERIZE_FN = """
async (htmlMarkup) => {
    const W = 480, H = 120;
    const inner = [
        '<div xmlns="http://www.w3.org/1999/xhtml"',
        ' style="width:' + W + 'px;min-height:' + H + 'px;',
        'background:white;padding:8px;box-sizing:border-box">',
        htmlMarkup,
        '</div>',
    ].join('');
    const svgStr = [
        '<svg xmlns="http://www.w3.org/2000/svg"',
        ' width="' + W + '" height="' + H + '">',
        '<foreignObject x="0" y="0"',
        ' width="' + W + '" height="' + H + '">',
        inner,
        '</foreignObject></svg>',
    ].join('');
    const dataUrl = 'data:image/svg+xml;charset=utf-8,'
        + encodeURIComponent(svgStr);
    const img = new Image();
    img.crossOrigin = 'anonymous';
    await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
        img.src = dataUrl;
    });
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const png = canvas.toDataURL('image/png');
    return { ok: true, byteLength: atob(png.split(',')[1]).length };
}
"""

_NO_TAINT_FN = """
async () => {
    try {
        const svgStr = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">',
            '<foreignObject x="0" y="0" width="100" height="100">',
            '<div xmlns="http://www.w3.org/1999/xhtml"><p>test</p></div>',
            '</foreignObject></svg>',
        ].join('');
        const url = 'data:image/svg+xml;charset=utf-8,'
            + encodeURIComponent(svgStr);
        const img = new Image(); img.crossOrigin = 'anonymous';
        await new Promise((res, rej) => {
            img.onload = res; img.onerror = rej; img.src = url;
        });
        const canvas = document.createElement('canvas');
        canvas.width = 100; canvas.height = 100;
        canvas.getContext('2d').drawImage(img, 0, 0);
        canvas.toDataURL('image/png');
        return null;
    } catch (e) { return e.message; }
}
"""


@pytest.mark.requires_browser
def test_foreign_object_data_url_table():
    """foreignObject + data: URL -> valid PNG, no tainted canvas."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        result = page.evaluate(_RASTERIZE_FN, TABLE_HTML)
        browser.close()
    assert result["ok"] is True
    assert result["byteLength"] > 500  # non-trivial PNG


@pytest.mark.requires_browser
def test_foreign_object_data_url_scenario():
    """Scenario card HTML -> valid PNG via foreignObject data: URL."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        result = page.evaluate(_RASTERIZE_FN, SCENARIO_HTML)
        browser.close()
    assert result["ok"] is True
    assert result["byteLength"] > 200


@pytest.mark.requires_browser
def test_no_tainted_canvas_error():
    """Verify no SecurityError is thrown -- this was the original bug."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        error = page.evaluate(_NO_TAINT_FN)
        browser.close()
    assert error is None, f"Expected no error, got: {error}"


# ---------------------------------------------------------------------------
# Helpers for vite-served harness tests
# ---------------------------------------------------------------------------

def _vite_reachable() -> bool:
    """Return True if the vite dev server is already listening at HARNESS_URL."""
    try:
        urllib.request.urlopen(HARNESS_URL, timeout=2)
        return True
    except Exception:
        return False


def _wait_for_vite(proc: subprocess.Popen, timeout: int = VITE_STARTUP_TIMEOUT) -> bool:
    """Poll until vite is reachable or timeout expires. Returns True on success."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _vite_reachable():
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Vite-served harness tests — exercises the REAL modules
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def vite_server():
    """
    Start (or reuse) the vite dev server for the duration of the test module.

    If HARNESS_URL is already reachable (e.g. already running in CI), the
    server is not started and is not stopped after the tests.  Otherwise a
    subprocess is started and killed after all module tests complete.
    """
    already_running = _vite_reachable()
    proc = None
    if not already_running:
        proc = subprocess.Popen(
            ["npx", "vite", "--port", "5173", "--strictPort"],
            cwd=os.path.join(os.path.dirname(__file__), "..", "web"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not _wait_for_vite(proc):
            proc.kill()
            pytest.skip("vite dev server did not start in time — skipping harness tests")
    yield
    if proc is not None:
        proc.kill()


def _run_harness_test(page, fn_name: str) -> dict:
    """Call a named harness function and return its result dict."""
    return page.evaluate(f"() => window.__harness.{fn_name}()")


def _open_harness(browser, url: str):
    """Open the harness page and wait until __harness is available."""
    page = browser.new_page()
    page.goto(url, wait_until="networkidle")
    page.wait_for_function("() => typeof window.__harness !== 'undefined'", timeout=15_000)
    return page


@pytest.mark.requires_browser
def test_harness_rasterizer_produces_png(vite_server):
    """
    t1 (real modules): defaultRasterizer produces a valid PNG for a
    chart_spec_preview slot in a real Chromium browser.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = _open_harness(browser, HARNESS_URL)
        result = _run_harness_test(page, "t1")
        browser.close()
    assert result.get("ok") is True, f"t1 failed: {result}"
    assert result.get("byteLength", 0) > 100, f"PNG too small: {result}"


@pytest.mark.requires_browser
def test_harness_rasterizer_with_preview_markup(vite_server):
    """
    t2 (real modules): defaultRasterizer uses previewMarkup (same-source
    rendering path) and still produces a valid PNG.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = _open_harness(browser, HARNESS_URL)
        result = _run_harness_test(page, "t2")
        browser.close()
    assert result.get("ok") is True, f"t2 failed: {result}"
    assert result.get("byteLength", 0) > 100, f"PNG too small: {result}"


@pytest.mark.requires_browser
def test_harness_build_odt_with_chart_spec(vite_server):
    """
    t3 (real modules): buildOdtFromSnapshots embeds a rasterized PNG for a
    chart_spec_preview slot — the ZIP has content.xml and a .png file.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = _open_harness(browser, HARNESS_URL)
        result = _run_harness_test(page, "t3")
        browser.close()
    assert result.get("ok") is True, f"t3 failed: {result}"
    assert result.get("hasContentXml") is True
    assert result.get("hasPng") is True
    assert result.get("byteLength", 0) > 1000, "ODT too small"


@pytest.mark.requires_browser
def test_harness_build_odt_with_png_base64(vite_server):
    """
    t4 (real modules): buildOdtFromSnapshots embeds a pre-supplied base64 PNG
    directly — the ZIP has the PNG embedded.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = _open_harness(browser, HARNESS_URL)
        result = _run_harness_test(page, "t4")
        browser.close()
    assert result.get("ok") is True, f"t4 failed: {result}"
    assert result.get("hasPng") is True


@pytest.mark.requires_browser
def test_harness_per_image_failure_produces_marker(vite_server):
    """
    t5 (real modules): when a rasterizer injection always fails, the ODT
    still builds (no OdtBuildError thrown) and content.xml contains the
    「匯出缺圖／預覽轉換失敗」 failure marker — no PNG is embedded.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = _open_harness(browser, HARNESS_URL)
        result = _run_harness_test(page, "t5")
        browser.close()
    assert result.get("ok") is True, f"t5 failed: {result}"
    assert result.get("hasMarker") is True, "Failure marker missing from ODT"
    assert result.get("hasPng") is False, "PNG must not be embedded on rasterizer failure"


@pytest.mark.requires_browser
def test_harness_no_tainted_canvas_error(vite_server):
    """
    t6 (real modules): the SVG foreignObject + data: URL path does NOT
    raise a SecurityError in the real Chromium context.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = _open_harness(browser, HARNESS_URL)
        result = _run_harness_test(page, "t6")
        browser.close()
    assert result.get("ok") is True, f"t6 (tainted-canvas test) failed: {result}"
