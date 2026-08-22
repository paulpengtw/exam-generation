"""Load the advisory canonical vocabulary for social-studies 圖像種類."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "social_studies" / "figure_kinds.json"


def load_figure_kinds(path: Path | None = None) -> tuple[str, ...]:
    """Load canonical figure-kind labels without making them a schema enum."""
    source = path or _DATA_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load figure-kind vocabulary from %s: %s", source, exc)
        return ()

    if not isinstance(raw, list):
        logger.warning("Figure-kind vocabulary at %s must be a JSON list", source)
        return ()

    return tuple(
        label.strip()
        for label in raw
        if isinstance(label, str) and label.strip()
    )


CANONICAL_FIGURE_KINDS: tuple[str, ...] = load_figure_kinds()

