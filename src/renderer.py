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


def render_chart(chart_spec: dict, output_path: str | Path, llm_client=None) -> str | None:
    """Render a chart from a chart_spec dict and save as PNG.

    Returns the output path on success, or None if chart_type is unknown.
    llm_client: optional LLMClient for LLM-assisted geometry rendering.
    """
    output_path = Path(output_path)
    chart_type = chart_spec.get("chart_type", "")

    if chart_type == "geometry":
        _render_geometry(chart_spec, output_path, llm_client)
        return str(output_path)

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


def _render_geometry(spec: dict, output_path: Path, llm_client=None) -> None:
    """Render a geometry diagram. Tries hardcoded patterns first, then LLM fallback."""
    title = spec.get("title", "")
    description = spec.get("description", "")
    data = spec.get("data", {})

    # Try hardcoded patterns
    if "rectangle" in data and "triangle" in data:
        _render_geometry_courtyard(spec, output_path)
        return
    if "lamp_height" in data:
        _render_geometry_shadow(spec, output_path)
        return

    # Fallback: LLM-assisted rendering
    if llm_client is not None:
        success = _render_geometry_via_llm(spec, output_path, llm_client)
        if success:
            return

    # Final fallback: render description as text (should not normally reach here)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.text(0.5, 0.5, description or title, transform=ax.transAxes,
            ha="center", va="center", fontsize=14, wrap=True)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.axis("off")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _render_geometry_courtyard(spec: dict, output_path: Path) -> None:
    """Render courtyard-style diagram: rectangle + triangle + optional circle."""
    data = spec.get("data", {})
    title = spec.get("title", "")
    rect = data["rectangle"]
    tri = data["triangle"]

    fig, ax = plt.subplots(figsize=(8, 6))

    rect_patch = patches.Rectangle(
        (0, 0), rect["width"], rect["height"],
        linewidth=2, edgecolor="black", facecolor="lightyellow", linestyle="--"
    )
    ax.add_patch(rect_patch)

    if "A" in tri and "B" in tri and "C" in tri:
        triangle = plt.Polygon(
            [tri["A"], tri["B"], tri["C"]],
            fill=False, edgecolor="blue", linewidth=2
        )
        ax.add_patch(triangle)
        for label, coord in [("A", tri["A"]), ("B", tri["B"]), ("C", tri["C"])]:
            ax.annotate(label, coord, fontsize=14, fontweight="bold", color="blue",
                        textcoords="offset points", xytext=(5, 5))

    if "circle" in data:
        circle_data = data["circle"]
        if circle_data.get("center") == "inside_triangle" and "A" in tri and "B" in tri and "C" in tri:
            cx = (tri["A"][0] + tri["B"][0] + tri["C"][0]) / 3
            cy = (tri["A"][1] + tri["B"][1] + tri["C"][1]) / 3
            circle = plt.Circle((cx, cy), 2, fill=True, facecolor="lightgreen",
                                edgecolor="green", linewidth=2, alpha=0.5)
            ax.add_patch(circle)
            ax.annotate("r", (cx + 1, cy), fontsize=12, color="green")

    ax.set_xlim(-3, rect["width"] + 3)
    ax.set_ylim(-3, rect["height"] + 3)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.axis("off")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _render_geometry_shadow(spec: dict, output_path: Path) -> None:
    """Render lamp/shadow diagram."""
    data = spec.get("data", {})
    title = spec.get("title", "")
    lamp_h = data["lamp_height"]
    person_h = data["person_height"]
    dist = data["distance"]
    shadow_len = (person_h * dist) / (lamp_h - person_h)

    fig, ax = plt.subplots(figsize=(8, 6))

    ax.plot([-1, dist + shadow_len + 1], [0, 0], "k-", linewidth=2)
    ax.plot([0, 0], [0, lamp_h], "k-", linewidth=3)
    ax.plot(0, lamp_h, "yo", markersize=15)
    ax.annotate(f"路燈\n{lamp_h}m", (0, lamp_h), textcoords="offset points", xytext=(-30, 10), fontsize=10)
    ax.plot([dist, dist], [0, person_h], "b-", linewidth=3)
    ax.annotate(f"人\n{person_h}m", (dist, person_h), textcoords="offset points", xytext=(10, 5), fontsize=10)
    ax.plot([0, dist + shadow_len], [lamp_h, 0], "r--", linewidth=1, alpha=0.6)
    ax.plot([dist, dist + shadow_len], [0, 0], color="gray", linewidth=6, alpha=0.4)
    ax.annotate("影子", (dist + shadow_len / 2, -0.3), ha="center", fontsize=10, color="gray")
    ax.annotate("", xy=(dist, -0.5), xytext=(0, -0.5), arrowprops=dict(arrowstyle="<->", color="red"))
    ax.text(dist / 2, -0.8, f"{dist}m", ha="center", fontsize=10, color="red")

    ax.set_xlim(-2, dist + shadow_len + 2)
    ax.set_ylim(-1.5, lamp_h + 1.5)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.axis("off")
    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


