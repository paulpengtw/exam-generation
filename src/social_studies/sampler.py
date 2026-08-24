"""Random parameter selection for social studies (PISA reading) question generation."""

from __future__ import annotations

import random

from src.common.difficulty import Difficulty, resolve_difficulty
from src.social_studies.core_competency_loader import (
    allowed_competencies,
    load_core_competencies,
)
from src.social_studies.curriculum_loader import (
    allowed_learning_content,
    allowed_learning_performance,
    load_learning_content,
    load_learning_performance,
)
from src.social_studies.schema_loader import load_grades, load_learning_stage, load_schemas
from src.social_studies.schemas import (
    CognitiveProcess,
    ContentDomain,
    CoreCompetency,
    QuestionContext,
    QuestionSetType,
    QuestionSubject,
    QuestionType,
    ReadingProcess,
    SampledParams,
    TextForm,
)

_schemas = load_schemas()
_GRADES: list[int] = load_grades(_schemas)
# Deliberately fixed; see README "Natural sciences vs social studies differences" and #192.
_LEARNING_STAGE: str = load_learning_stage(_schemas)
_CONTENT_TYPE_VALUES: list[str] = [
    row["value"] for row in _schemas.get("題目內容類型", []) if row.get("value")
]
_RANDOM_CONTENT_TYPE_VALUES: list[str] = [
    v for v in _CONTENT_TYPE_VALUES if v != "customized"
]
_MAX_SUBQUESTION_SLOTS = 7
_CC_DATA: dict = load_core_competencies()
_ALLOWED_COMPETENCY_VALUES: list[str] = allowed_competencies(_CC_DATA, _LEARNING_STAGE)
_ALLOWED_COMPETENCIES: list[CoreCompetency] = [CoreCompetency(v) for v in _ALLOWED_COMPETENCY_VALUES]  # type: ignore[misc]

_LC_DATA: dict = load_learning_content()
_LP_DATA: dict = load_learning_performance()


