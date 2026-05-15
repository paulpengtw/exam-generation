"""Data loading for social studies — no K-12 curriculum; just few-shot examples."""

from __future__ import annotations

import json
from pathlib import Path


def load_few_shot_examples(few_shot_dir: Path, style: str) -> list[dict]:
    """Load few-shot examples matching a given question style."""
    style_dir = few_shot_dir / style
    if not style_dir.exists():
        return []
    examples = []
    for f in sorted(style_dir.glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            examples.append(json.load(fh))
    return examples
