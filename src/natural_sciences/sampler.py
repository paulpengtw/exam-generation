"""Random parameter selection for PISA Science + 108課綱自然科學 generation."""

from __future__ import annotations

import random

from src.common.difficulty import Difficulty, resolve_difficulty
from src.natural_sciences.curriculum_loader import (
    allowed_learning_content,
    allowed_learning_performance,
    grade_to_learning_stage,
    load_learning_content,
    load_learning_performance,
)
from src.natural_sciences.schema_loader import load_grades, load_schemas
from src.natural_sciences.schemas import (
    QuestionContext,
    QuestionSetType,
    QuestionSubContext,
    QuestionType,
    SampledParams,
    ScienceCompetency,
)

_schemas = load_schemas()
_GRADES: list[int] = load_grades(_schemas)
_CONTENT_TYPE_VALUES: list[str] = [
    row["value"] for row in _schemas.get("題目內容類型", []) if row.get("value")
]
_RANDOM_CONTENT_TYPE_VALUES: list[str] = [
    v for v in _CONTENT_TYPE_VALUES if v != "customized"
]
_SUB_CONTEXT_PARENT: dict[str, str] = {
    row["value"]: row.get("parent", "")
    for row in _schemas.get("情境子類別", [])
    if row.get("value")
}

_LC_DATA: dict = load_learning_content()
_LP_DATA: dict = load_learning_performance()


def _matching_subcontexts(context_values: set[str]) -> list[QuestionSubContext]:
    return [
        sub_context for sub_context in QuestionSubContext
        if _SUB_CONTEXT_PARENT.get(sub_context.value) in context_values
    ]


def _content_from_performance(
    performance_codes: list[str],
    learning_stage: str,
) -> list[str]:
    content_by_value = {
        entry["value"]: entry
        for entry in allowed_learning_content(_LC_DATA, learning_stage)
    }
    performance_by_value = {
        entry["value"]: entry
        for entry in allowed_learning_performance(_LP_DATA, learning_stage)
    }
    result: list[str] = []
    seen: set[str] = set()
    for code in performance_codes:
        for content_code in performance_by_value.get(code, {}).get("對應學習內容", []):
            if content_code in content_by_value and content_code not in seen:
                seen.add(content_code)
                result.append(content_code)
    return result


