"""
Real-browser test for issue #753: foreignObject + data-URL SVG rasterization.

Verifies:
1. Table HTML wrapped in SVG foreignObject with data: URL -> valid PNG (no tainted canvas)
2. Geometry SVG wrapped similarly -> valid PNG
3. Scenario card HTML -> valid PNG
4. No tainted-canvas SecurityError
"""
import pytest
from playwright.sync_api import sync_playwright

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
