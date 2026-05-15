"""Random parameter selection for social studies (PISA reading) question generation."""

from __future__ import annotations

import random

from src.social_studies.schema_loader import load_grades, load_schemas
from src.social_studies.schemas import (
    QuestionContext,
    QuestionSetType,
    QuestionStyle,
    QuestionType,
    ReadingProcess,
    SampledParams,
    TextForm,
)

_GRADES: list[int] = load_grades(load_schemas())


def sample_params(
    grade: int | None = None,
    style: list[QuestionStyle] | None = None,
    context: list[QuestionContext] | None = None,
    set_type: QuestionSetType | None = None,
    q_type: list[QuestionType] | None = None,
    seed: int | None = None,
) -> SampledParams:
    """Sample random PISA-reading question parameters.

    No grade_content needed — reading literacy has no K-12 curriculum code lookup.
    Sampler cardinality: 情境 1+, 文本形式 1, 閱讀歷程 1-2; 題型種類 forced 題組題.
    """
    rng = random.Random(seed)

    selected_grade = grade if grade is not None else rng.choice(_GRADES)

    all_contexts = list(QuestionContext)
    if context is not None:
        selected_context = context
    else:
        context_count = rng.randint(1, len(all_contexts))
        selected_context = rng.sample(all_contexts, context_count)

    # 題型種類 is always 題組題 in PISA; schema has only one value so this is deterministic.
    selected_set_type = set_type if set_type is not None else rng.choice(list(QuestionSetType))

    selected_q_type = rng.choice(q_type) if q_type is not None else rng.choice(list(QuestionType))

    # 閱讀歷程: pick 1-2
    all_processes = list(ReadingProcess)
    process_count = rng.randint(1, min(2, len(all_processes)))
    selected_process = rng.sample(all_processes, process_count)

    # 文本形式: pick 1; for mixed_text style pick 1-2, but keep as single TextForm field
    selected_text_form = rng.choice(list(TextForm))

    selected_style = rng.choice(style) if style is not None else rng.choice(list(QuestionStyle))

    return SampledParams(
        grade=selected_grade,
        情境=selected_context,
        題型種類=selected_set_type,
        題型=selected_q_type,
        閱讀歷程=selected_process,
        文本形式=selected_text_form,
        style=selected_style,
    )
