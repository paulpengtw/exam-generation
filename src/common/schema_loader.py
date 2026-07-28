"""Subject-agnostic schema loader for CSV-based question parameter schemas.

Both social-studies and natural-sciences schema loaders delegate to this
module, parameterised by their subject-specific directory, env-var name, and
category tuple.

Malformed rows (empty or missing ``value`` field) are skipped with a
``logging.WARNING`` — they are never included in the returned dict.
"""

from __future__ import annotations

import csv
import logging
import os
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_dir(path: Path | None, env_var: str, default_dir: Path) -> Path:
    if path is not None:
        return path
    env_path = os.environ.get(env_var)
    return Path(env_path) if env_path else default_dir


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_schemas(
    categories: tuple[str, ...],
    env_var: str,
    default_dir: Path,
    curriculum_dir: Path | None = None,
) -> dict:
    """Load schema from schema_meta.csv and schema_parameters.csv.

    Parameters
    ----------
    categories:
        Ordered tuple of category names to collect (e.g. ``("情境", "題型")``).
    env_var:
        Env-var name whose value overrides the curriculum directory.
    default_dir:
        Default curriculum directory when neither *curriculum_dir* nor the
        env-var is set.
    curriculum_dir:
        Explicit directory override; takes precedence over the env-var.

    Returns
    -------
    dict with keys ``"學習階段"``, ``"grades"``, and one key per category.

    Notes
    -----
    * Rows whose ``value`` cell is empty or whose CSV header lacks a ``value``
      column are **skipped** with a :py:data:`logging.WARNING` — they are never
      included in the returned category lists.
    * An optional ``parent`` column is captured for categories that use it
      (e.g. NS ``情境子類別``); it is ignored for categories that don't.
    """
    d = _resolve_dir(curriculum_dir, env_var, default_dir)
    csv_path = d / "schema_parameters.csv"

    meta_rows = _read_csv(d / "schema_meta.csv")
    meta = {row["欄位"]: row["值"] for row in meta_rows}
    grades_raw = meta.get("grades", "")
    grades = [int(g.strip()) for g in grades_raw.split(";") if g.strip()]

    param_rows = _read_csv(csv_path)
    categories_dict: dict[str, list[dict[str, str]]] = {c: [] for c in categories}
    for row in param_rows:
        cat = row.get("類別", "")
        if cat not in categories_dict:
            continue
        # Use .get() so a missing "value" column yields "" rather than KeyError.
        value = row.get("value") or ""
        if not value:
            logger.warning(
                "Skipping malformed row in %s (empty or missing 'value'): %r",
                csv_path,
                dict(row),
            )
            continue
        entry: dict[str, str] = {
            "value": value,
            "instruction": row.get("instruction") or "",
        }
        parent = row.get("parent") or ""
        if parent:
            entry["parent"] = parent
        categories_dict[cat].append(entry)

    return {"學習階段": meta.get("學習階段", ""), "grades": grades, **categories_dict}


def extract_values(entries: list[dict]) -> list[str]:
    """Return the ``value`` strings, skipping any that are falsy."""
    return [entry["value"] for entry in entries if entry.get("value")]


def build_str_enum(name: str, values: list[str]) -> type:
    members = {f"ITEM_{i}": v for i, v in enumerate(values)}
    return Enum(name, members, type=str)  # type: ignore[return-value]


def load_grades(schemas: dict) -> list[int]:
    return schemas["grades"]


def load_learning_stage(schemas: dict) -> str:
    return schemas["學習階段"]


def build_instructions(schemas: dict, categories: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Return ``{category: {value: instruction}}`` for all non-empty instructions."""
    result: dict[str, dict[str, str]] = {}
    for category in categories:
        mapping: dict[str, str] = {}
        for entry in schemas.get(category, []):
            if entry.get("instruction"):
                mapping[entry["value"]] = entry["instruction"]
        result[category] = mapping
    return result
