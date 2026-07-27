"""CurriculumContext — value object carrying the three curriculum text fields.

Performs NO file I/O at import time.  All loading is deferred to the explicit
factory :func:`load_curriculum_context`, which must be called once per run and
the resulting object threaded into every prompt-building call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.common.curriculum_loader import (
    load_learning_content,
    load_learning_performance,
    load_performance_intro,
)

_DEFAULT_MATH_CURRICULUM_DIR = (
    Path(__file__).parent.parent / "data" / "math" / "curriculum"
)

_CURRICULUM_EMPTY_NOTICE = (
    "（課程綱要資料待研究人員補充至 data/math/curriculum/）"
)


@dataclass(frozen=True)
class CurriculumContext:
    """Immutable snapshot of the three curriculum text fields used in prompts."""

    content_text: str
    performance_text: str
    intro_text: str


def load_curriculum_context(data_dir: Path | None = None) -> CurriculumContext:
    """Load a :class:`CurriculumContext` from a curriculum directory.

    Args:
        data_dir: Directory containing ``learning_content.json``,
                  ``learning_performance.json``, and optionally
                  ``learning_performance_intro.md``.
                  Defaults to ``data/math/curriculum/``.
    """
    if data_dir is None:
        data_dir = _DEFAULT_MATH_CURRICULUM_DIR

    content_data = load_learning_content(data_dir)
    performance_data = load_learning_performance(data_dir)
    intro_text = load_performance_intro(data_dir)

    performance_text: str = (
        json.dumps(performance_data, ensure_ascii=False, indent=2)
        if performance_data.get("學習表現")
        else ""
    )
    content_text: str = (
        json.dumps(content_data, ensure_ascii=False, indent=2)
        if content_data.get("學習內容")
        else ""
    )

    return CurriculumContext(
        content_text=content_text,
        performance_text=performance_text,
        intro_text=intro_text,
    )


def build_curriculum_section(ctx: CurriculumContext) -> str:
    """Return the ``## 課程綱要參考`` body string for *ctx*.

    The result is empty-notice when both text fields are absent; otherwise it
    concatenates the intro, performance, and content subsections.
    """
    if not ctx.content_text and not ctx.performance_text:
        return _CURRICULUM_EMPTY_NOTICE
    parts = []
    if ctx.intro_text:
        parts.append("### 學習表現架構說明\n\n" + ctx.intro_text)
    if ctx.performance_text:
        parts.append("### 學習表現標準\n\n" + ctx.performance_text)
    if ctx.content_text:
        parts.append("### 學習內容\n\n" + ctx.content_text)
    return "\n\n".join(parts)
