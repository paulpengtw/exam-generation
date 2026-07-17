"""Classify historical chart_spec entries by shape.

Scans a directory of generated question JSON files (both math flat structure and
社會領域/自然科學 題組 with subquestions[*].chart_spec) and emits a Markdown
summary of how many specs fall into each category. Used by Task 6 of the
figure-rendering plan to record measured coverage of the frontend TS prototype.

Run:
    uv run python scripts/analyze_chart_spec_coverage.py output/
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

SCENARIO_KEYWORDS = ("情境卡",)


def classify_spec(spec: dict) -> str:
    """Return the coverage category for a single chart_spec dict."""
    render_mode = (spec.get("render_mode") or "").lower()
    if render_mode == "chart":
        return "chart"

    data = spec.get("data") or {}
    if isinstance(data, dict):
        if "rows" in data or "columns" in data:
            return "table"
        if "shapes" in data:
            return "geometry"

    description = spec.get("description") or ""
    if any(k in description for k in SCENARIO_KEYWORDS):
        return "scenario_card"

    return "other"


def iter_specs(root: Path) -> Iterable[dict]:
    """Yield every non-null chart_spec found under root (top-level + subquestions)."""
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payloads = payload if isinstance(payload, list) else [payload]
        for item in payloads:
            if not isinstance(item, dict):
                continue
            top = item.get("chart_spec")
            if isinstance(top, dict):
                yield top
            for sq in item.get("subquestions") or []:
                if not isinstance(sq, dict):
                    continue
                sub = sq.get("chart_spec")
                if isinstance(sub, dict):
                    yield sub


def summarize(specs: list[dict]) -> str:
    """Render a Markdown table (category | count | percentage) for the given specs."""
    counts = Counter(classify_spec(s) for s in specs)
    total = sum(counts.values()) or 1
    order = ["chart", "table", "geometry", "scenario_card", "other"]
    lines = ["| category | count | percentage |", "| --- | --- | --- |"]
    for cat in order:
        if cat not in counts:
            continue
        n = counts[cat]
        pct = 100.0 * n / total
        lines.append(f"| {cat} | {n} | {pct:.1f}% |")
    lines.append(f"\nTotal chart_spec entries analyzed: **{sum(counts.values())}**")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify chart_spec entries by shape.")
    parser.add_argument(
        "root", type=Path, help="Directory containing generated question JSON files."
    )
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    specs = list(iter_specs(args.root))
    print(summarize(specs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
