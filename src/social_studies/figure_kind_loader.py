"""Load the advisory vocabulary and aliases for social-studies 圖像種類."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "social_studies" / "figure_kinds.json"


def _load_document(source: Path) -> object | None:
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load figure-kind vocabulary from %s: %s", source, exc)
        return None


def _canonical_labels(raw: object, source: Path) -> tuple[str, ...]:
    if isinstance(raw, list):
        labels = raw
    elif isinstance(raw, dict):
        labels = raw.get("canonical")
    else:
        labels = None

    if not isinstance(labels, list):
        logger.warning(
            "Figure-kind vocabulary at %s must contain a canonical JSON list",
            source,
        )
        return ()

    return tuple(
        label.strip()
        for label in labels
        if isinstance(label, str) and label.strip()
    )


def load_figure_kinds(path: Path | None = None) -> tuple[str, ...]:
    """Load canonical figure-kind labels without making them a schema enum."""
    source = path or _DATA_PATH
    raw = _load_document(source)
    return _canonical_labels(raw, source) if raw is not None else ()


def load_figure_kind_aliases(path: Path | None = None) -> dict[str, str]:
    """Load normalized alias spellings mapped to their canonical figure kind."""
    source = path or _DATA_PATH
    raw = _load_document(source)
    if not isinstance(raw, dict):
        return {}

    canonical = _canonical_labels(raw, source)
    canonical_by_key = {label.casefold(): label for label in canonical}
    aliases_by_canonical = raw.get("aliases", {})
    if not isinstance(aliases_by_canonical, dict):
        logger.warning("Figure-kind aliases at %s must be a JSON object", source)
        return {}

    aliases: dict[str, str] = {}
    for raw_canonical, raw_aliases in aliases_by_canonical.items():
        if not isinstance(raw_canonical, str):
            continue
        canonical_label = canonical_by_key.get(raw_canonical.strip().casefold())
        if canonical_label is None:
            logger.warning(
                "Ignoring figure-kind aliases for unknown canonical label %r in %s",
                raw_canonical,
                source,
            )
            continue
        if not isinstance(raw_aliases, list):
            logger.warning(
                "Figure-kind aliases for %s in %s must be a JSON list",
                raw_canonical,
                source,
            )
            continue

        for raw_alias in raw_aliases:
            if not isinstance(raw_alias, str) or not raw_alias.strip():
                continue
            alias = raw_alias.strip().casefold()
            if alias == canonical_label.casefold():
                continue
            previous = aliases.get(alias)
            if previous is not None and previous != canonical_label:
                logger.warning(
                    "Ignoring ambiguous figure-kind alias %r in %s",
                    raw_alias,
                    source,
                )
                continue
            aliases[alias] = canonical_label
    return aliases


CANONICAL_FIGURE_KINDS: tuple[str, ...] = load_figure_kinds()
FIGURE_KIND_ALIASES: dict[str, str] = load_figure_kind_aliases()
