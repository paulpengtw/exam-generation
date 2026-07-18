"""Build the side-by-side fidelity manifest (issue #110 gate evidence, Part A).

Picks illustrative chart_specs (render_mode != "chart") out of generation_records,
renders each through the current server path (LLM-HTML + Playwright, see
docs/figure-rendering-policy.md) and writes fidelity/manifest.json. Load that
file on the web app's /fidelity-compare page (frontend built with
VITE_ENABLE_FRONTEND_TS_RENDERER=1) to rate server PNG vs frontend TS renders.

Run (needs LLM_API_KEY and a Playwright chromium: `uv run playwright install chromium`):
    DATABASE_URL=<url> uv run python scripts/build_fidelity_manifest.py --limit 12
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_chart_spec_coverage import classify_spec  # noqa: E402
from scripts.census_chart_specs import default_database_url, load_records  # noqa: E402


def _question_text(item: dict) -> str:
    """Context passed to the HTML generator: 文本 (題組) or joined 題目 (math)."""
    text = item.get("文本")
    if isinstance(text, str) and text:
        return text
    body = item.get("題目")
    if isinstance(body, list):
        return "\n".join(str(part) for part in body)
    return ""


def select_illustrative_specs(
    rows: list[tuple[str, dict]], limit_per_subject: int = 12
) -> list[dict]:
    """Pick up to limit_per_subject illustrative specs (render_mode != "chart") per subject."""
    picked: list[dict] = []
    counts: Counter = Counter()
    for subject, item in rows:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id") or "unknown")
        candidates: list[tuple[str, object]] = [(qid, item.get("chart_spec"))]
        for sq in item.get("subquestions") or []:
            if isinstance(sq, dict):
                candidates.append((f"{qid}_sq{sq.get('序號', '?')}", sq.get("chart_spec")))
        for spec_id, spec in candidates:
            if not isinstance(spec, dict):
                continue
            if (spec.get("render_mode") or "").lower() == "chart":
                continue
            if counts[subject] >= limit_per_subject:
                continue
            counts[subject] += 1
            picked.append(
                {
                    "id": spec_id,
                    "subject": subject,
                    "category": classify_spec(spec),
                    "spec": spec,
                    "question_text": _question_text(item)[:300],
                }
            )
    return picked


def build_manifest(
    entries: list[dict], render_png: Callable[[dict, str], bytes | None]
) -> list[dict]:
    """Attach server_png_base64 to every entry via the injected renderer."""
    manifest: list[dict] = []
    for entry in entries:
        png = render_png(entry["spec"], entry["question_text"])
        encoded = base64.b64encode(png).decode("ascii") if png else None
        manifest.append({**entry, "server_png_base64": encoded})
    return manifest


def _server_renderer(html_renderer, llm_client) -> Callable[[dict, str], bytes | None]:
    """Real renderer: the exact server path (LLM-HTML + Playwright screenshot)."""
    from src.renderer import render_image

    def render_png(spec: dict, question_text: str) -> bytes | None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fig.png"
            rendered = render_image(
                spec,
                out,
                question_text=question_text,
                html_renderer=html_renderer,
                llm_client=llm_client,
                image_generation_mode="html",
            )
            if rendered is None:
                return None
            return Path(rendered).read_bytes()

    return render_png


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render illustrative chart_specs server-side into fidelity/manifest.json."
    )
    parser.add_argument("--database-url", default=default_database_url())
    parser.add_argument(
        "--limit", type=int, default=12, help="max illustrative specs per subject"
    )
    parser.add_argument("--output", type=Path, default=Path("fidelity/manifest.json"))
    args = parser.parse_args(argv)

    from src.config import Config
    from src.html_renderer import PlaywrightRenderer
    from src.llm_client import LLMClient

    config = Config.from_env()
    if not config.api_key:
        print("error: LLM_API_KEY is required (HTML generation uses the LLM)", file=sys.stderr)
        return 2

    rows = asyncio.run(load_records(args.database_url))
    entries = select_illustrative_specs(rows, limit_per_subject=args.limit)
    if not entries:
        print("no illustrative chart_spec entries found — generate questions first",
              file=sys.stderr)
        return 1

    client = LLMClient(config)
    with PlaywrightRenderer() as renderer:
        manifest = build_manifest(entries, _server_renderer(renderer, client))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for m in manifest if m["server_png_base64"])
    print(f"wrote {len(manifest)} entries ({ok} with server PNG) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