def sample_params(
    grade: int | None = None,
    context: list[QuestionContext] | None = None,
    set_type: QuestionSetType | None = None,
    q_type: list[QuestionType] | None = None,
    subject: list[QuestionSubject] | None = None,
    core_competency: list[CoreCompetency] | None = None,
    learning_content: list[str] | None = None,
    learning_performance: list[str] | None = None,
    content_type: str | None = None,
    seed: int | None = None,
    sub_question_count: int | None = None,
    question_word_limit: int | None = None,
    option_word_limit: int | None = None,
    subquestion_configs: list | None = None,
    difficulty: Difficulty | str | None = None,
    allow_duplicate_figure_kinds: bool = False,
) -> SampledParams:
    """Sample random PISA-reading question parameters.

    No grade_content needed — reading literacy has no K-12 curriculum code lookup.
    Sampler cardinality: 情境 1+, 文本形式 1, 閱讀歷程 1-2; 題型種類 forced 題組題.

    """
    rng = random.Random(seed)
    resolved_difficulty: Difficulty = resolve_difficulty(difficulty)

    selected_grade = grade if grade is not None else rng.choice(_GRADES)

    all_contexts = list(QuestionContext)
    if context is not None:
        selected_context = context
    else:
        context_count = rng.randint(1, len(all_contexts))
        selected_context = rng.sample(all_contexts, context_count)

    # 題型種類 is always 題組題 in PISA; schema has only one value so this is deterministic.
    selected_set_type = set_type if set_type is not None else rng.choice(list(QuestionSetType))

    if sub_question_count is not None and not 3 <= sub_question_count <= 7:
        raise ValueError("sub_question_count must be between 3 and 7")

    if q_type:
        q_type_pool = q_type
    else:
        q_type_pool = list(QuestionType)

    # 閱讀歷程: pick 1-2
    all_processes = list(ReadingProcess)
    process_count = rng.randint(1, min(2, len(all_processes)))
    selected_process = rng.sample(all_processes, process_count)

    selected_content_type = (
        content_type.strip()
        if content_type and content_type.strip()
        else rng.choice(_RANDOM_CONTENT_TYPE_VALUES or _CONTENT_TYPE_VALUES or ["純文字"])
    )

    # 文本形式: align built-in content types with compatible text forms.
    all_text_forms = list(TextForm)
    if selected_content_type == "純文字":
        text_form_pool = [f for f in all_text_forms if f.value.startswith("連續文本")]
    elif selected_content_type == "graphs/charts/tables":
        text_form_pool = [
            f for f in all_text_forms
            if f.value in {"非連續文本—圖表與圖形", "非連續文本—表格"}
        ]
    elif selected_content_type == "含圖片":
        text_form_pool = [
            f for f in all_text_forms
            if f.value.startswith("非連續文本") and f.value not in {"非連續文本—圖表與圖形", "非連續文本—表格"}
        ]
    else:
        text_form_pool = all_text_forms
    selected_text_form = rng.choice(text_form_pool or all_text_forms)

    selected_subject = rng.choice(subject) if subject is not None else rng.choice(list(QuestionSubject))

    if core_competency is not None:
        selected_competency = core_competency
    else:
        pool = _ALLOWED_COMPETENCIES
        competency_count = rng.randint(1, min(3, len(pool)))
        selected_competency = rng.sample(pool, competency_count)

    subj_key = selected_subject.value
    if learning_content is not None:
        selected_lc_pool = learning_content
    else:
        lc_entries = allowed_learning_content(_LC_DATA, _LEARNING_STAGE, subj_key)
        lc_count = rng.randint(1, min(3, max(1, len(lc_entries))))
        selected_lc_pool = [e["value"] for e in rng.sample(lc_entries, lc_count)] if lc_entries else []

    if learning_performance is not None:
        selected_lp_pool = learning_performance
    else:
        lp_entries = allowed_learning_performance(_LP_DATA, _LEARNING_STAGE, subj_key)
        lp_count = rng.randint(1, min(2, max(1, len(lp_entries))))
        selected_lp_pool = [e["value"] for e in rng.sample(lp_entries, lp_count)] if lp_entries else []

    from src.social_studies.schemas import SubQuestionConfig
    resolved_configs: list[SubQuestionConfig] = []
    if subquestion_configs:
        for cfg in subquestion_configs:
            if isinstance(cfg, dict):
                resolved_configs.append(SubQuestionConfig(**cfg))
            elif isinstance(cfg, SubQuestionConfig):
                resolved_configs.append(cfg)

    # 題型 is owned by each 小題 when the count is known. Missing row types are
    # sampled deterministically from the request pool or the full schema.
    if sub_question_count is not None:
        resolved_configs = [
            resolved_configs[i] if i < len(resolved_configs) else SubQuestionConfig()
            for i in range(sub_question_count)
        ]
        # Fill blank slots from a shuffled cycle so no 題型 repeats before exhausting
        # the pool. Pinned slots are untouched; only blank slots consume from fill_iter.
        blank_count = sum(1 for cfg in resolved_configs if not cfg.question_type)
        pinned_types = {cfg.question_type for cfg in resolved_configs if cfg.question_type}
        fill_pool = [q for q in q_type_pool if q not in pinned_types] or q_type_pool[:]
        shuffled = fill_pool[:]
        rng.shuffle(shuffled)
        fill_iter = iter(shuffled[i % len(shuffled)] for i in range(blank_count))
        resolved_configs = [
            cfg.model_copy(update={"question_type": cfg.question_type or next(fill_iter)})
            for cfg in resolved_configs
        ]
        selected_q_types: list[QuestionType] = []
        for cfg in resolved_configs:
            if cfg.question_type and cfg.question_type not in selected_q_types:
                selected_q_types.append(cfg.question_type)
    else:
        # Legacy/global mode for CLI or API callers that do not pin 小題 count.
        type_count = rng.randint(1, min(3, len(q_type_pool)))
        selected_q_types = rng.sample(q_type_pool, type_count)

    selected_content_domain = rng.choice(list(ContentDomain))
    slot_count = sub_question_count or len(resolved_configs) or _MAX_SUBQUESTION_SLOTS
    selected_cognitive_processes = [
        rng.choice(list(CognitiveProcess)).value for _ in range(slot_count)
    ]
    if resolved_configs:
        resolved_configs = [
            cfg.model_copy(update={"認知歷程": selected_cognitive_processes[i]})
            for i, cfg in enumerate(resolved_configs)
        ]

    return SampledParams(
        grade=selected_grade,
        seed=seed,
        情境=selected_context,
        題型種類=selected_set_type,
        題型=selected_q_types,
        閱讀歷程=selected_process,
        文本形式=selected_text_form,
        題目內容類型=selected_content_type,
        科目=selected_subject,
        內容領域=selected_content_domain,
        核心素養=selected_competency,
        學習內容_pool=selected_lc_pool,
        學習表現_pool=selected_lp_pool,
        認知歷程_pool=selected_cognitive_processes,
        sub_question_count=sub_question_count,
        question_word_limit=question_word_limit,
        option_word_limit=option_word_limit,
        subquestion_configs=resolved_configs,
        allow_duplicate_figure_kinds=allow_duplicate_figure_kinds,
        difficulty=resolved_difficulty,
    )


def ss_sample_params(rng: random.Random | None = None, **kwargs) -> SampledParams:
    seed = kwargs.pop("seed", None)
    if seed is None and rng is not None:
        seed = rng.randrange(2**32)
    return sample_params(seed=seed, **kwargs)
