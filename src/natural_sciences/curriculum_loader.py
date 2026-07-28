"""Subject-specific shim over src.common.curriculum_loader for 自然科學領域.

Differences from the SS shim
-----------------------------
* ``subject_to_prefixes`` is empty — NS has no subject bucketing at the sampler
  level.  The common ``_subject_prefixes()`` helper therefore falls back to
  ``{subject}`` for an explicit subject (exact 科目 match) and returns ``None``
  (no filter) when ``subject=None``.  All current NS call sites pass no subject,
  so the behaviour is byte-identical to the old ``del subject`` approach; the
  argument simply stops being silently discarded (AC2).
* NS-only helpers (``grade_to_learning_stage``, ``relevant_cross_concepts``,
  ``_paren_code``) have no SS counterpart and remain here.
* Per-file env-var overrides for LC/LP are preserved (NS has three that SS
  also carries; see ``SubjectLoaderSpec`` for the full list).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path

from src.common import curriculum_loader as _base
from src.common.subject_spec import NATURAL_SCIENCES as _SPEC

_DATA_DIR = _SPEC.data_dir


def grade_to_learning_stage(grade: int) -> str:
    """Map a grade (3-12) to its 自然科學 學習階段.

    Mirrors ``src.sampler.grade_to_learning_stage`` (math), but 自然科學 has
    no 第一學習階段 — the subject starts at grade 3 (學習階段_to_grades in the
    curriculum JSON covers stages 二/三/四/五 only).
    """
    if 3 <= grade <= 4:
        return "第二學習階段"
    if 5 <= grade <= 6:
        return "第三學習階段"
    if 7 <= grade <= 9:
        return "第四學習階段"
    if 10 <= grade <= 12:
        return "第五學習階段"
    raise ValueError(f"grade {grade} has no 自然科學 學習階段 (must be 3-12)")


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_learning_content(path: Path | None = None) -> dict:
    if path is not None:
        return _load_json(path)
    env = os.environ.get(_SPEC.lc_path_env or "")
    if env:
        return _load_json(Path(env))
    return _base.load_learning_content(_DATA_DIR)


def load_learning_performance(path: Path | None = None) -> dict:
    if path is not None:
        return _load_json(path)
    env = os.environ.get(_SPEC.lp_path_env or "")
    if env:
        return _load_json(Path(env))
    return _base.load_learning_performance(_DATA_DIR)


def load_performance_intro(path: Path | None = None) -> str:
    if path is not None:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")
    env = os.environ.get(_SPEC.lp_intro_path_env or "")
    if env:
        p = Path(env)
        return p.read_text(encoding="utf-8") if p.exists() else ""
    return _base.load_performance_intro(_DATA_DIR)


def allowed_learning_content(
    data: dict,
    learning_stage: str,
    subject: str | None = None,
) -> list[dict]:
    """Return 學習內容 entries for *learning_stage*, optionally filtered by 科目.

    When *subject* is ``None`` (all current NS call sites) the full stage pool
    is returned — behaviour unchanged from the old ``del subject`` approach.
    When *subject* is given, the common implementation filters to entries whose
    ``科目`` field is in the fallback set ``{subject}`` (since
    ``subject_to_prefixes`` is empty for NS).
    """
    return _base.allowed_learning_content(
        data,
        learning_stage,
        subject=subject,
        subject_to_prefixes=_SPEC.subject_to_prefixes,
    )


def allowed_learning_performance(
    data: dict,
    learning_stage: str,
    subject: str | None = None,
) -> list[dict]:
    """Return 學習表現 entries for *learning_stage*, optionally filtered by 科目.

    Same subject-handling contract as ``allowed_learning_content``.
    """
    return _base.allowed_learning_performance(
        data,
        learning_stage,
        subject=subject,
        subject_to_prefixes=_SPEC.subject_to_prefixes,
    )


_PAREN_CODE_RE = re.compile(r"（\s*([A-Za-z]+)\s*）")


def _paren_code(text: str) -> str:
    """Extract the Latin code in full-width parens: '物質與能量（INa）' → 'INa'."""
    m = _PAREN_CODE_RE.search(text or "")
    return m.group(1) if m else ""


def relevant_cross_concepts(rows: list[dict], lc_codes: Sequence[str]) -> list[dict]:
    """Narrow the 跨科概念 taxonomy to concepts related to 學習內容 codes.

    A 學習內容 code's prefix (the part before the first ``-``) locates it in
    the taxonomy:

    - 國小 codes (``INa-II-1``) carry a 跨科概念 code directly (INa–INg);
    - 國中 codes (``Ab-Ⅳ-1``) carry a 次主題 code (Aa–Nc);
    - 高中 codes (``BDa-Ⅴa-1``) prepend a 科目 letter (B/C/P/E) to the 次主題.

    Every matched 次主題 pulls in its whole parent 跨科概念 group so the
    model keeps local taxonomy context. Safe fallback (issue #91): an empty
    ``lc_codes``, or prefixes that match nothing, return ``rows`` unchanged.
    """
    prefixes = {code.split("-", 1)[0] for code in lc_codes if code and "-" in code}
    if not prefixes:
        return rows

    concept_codes: set[str] = set()
    concept_by_sub: dict[str, str] = {}
    for row in rows:
        concept = _paren_code(row.get("跨科概念", ""))
        sub = _paren_code(row.get("次主題", ""))
        if concept:
            concept_codes.add(concept)
        if concept and sub:
            concept_by_sub[sub] = concept

    wanted: set[str] = set()
    for prefix in prefixes:
        if prefix in concept_codes:
            wanted.add(prefix)
        elif prefix in concept_by_sub:
            wanted.add(concept_by_sub[prefix])
        elif len(prefix) == 3 and prefix[1:] in concept_by_sub:
            # 高中 code: strip the leading 科目 letter (B/C/P/E).
            wanted.add(concept_by_sub[prefix[1:]])

    if not wanted:
        return rows
    filtered = [row for row in rows if _paren_code(row.get("跨科概念", "")) in wanted]
    return filtered or rows


content_instructions = _base.content_instructions
performance_instructions = _base.performance_instructions
