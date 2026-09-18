"""Shared admission lookup over curriculum entries' ``admitted_by`` tags.

See docs/adr/0020-dependent-parameter-rules-ship-as-data-in-the-schema-payload.md:
answer which parent values admit a loaded curriculum entry; reads the
admitting-parent data attached at load.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def admitted_parents(entry: Mapping[str, Any], parent: str) -> list[str] | None:
    """The parent values whose tag admits *entry*.

    None when *parent* does not govern the row (no such key under
    ``entry["admitted_by"]``). A tag that is present but not a list returns
    ``[]`` (never admitted).
    """
    admitted_by = entry.get("admitted_by")
    if not isinstance(admitted_by, Mapping) or parent not in admitted_by:
        return None
    tag = admitted_by[parent]
    if not isinstance(tag, list):
        return []
    return tag


def admits(entry: Mapping[str, Any], parent: str, value: str) -> bool:
    """True when *entry* is admitted by *value* under *parent*.

    True when admitted_parents(...) is None (row unscoped by that parent) or
    contains value.
    """
    parents = admitted_parents(entry, parent)
    return parents is None or value in parents


def entries_admitted_by(
    entries: Iterable[Mapping[str, Any]], parent: str, value: str
) -> list[dict]:
    """Entries admitted by *value* under *parent*, preserving order and identity."""
    return [e for e in entries if admits(e, parent, value)]


def admitted_parents_by_code(
    data: Mapping[str, Any], key: str, parent: str
) -> dict[str, list[str]]:
    """Union of *parent* tag values admitting each code under ``data[key]``.

    Skips rows that are not dicts or whose ``"value"`` is not a str; skips
    rows whose *parent* tag is not a list. Unions the str members per code,
    preserving first-seen order without duplicates. Codes with no tagged row
    are absent.
    """
    by_code: dict[str, list[str]] = {}
    for entry in data.get(key, []):
        if not isinstance(entry, dict) or not isinstance(entry.get("value"), str):
            continue
        tag = entry.get("admitted_by", {}).get(parent)
        if not isinstance(tag, list):
            continue
        existing = by_code.setdefault(entry["value"], [])
        for member in tag:
            if isinstance(member, str) and member not in existing:
                existing.append(member)
    return by_code