def sample_params(
    grade: int | None = None,
    context: list[QuestionContext] | None = None,
    sub_context: QuestionSubContext | None = None,
    set_type: QuestionSetType | None = None,
    q_type: list[QuestionType] | None = None,
    science_competency: list[ScienceCompetency] | None = None,
    learning_content: list[str] | None = None,
    learning_performance: list[str] | None = None,
    content_type: str | None = None,
    seed: int | None = None,
    sub_question_count: int | None = None,
    question_word_limit: int | None = None,
    option_word_limit: int | None = None,
    subquestion_configs: list | None = None,
    difficulty: Difficulty | str | None = None,
) -> SampledParams:
    """Sample random PISA Science parameters for a single 題組."""

    rng = random.Random(seed)
    resolved_difficulty: Difficulty = resolve_difficulty(difficulty)

    selected_grade = grade if grade is not None else rng.choice(_GRADES)
    learning_stage = grade_to_learning_stage(selected_grade)

    if context is not None:
        selected_context = context
    elif sub_context is not None and _SUB_CONTEXT_PARENT.get(sub_context.value):
        parent = _SUB_CONTEXT_PARENT[sub_context.value]
        selected_context = [QuestionContext(parent)]
    else:
        selected_context = [rng.choice(list(QuestionContext))]

    context_values = {c.value for c in selected_context}
    if sub_context is not None and _SUB_CONTEXT_PARENT.get(sub_context.value) in context_values:
        selected_sub_context = sub_context
    else:
        sub_context_pool = _matching_subcontexts(context_values) or list(QuestionSubContext)
        selected_sub_context = rng.choice(sub_context_pool)

    selected_set_type = set_type if set_type is not None else rng.choice(list(QuestionSetType))
    selected_q_type = rng.choice(q_type) if q_type is not None else rng.choice(list(QuestionType))

    if science_competency is not None:
        selected_science_competency = science_competency
    else:
        pool = list(ScienceCompetency)
        competency_count = rng.randint(1, min(2, len(pool)))
        selected_science_competency = rng.sample(pool, competency_count)

    selected_content_type = (
        content_type.strip()
        if content_type and content_type.strip()
        else rng.choice(_RANDOM_CONTENT_TYPE_VALUES or _CONTENT_TYPE_VALUES or ["純文字"])
    )

    if learning_performance is not None:
        selected_lp_pool = learning_performance
    else:
        lp_entries = allowed_learning_performance(_LP_DATA, learning_stage)
        lp_count = rng.randint(1, min(2, max(1, len(lp_entries))))
        selected_lp_pool = (
            [e["value"] for e in rng.sample(lp_entries, lp_count)]
            if lp_entries
            else []
        )

    if learning_content is not None:
        selected_lc_pool = learning_content
    else:
        mapped_content = _content_from_performance(selected_lp_pool, learning_stage)
        if mapped_content:
            lc_count = rng.randint(1, min(3, len(mapped_content)))
            selected_lc_pool = rng.sample(mapped_content, lc_count)
        else:
            lc_entries = allowed_learning_content(_LC_DATA, learning_stage)
            lc_count = rng.randint(1, min(3, max(1, len(lc_entries))))
            selected_lc_pool = (
                [e["value"] for e in rng.sample(lc_entries, lc_count)]
                if lc_entries
                else []
            )

    from src.natural_sciences.reporting_scale import REPORTING_SCALE_ORDER
    from src.natural_sciences.schemas import SubQuestionConfig
    resolved_configs: list[SubQuestionConfig] = []
    if subquestion_configs:
        for cfg in subquestion_configs:
            if isinstance(cfg, dict):
                resolved_configs.append(SubQuestionConfig(**cfg))
            elif isinstance(cfg, SubQuestionConfig):
                resolved_configs.append(cfg)

    q_type_pool = q_type if q_type is not None else list(QuestionType)

    if sub_question_count is not None:
        if not 3 <= sub_question_count <= 7:
            raise ValueError("sub_question_count must be between 3 and 7")
        resolved_configs = [
            resolved_configs[i] if i < len(resolved_configs) else SubQuestionConfig()
            for i in range(sub_question_count)
        ]
        blank_count = sum(1 for cfg in resolved_configs if not cfg.question_type)
        pinned_types = {cfg.question_type for cfg in resolved_configs if cfg.question_type}
        fill_pool = [q for q in q_type_pool if q not in pinned_types] or list(q_type_pool)
        shuffled = list(fill_pool)
        rng.shuffle(shuffled)
        fill_iter = iter(shuffled[i % len(shuffled)] for i in range(blank_count))
        resolved_configs = [
            cfg.model_copy(update={"question_type": cfg.question_type or next(fill_iter)})
            for cfg in resolved_configs
        ]
    else:
        # No explicit 小題 count: keep any caller-provided configs and fill their
        # blank 題型 slots from the pool (parallel to the counted path above).
        if resolved_configs:
            blank_count = sum(1 for cfg in resolved_configs if not cfg.question_type)
            shuffled = list(q_type_pool)
            rng.shuffle(shuffled)
            fill_iter = iter(shuffled[i % len(shuffled)] for i in range(blank_count))
            resolved_configs = [
                cfg.model_copy(update={"question_type": cfg.question_type or next(fill_iter)})
                for cfg in resolved_configs
            ]

    if resolved_configs:
        resolved_configs = [
            cfg.model_copy(
                update={
                    "reporting_scale": cfg.reporting_scale
                    or rng.choice(REPORTING_SCALE_ORDER)
                }
            )
            for cfg in resolved_configs
        ]
        selected_q_type = resolved_configs[0].question_type or selected_q_type

    return SampledParams(
        grade=selected_grade,
        情境=selected_context,
        情境子類別=selected_sub_context,
        題型種類=selected_set_type,
        題型=selected_q_type,
        科學能力=selected_science_competency,
        題目內容類型=selected_content_type,
        學習內容_pool=selected_lc_pool,
        學習表現_pool=selected_lp_pool,
        sub_question_count=sub_question_count,
        question_word_limit=question_word_limit,
        option_word_limit=option_word_limit,
        subquestion_configs=resolved_configs,
        difficulty=resolved_difficulty,
    )
