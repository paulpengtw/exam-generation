"""Load ICCS cognitive-process exemplars used by Channel 2 prompts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROCESS_BUCKETS: tuple[str, ...] = (
    "Knowing–Defining and Describing",
    "Knowing–Illustrating with examples",
    "Reasoning and Applying–Interpret information",
    "Reasoning and Applying–Relate or Integrate",
)

_DEFAULT_DIR = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "social_studies"
    / "few_shot"
    / "process_exemplars"
)


def _json_paths(source: Path) -> list[Path]:
    try:
        if source.is_file() and source.suffix == ".json":
            return [source]
        if not source.is_dir():
            return []
        return sorted(source.rglob("*.json"))
    except (AttributeError, OSError, RuntimeError, TypeError):
        return []


def _append_entries(
    result: dict[str, list[dict[str, Any]]],
    bucket: object,
    entries: object,
) -> None:
    if not isinstance(bucket, str) or bucket not in result:
        return
    if not isinstance(entries, list):
        return
    result[bucket].extend(
        entry for entry in entries if isinstance(entry, dict) and _is_valid_entry(entry)
    )


def _is_valid_entry(entry: dict[str, Any]) -> bool:
    """Keep only prompt-ready exemplars with the required compact fields."""
    text_fields = ("題幹", "答案", "rationale")
    if any(
        not isinstance(entry.get(field), str) or not entry[field].strip()
        for field in text_fields
    ):
        return False
    options = entry.get("選項")
    return isinstance(options, (dict, list, str)) and bool(options)


def _load_json_file(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _merge_file(result: dict[str, list[dict[str, Any]]], loaded: object) -> None:
    if isinstance(loaded, dict):
        bucket = loaded.get("bucket")
        if bucket is not None:
            _append_entries(result, bucket, loaded.get("exemplars"))
            return
        for key, entries in loaded.items():
            _append_entries(result, key, entries)
        return

    if isinstance(loaded, list):
        for entry in loaded:
            if not isinstance(entry, dict):
                continue
            _append_entries(result, entry.get("bucket"), entry.get("exemplars"))


def load_process_exemplars(
    exemplar_dir: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return process-bucketed exemplars; missing or unknown data is harmless."""
    result = {bucket: [] for bucket in PROCESS_BUCKETS}
    source = exemplar_dir if exemplar_dir is not None else _DEFAULT_DIR
    for path in _json_paths(source):
        _merge_file(result, _load_json_file(path))
    return result
