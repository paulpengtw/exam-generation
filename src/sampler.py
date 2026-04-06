"""Random parameter selection for exam question generation."""

from __future__ import annotations

import random

from src.schema_loader import load_grades, load_schemas
from src.schemas import (
    LearningContentItem,
    MathThinking,
    QuestionContext,
    QuestionSetType,
    QuestionStyle,
    QuestionType,
    SampledParams,
)

_GRADES: list[int] = load_grades(load_schemas())


def sample_params(
    grade_content: dict[int, list[LearningContentItem]],
    grade: int | None = None,
    style: QuestionStyle | None = None,
    context: list[QuestionContext] | None = None,
    set_type: QuestionSetType | None = None,
    q_type: QuestionType | None = None,
    seed: int | None = None,
) -> SampledParams:
    """Sample random question parameters.

    All parameters can be overridden. If not provided, they are randomly selected.
    grade_content should be a dict mapping grade (7, 8, 9) to their LearningContentItem lists.
    """
    rng = random.Random(seed)

    # Grade
    selected_grade = grade if grade is not None else rng.choice(_GRADES)

    # 情境 (1 to N items)
    all_contexts = list(QuestionContext)
    if context is not None:
        selected_context = context
    else:
        context_count = rng.randint(1, len(all_contexts))
        selected_context = rng.sample(all_contexts, context_count)

    # 題型種類
    selected_set_type = set_type if set_type is not None else rng.choice(list(QuestionSetType))

    # 題型
    selected_q_type = q_type if q_type is not None else rng.choice(list(QuestionType))

    # 數學思考 (1-3 items)
    all_thinking = list(MathThinking)
    thinking_count = rng.randint(1, 3)
    selected_thinking = rng.sample(all_thinking, min(thinking_count, len(all_thinking)))

    # 學習內容 (1-3 items from the selected grade)
    available_content = grade_content.get(selected_grade, [])
    if not available_content:
        raise ValueError(f"No learning content available for grade {selected_grade}")
    content_count = rng.randint(1, min(3, len(available_content)))
    selected_content = rng.sample(available_content, content_count)

    # Question style
    selected_style = style if style is not None else rng.choice(list(QuestionStyle))

    return SampledParams(
        grade=selected_grade,
        情境=selected_context,  # now a list
        題型種類=selected_set_type,
        題型=selected_q_type,
        數學思考=selected_thinking,
        學習內容=selected_content,
        style=selected_style,
    )
