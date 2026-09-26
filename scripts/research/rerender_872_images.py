"""Re-render 872-counting-stem-figure-route chart images with CJK font.

WenQuanYi Zen Hei IS installed at /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc
but is not in src/renderer.py's _CJK_FONTS list (production file; cannot modify).

This script registers the font with matplotlib BEFORE importing src.renderer
(whose _setup_chinese_font() runs at module import), then re-renders all four
chart images so that Chinese axis labels and titles are legible.

Run from the repo root:
    uv run python scripts/research/rerender_872_images.py
"""

from __future__ import annotations

import pathlib
import sys

# ── 1. Register WenQuanYi Zen Hei BEFORE any matplotlib import ─────────────
_WQY_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
if pathlib.Path(_WQY_PATH).exists():
    import matplotlib
    import matplotlib.font_manager as _fm
    _fm.fontManager.addfont(_WQY_PATH)
    import matplotlib.pyplot as _plt
    _plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei"] + _plt.rcParams["font.sans-serif"]
    _plt.rcParams["axes.unicode_minus"] = False
    print(f"[font] WenQuanYi Zen Hei registered from {_WQY_PATH}", file=sys.stderr)
else:
    print(f"[warn] Font not found at {_WQY_PATH} — labels may render as tofu", file=sys.stderr)

# ── 2. Path setup ────────────────────────────────────────────────────────────
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.renderer import render_chart  # noqa: E402

IMAGE_DIR = ROOT / "docs" / "research" / "872-counting-stem-figure-route" / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# ── 3. Chart specs (copied verbatim from rubric_872_harness.py) ──────────────

CHART_SPECS: dict[str, dict] = {
    "chart_A": {
        "render_mode": "chart",
        "chart_type": "histogram",
        "title": "四組實驗的溫度變化（°C）",
        "data": {
            "bins": ["甲", "乙", "丙", "丁"],
            "counts": [12, 8, 15, 5],
        },
        "labels": {"x": "實驗組", "y": "溫度變化（°C）"},
    },
    "chart_B": {
        # Switched from line_chart (series format unsupported) to histogram.
        "render_mode": "chart",
        "chart_type": "histogram",
        "title": "三種處理方式第5天細胞存活率（%）",
        "data": {
            "bins": ["處理A", "處理B", "處理C"],
            "counts": [30, 62, 25],
        },
        "labels": {"x": "處理方式", "y": "第5天細胞存活率（%）"},
    },
    "chart_C": {
        # Switched from line_chart (series format unsupported) to histogram.
        "render_mode": "chart",
        "chart_type": "histogram",
        "title": "高溫與低溫下的最高光合速率比較",
        "data": {
            "bins": ["高溫（35°C）", "低溫（15°C）"],
            "counts": [20, 13],
        },
        "labels": {"x": "溫度條件", "y": "最高光合速率（μmol CO₂/m²/s）"},
    },
    "chart_D": {
        "render_mode": "chart",
        "chart_type": "pie_chart",
        "title": "校園廢棄物組成比例",
        "data": {
            "segments": [
                {"label": "廚餘 45%", "angle": 162},
                {"label": "紙類 30%", "angle": 108},
                {"label": "塑膠 25%", "angle": 90},
            ]
        },
        "labels": {},
    },
}

# ── 4. Render ────────────────────────────────────────────────────────────────

for chart_key, spec in CHART_SPECS.items():
    out_path = IMAGE_DIR / f"fig_{chart_key}.png"
    result = render_chart(spec, out_path)
    if result:
        print(f"  rendered: {out_path}", file=sys.stderr)
    else:
        print(f"  [WARN] render_chart returned None for {chart_key}", file=sys.stderr)

print("Done.", file=sys.stderr)