_GEOMETRY_CODE_PROMPT = """\
You are a matplotlib code generator. Given a geometry diagram description, output ONLY a Python code block that draws the diagram using matplotlib.

Rules:
- The code will be exec()'d with these variables already in scope: `fig`, `ax`, `plt`, `np`, `patches`, `Path` (matplotlib.path.Path), `FONT_PROP` (a FontProperties object for CJK text)
- fig and ax are already created (fig, ax = plt.subplots(figsize=(8, 6)))
- Do NOT call plt.show(), fig.savefig(), or plt.close() — that's handled externally
- Use ax.set_aspect("equal") and ax.axis("off")
- Set ax.set_title() with the provided title
- Use clear labels, annotations, and dimension markers
- IMPORTANT: For ALL text that contains Chinese characters, pass `fontproperties=FONT_PROP` to ax.text(), ax.annotate(), ax.set_title(), etc. For pure ASCII text (numbers, "x+4"), fontproperties is optional.
- Keep the code simple and self-contained
- Output ONLY the code block, nothing else

Diagram to render:
Title: {title}
Description: {description}
Data: {data}
"""


def _render_geometry_via_llm(spec: dict, output_path: Path, llm_client) -> bool:
    """Use LLM to generate matplotlib code for arbitrary geometry diagrams.

    Returns True if rendering succeeded, False otherwise.
    """
    import json
    import re
    import sys

    title = spec.get("title", "")
    description = spec.get("description", "")
    data = spec.get("data", {})

    prompt = _GEOMETRY_CODE_PROMPT.format(
        title=title,
        description=description,
        data=json.dumps(data, ensure_ascii=False, indent=2),
    )

    try:
        print("  Generating geometry diagram via LLM...", file=sys.stderr)
        raw = llm_client.generate(
            "You are a matplotlib code generator. Output only Python code.",
            prompt,
        )

        # Extract code from response
        code_match = re.search(r"```(?:python)?\s*\n(.*?)\n```", raw, re.DOTALL)
        if code_match:
            code = code_match.group(1)
        else:
            code = raw.strip()

        # Execute in sandboxed namespace
        fig, ax = plt.subplots(figsize=(8, 6))
        from matplotlib.path import Path as MplPath
        from matplotlib.font_manager import FontProperties
        # Build a FontProperties object for CJK text using the configured font
        cjk_font_name = plt.rcParams["font.sans-serif"][0] if plt.rcParams["font.sans-serif"] else "sans-serif"
        font_prop = FontProperties(family=cjk_font_name, size=12)
        namespace = {
            "fig": fig,
            "ax": ax,
            "plt": plt,
            "np": np,
            "patches": patches,
            "Path": MplPath,
            "FONT_PROP": font_prop,
        }
        exec(code, namespace)

        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return True

    except Exception as e:
        print(f"  Warning: LLM geometry rendering failed: {e}", file=sys.stderr)
        plt.close("all")  # Clean up any open figures
        return False
