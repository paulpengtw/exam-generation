"""matplotlib image renderer for chart and diagram generation."""

from __future__ import annotations

import platform
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

matplotlib.use("Agg")  # Non-interactive backend for CLI

# Configure Chinese font support
_CJK_FONTS = [
    "Noto Sans CJK TC",
    "PingFang TC",
    "Heiti TC",
    "Microsoft JhengHei",
    "SimHei",
    "AR PL UMing TW",
]


def _setup_chinese_font() -> None:
    """Configure matplotlib to use a CJK font for Chinese labels."""
    if platform.system() == "Darwin":
        # macOS has PingFang built-in
        preferred = ["PingFang TC", "Heiti TC"] + _CJK_FONTS
    else:
        preferred = _CJK_FONTS

    for font in preferred:
        try:
            matplotlib.font_manager.findfont(font, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [font] + plt.rcParams["font.sans-serif"]
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            continue

    # Fallback: just disable minus sign issue
    plt.rcParams["axes.unicode_minus"] = False


_setup_chinese_font()


def render_chart(chart_spec: dict, output_path: str | Path) -> str | None:
    """Render a statistical chart from a chart_spec dict and save as PNG.

    Handles render_mode="chart" types: histogram, boxplot, line_chart, pie_chart.
    Returns the output path on success, or None if chart_type is unknown.
    """
    output_path = Path(output_path)
    chart_type = chart_spec.get("chart_type", "")

    renderers = {
        "histogram": _render_histogram,
        "boxplot": _render_boxplot,
        "line_chart": _render_line_chart,
        "pie_chart": _render_pie_chart,
    }

    renderer = renderers.get(chart_type)
    if renderer is None:
        return None

    renderer(chart_spec, output_path)
    return str(output_path)


def _render_histogram(spec: dict, output_path: Path) -> None:
    """Render a histogram (直方圖)."""
    data = spec.get("data", {})
    labels_spec = spec.get("labels", {})
    title = spec.get("title", "")

    bins = data.get("bins", [])
    counts = data.get("counts", [])

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(bins))
    bars = ax.bar(x, counts, width=0.8, color="#4C72B0", edgecolor="white", linewidth=1.2)

    # Add value labels on bars
    for bar, count in zip(bars, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            str(count),
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(bins, fontsize=10)
    ax.set_xlabel(labels_spec.get("x", ""), fontsize=12)
    ax.set_ylabel(labels_spec.get("y", ""), fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _render_boxplot(spec: dict, output_path: Path) -> None:
    """Render side-by-side boxplots from five-number summaries."""
    data = spec.get("data", {})
    labels_spec = spec.get("labels", {})
    title = spec.get("title", "")

    fig, ax = plt.subplots(figsize=(7, 5))

    positions = []
    tick_labels = []
    for i, (label, stats) in enumerate(data.items()):
        pos = i + 1
        positions.append(pos)
        tick_labels.append(label)

        min_val = stats["min"]
        q1 = stats["Q1"]
        median = stats["median"]
        q3 = stats["Q3"]
        max_val = stats["max"]

        # Draw box
        box_width = 0.4
        box = patches.FancyBboxPatch(
            (pos - box_width / 2, q1),
            box_width,
            q3 - q1,
            boxstyle="round,pad=0.02",
            facecolor=f"C{i}",
            alpha=0.3,
            edgecolor=f"C{i}",
            linewidth=2,
        )
        ax.add_patch(box)

        # Median line
        ax.hlines(median, pos - box_width / 2, pos + box_width / 2, colors=f"C{i}", linewidth=2.5)

        # Whiskers
        ax.vlines(pos, min_val, q1, colors=f"C{i}", linewidth=1.5)
        ax.vlines(pos, q3, max_val, colors=f"C{i}", linewidth=1.5)

        # Caps
        cap_width = 0.15
        ax.hlines(min_val, pos - cap_width, pos + cap_width, colors=f"C{i}", linewidth=1.5)
        ax.hlines(max_val, pos - cap_width, pos + cap_width, colors=f"C{i}", linewidth=1.5)

        # Annotate five-number summary (use ASCII-safe labels to avoid missing glyph warnings)
        for val, label_text in [(min_val, f"{min_val}"), (q1, f"Q1={q1}"), (median, f"Med={median}"), (q3, f"Q3={q3}"), (max_val, f"{max_val}")]:
            ax.annotate(
                label_text,
                (pos + box_width / 2 + 0.05, val),
                fontsize=8,
                va="center",
            )

    ax.set_xticks(positions)
    ax.set_xticklabels(tick_labels, fontsize=12)
    ax.set_xlabel(labels_spec.get("x", ""), fontsize=12)
    ax.set_ylabel(labels_spec.get("y", ""), fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _render_line_chart(spec: dict, output_path: Path) -> None:
    """Render a line chart (折線圖)."""
    data = spec.get("data", {})
    labels_spec = spec.get("labels", {})
    title = spec.get("title", "")

    fig, ax = plt.subplots(figsize=(8, 5))

    if "x_labels" in data and "y_values" in data:
        # Explicit data points
        x_labels = data["x_labels"]
        y_values = data["y_values"]
        x = np.arange(len(x_labels))
        ax.plot(x, y_values, "o-", color="#4C72B0", linewidth=2, markersize=8)
        for xi, yi in zip(x, y_values):
            ax.annotate(str(yi), (xi, yi), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, fontsize=10)
    elif "function" in data:
        # Function-based line
        x_range = data.get("x_range", [0, 20])
        x = np.linspace(x_range[0], x_range[1], 200)
        # Parse simple linear function y = ax + b
        func_str = data["function"]
        # Extract coefficients from "y = ax + b" format
        import re
        match = re.match(r"y\s*=\s*([-]?\d*\.?\d*)\s*x\s*([+-]\s*\d+\.?\d*)", func_str)
        if match:
            a = float(match.group(1)) if match.group(1) not in ("", "-") else (-1.0 if match.group(1) == "-" else 1.0)
            b = float(match.group(2).replace(" ", ""))
            y = a * x + b
            ax.plot(x, y, color="#4C72B0", linewidth=2)
            # Mark key points
            if "points" in data:
                for px, py in data["points"]:
                    ax.plot(px, py, "o", color="#E74C3C", markersize=8)
                    ax.annotate(f"({px}, {py})", (px, py), textcoords="offset points", xytext=(10, 5), fontsize=9)

    ax.set_xlabel(labels_spec.get("x", ""), fontsize=12)
    ax.set_ylabel(labels_spec.get("y", ""), fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _render_pie_chart(spec: dict, output_path: Path) -> None:
    """Render a pie/spinner chart (圓形圖/轉盤)."""
    data = spec.get("data", {})
    title = spec.get("title", "")

    segments = data.get("segments", [])
    if not segments:
        return

    fig, ax = plt.subplots(figsize=(6, 6))

    angles = [s["angle"] for s in segments]
    labels = [s["label"] for s in segments]
    colors = [s.get("color", f"C{i}") for i, s in enumerate(segments)]

    # Normalize angles to fractions
    total = sum(angles)
    sizes = [a / total for a in angles]

    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        autopct=lambda pct: f"{pct:.0f}%\n({int(pct/100*total)}°)",
        startangle=90,
        counterclock=False,
        textprops={"fontsize": 12},
        wedgeprops={"edgecolor": "white", "linewidth": 2},
    )

    for autotext in autotexts:
        autotext.set_fontsize(9)

    ax.set_title(title, fontsize=14, fontweight="bold")

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def render_image(
    image_spec: dict,
    output_path: str | Path,
    question_text: str = "",
    html_renderer=None,
    llm_client=None,
) -> str | None:
    """Render a question image from an ImageSpec dict and save as PNG.

    Dispatches based on render_mode:
    - "chart": matplotlib renderers (deterministic, data-driven)
    - "html": LLM generates HTML/CSS/SVG → Playwright renders to PNG

    Returns the output path on success, or None on failure.
    """
    import sys
    render_mode = image_spec.get("render_mode", "chart")

    if render_mode == "chart":
        return render_chart(image_spec, output_path)

    if render_mode == "html":
        html = image_spec.get("html", "")
        if not html and llm_client is not None:
            html = _generate_html_via_llm(image_spec, question_text, llm_client)
        if not html:
            print("  Warning: no HTML content to render", file=sys.stderr)
            return None
        if html_renderer is None:
            print("  Warning: html render_mode requires PlaywrightRenderer", file=sys.stderr)
            return None
        try:
            return html_renderer.render(html, output_path)
        except Exception as e:
            print(f"  Warning: Playwright render failed: {e}", file=sys.stderr)
            return None

    print(f"  Warning: unknown render_mode '{render_mode}'", file=sys.stderr)
    return None


_HTML_SYSTEM_PROMPT = """\
You are an HTML/CSS/SVG visual designer for Taiwanese junior high school math exam questions.
Generate a self-contained HTML document that renders a clear, exam-appropriate image.

Rules:
- Output ONLY a complete <!DOCTYPE html> document — no explanation, no markdown
- All CSS must be inline (no external stylesheets, no CDN links)
- No external resources (no image URLs, no web fonts)
- Font stack: 'PingFang TC', 'Noto Sans TC', 'Microsoft JhengHei', 'Microsoft YaHei', sans-serif
- Design for 800px viewport width; keep height compact (fit content)
- Use inline SVG for geometry diagrams, coordinate planes, number lines, and schematic drawings
- Use styled divs/tables for menus, price tables, data tables, and comparison layouts
- Style should be clean and exam-like — minimal decoration, high readability
- All Chinese text must display correctly with the font stack above
- Background: white (#ffffff) or very light
"""

_HTML_USER_TEMPLATE = """\
Generate the HTML image for this exam question.

Question context (for understanding what the image supports):
{question_text}

Image description (what to draw):
{description}

Numerical data (if any):
{data}
"""


def _generate_html_via_llm(spec: dict, question_text: str, llm_client) -> str:
    """Ask the LLM to generate an HTML document for the given image spec.

    Retries once on failure. Returns empty string if both attempts fail.
    """
    import json
    import re
    import sys

    description = spec.get("description", spec.get("title", ""))
    data = spec.get("data", {})
    prompt = _HTML_USER_TEMPLATE.format(
        question_text=question_text[:600] if question_text else "（無）",
        description=description,
        data=json.dumps(data, ensure_ascii=False, indent=2) if data else "（無）",
    )

    for attempt in range(2):
        try:
            if attempt > 0:
                print("  Retrying HTML generation...", file=sys.stderr)
            else:
                print("  Generating HTML image via LLM...", file=sys.stderr)

            raw = llm_client.generate(_HTML_SYSTEM_PROMPT, prompt)

            # Extract HTML from code block if wrapped
            match = re.search(r"```(?:html)?\s*\n(.*?)\n```", raw, re.DOTALL)
            if match:
                return match.group(1).strip()

            stripped = raw.strip()
            if stripped.startswith("<!DOCTYPE") or stripped.lower().startswith("<html"):
                return stripped

            # Unexpected format — retry with clarification
            prompt = prompt + "\n\nIMPORTANT: Output ONLY the raw <!DOCTYPE html> document. No explanation."

        except Exception as e:
            print(f"  Warning: HTML generation attempt {attempt + 1} failed: {e}", file=sys.stderr)

    return ""
