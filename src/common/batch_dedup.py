"""Batch-level scope dedup helper for issue #111.

Each subject's batch loop accumulates a list of `PriorScope` — a small summary
of already-accepted siblings — and passes it to the next question's user prompt
so the LLM can vary angle/題材 even when learning-content codes overlap.

Prompt-level only. Embedding-similarity retry is a separate future issue.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover — import guard for type hints only
    from src.natural_sciences.schemas import ExamQuestion as NSExamQuestion
    from src.schemas import ExamQuestion as MathExamQuestion
    from src.social_studies.schemas import ExamQuestion as SSExamQuestion

logger = logging.getLogger(__name__)

_PRIOR_SCOPES_CAP: int = 10


class PriorScope(BaseModel):
    """A one-line summary of an already-accepted batch sibling."""

    summary: str = ""
    codes: list[str] = Field(default_factory=list)


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def extract_math_prior_scope(question: "MathExamQuestion") -> PriorScope | None:
    """Extract a PriorScope from a completed math ExamQuestion."""
    try:
        summary = (getattr(question, "出題概念", "") or "").strip()
        raw_codes = [
            (item.編碼 or "").strip()
            for item in getattr(question, "學習內容", []) or []
        ]
        codes = _dedup_preserve_order(raw_codes)
    except Exception as exc:
        logger.debug("skipping prior scope for math question: %s", exc)
        return None
    if not summary and not codes:
        logger.debug("skipping prior scope for math question: both summary and codes empty")
        return None
    return PriorScope(summary=summary, codes=codes)


def extract_ss_prior_scope(question: "SSExamQuestion") -> PriorScope | None:
    """Extract a PriorScope from a completed social-studies ExamQuestion."""
    try:
        summary = (getattr(question, "核心問題", "") or "").strip()
        raw_codes: list[str] = []
        for sub in getattr(question, "subquestions", []) or []:
            for ref in getattr(sub, "學習內容", []) or []:
                raw_codes.append((ref.編碼 or "").strip())
        codes = _dedup_preserve_order(raw_codes)
    except Exception as exc:
        logger.debug("skipping prior scope for social-studies question: %s", exc)
        return None
    if not summary and not codes:
        logger.debug(
            "skipping prior scope for social-studies question: both summary and codes empty"
        )
        return None
    return PriorScope(summary=summary, codes=codes)


def extract_ns_prior_scope(question: "NSExamQuestion") -> PriorScope | None:
    """Extract a PriorScope from a completed natural-sciences ExamQuestion."""
    try:
        summary = (getattr(question, "核心問題", "") or "").strip()
        raw_codes: list[str] = []
        for sub in getattr(question, "subquestions", []) or []:
            for ref in getattr(sub, "學習內容", []) or []:
                raw_codes.append((ref.編碼 or "").strip())
        codes = _dedup_preserve_order(raw_codes)
    except Exception as exc:
        logger.debug("skipping prior scope for natural-sciences question: %s", exc)
        return None
    if not summary and not codes:
        logger.debug(
            "skipping prior scope for natural-sciences question: both summary and codes empty"
        )
        return None
    return PriorScope(summary=summary, codes=codes)


def format_prior_scopes_block(scopes: Sequence[PriorScope]) -> str:
    """Render the `## 已生成題目（請避免相似範圍）` block for the user prompt.

    Returns an empty string when the input list is empty — the count=1
    regression guarantee. Only the most recent `_PRIOR_SCOPES_CAP` entries
    appear in the rendered block.
    """
    if not scopes:
        return ""
    recent = list(scopes)[-_PRIOR_SCOPES_CAP:]
    lines = ["## 已生成題目（請避免相似範圍）", ""]
    for i, scope in enumerate(recent, start=1):
        codes_str = ", ".join(scope.codes) if scope.codes else "（無）"
        lines.append(f"{i}. 核心問題：{scope.summary}；學習內容：{codes_str}")
    return "\n".join(lines) + "\n"
