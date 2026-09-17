"""Random parameter selection for social-studies question generation."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable

from src.common.admission import entries_admitted_by
from src.common.difficulty import Difficulty, resolve_difficulty
from src.common.randomness import draw_rng
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
    SampledParams,
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
_CC_DATA: dict = load_core_competencies()
_ALLOWED_COMPETENCY_VALUES: list[str] = allowed_competencies(_CC_DATA, _LEARNING_STAGE)
_ALLOWED_COMPETENCIES: list[CoreCompetency] = [
    CoreCompetency(v) for v in _ALLOWED_COMPETENCY_VALUES
]  # type: ignore[misc]

_LC_DATA: dict = load_learning_content()
_LP_DATA: dict = load_learning_performance()
_DOMAIN_FILTER_SUBJECTS = {"公民與社會", "跨科"}
logger = logging.getLogger(__name__)
_KNOWING_DEFINING = "Knowing–Defining and Describing"
_KNOWING_ILLUSTRATING = "Knowing–Illustrating with examples"
_REASONING_INTERPRET = "Reasoning and Applying–Interpret information"
_REASONING_RELATE = "Reasoning and Applying–Relate or Integrate"
_REASONING_PROCESSES = (_REASONING_INTERPRET, _REASONING_RELATE)
_COGNITIVE_PROCESS_VALUES = frozenset(member.value for member in CognitiveProcess)
_QUESTION_TYPE_VALUES = frozenset(member.value for member in QuestionType)
_INTERACTIVE_QUESTION_TYPE_VALUES = frozenset({"拖放題", "滑桿題"})
_QUESTION_TYPE_WEIGHTS: dict[str, int] = {
    "選擇題": 85,
    "開放式建構反應題": 10,
    "拖放題": 3,
    "滑桿題": 2,
}


class IncompatibleContentDomainError(ValueError):
    """A pinned ICCS domain has no admitted learning-content rows."""


def _filter_entries_for_domain(
    entries: list[dict],
    domain: ContentDomain,
    subject: QuestionSubject,
) -> list[dict]:
    """Keep 學習內容 rows admitted by *domain* for subjects whose parent applies.

    Reads the shared admission lookup over each entry's ``admitted_by``
    tags (attached at curriculum-load time); no code-prefix check and no
    separately built domain map on this path.
    """
    if subject.value not in _DOMAIN_FILTER_SUBJECTS:
        return entries
    return entries_admitted_by(entries, "內容領域", domain.value)


def _resolve_domain_and_pools(
    rng: random.Random | None,
    selected_domain: ContentDomain | None,
    subject: QuestionSubject,
    lc_entries: list[dict] | None,
    lp_entries: list[dict] | None,
    *,
    domain_pinned: bool = False,
) -> tuple[ContentDomain, list[dict] | None, list[dict] | None]:
    """Draw once from domains with a non-empty dependent learning-content pool."""
    domains = list(ContentDomain)
    if subject.value not in _DOMAIN_FILTER_SUBJECTS:
        if selected_domain is None:
            assert rng is not None
            selected_domain = rng.choice(domains)
        return selected_domain, lc_entries, lp_entries

    usable_domains = [
        domain
        for domain in domains
        if lc_entries is None
        or _filter_entries_for_domain(lc_entries, domain, subject)
    ]
    if not domain_pinned and usable_domains:
        assert rng is not None
        selected_domain = rng.choice(usable_domains)
    selected_domain = selected_domain or domains[0]

    filtered_lc = (
        _filter_entries_for_domain(lc_entries, selected_domain, subject)
        if lc_entries is not None
        else None
    )
    # 學習表現 has no 內容領域 parent (#833): the pool passes through unfiltered.
    return selected_domain, filtered_lc, lp_entries


def _assign_cognitive_processes(
    field_rng: Callable[[str], random.Random],
    slot_count: int,
    subject: QuestionSubject,
    pinned_assignments: list[str | None] | None = None,
) -> list[str]:
    """Assign ICCS processes while preserving valid per-slot pins."""
    if slot_count <= 0:
        return []

    pins = list(pinned_assignments or [])[:slot_count]
    pins.extend([None] * (slot_count - len(pins)))
    assignments: list[str | None] = [
        value if value in _COGNITIVE_PROCESS_VALUES else None for value in pins
    ]
    slot_rngs = {
        index: field_rng(f"subquestion_configs[{index}].認知歷程")
        for index in range(slot_count)
    }
    unpinned_indices = [index for index, value in enumerate(assignments) if value is None]
    tiers = [
        "Knowing"
        if slot_rngs[index].random() < (1 / 3)
        else "Reasoning"
        for index in unpinned_indices
    ]
    knowing_indices = [
        index for index, tier in zip(unpinned_indices, tiers) if tier == "Knowing"
    ]
    has_pinned_defining = _KNOWING_DEFINING in assignments
    defining_index = (
        min(
            knowing_indices,
            key=lambda index: slot_rngs[index].random(),
        )
        if knowing_indices and not has_pinned_defining
        else None
    )
    for index, tier in zip(unpinned_indices, tiers):
        assignments[index] = (
            _KNOWING_DEFINING
            if index == defining_index
            else _KNOWING_ILLUSTRATING
            if tier == "Knowing"
            else slot_rngs[index].choice(_REASONING_PROCESSES)
        )

    if (
        subject.value == "跨科"
        and _REASONING_RELATE not in assignments
        and unpinned_indices
    ):
        reasoning_candidates = [
            index
            for index in unpinned_indices
            if assignments[index] in _REASONING_PROCESSES
        ] or unpinned_indices
        reasoning_index = min(
            reasoning_candidates,
            key=lambda index: slot_rngs[index].random(),
        )
        assignments[reasoning_index] = _REASONING_RELATE

    return [value for value in assignments if value is not None]


def _coerce_subquestion_config(raw: dict, config_cls: type) -> object:
    """Keep invalid tolerant-channel enum pins as blank slots."""
    data = dict(raw)
    cognitive_value = data.get("cognitive_process", data.get("認知歷程"))
    if (
        cognitive_value is not None
        and (
            not isinstance(cognitive_value, str)
            or cognitive_value not in _COGNITIVE_PROCESS_VALUES
        )
    ):
        data.pop("cognitive_process", None)
        data.pop("認知歷程", None)
    question_type = data.get("question_type")
    if (
        question_type is not None
        and (
            not isinstance(question_type, str)
            or question_type not in _QUESTION_TYPE_VALUES
        )
    ):
        data.pop("question_type", None)
    return config_cls(**data)


def _question_type_value(question_type: QuestionType | str) -> str:
    return getattr(question_type, "value", question_type)


def _question_type_draw_pool(
    q_type: list[QuestionType] | None,
    target_surface: str,
) -> list[QuestionType]:
    """Return the live per-slot pool, excluding digital types on paper."""
    source = list(q_type) if q_type else list(QuestionType)
    pool = [
        question_type
        for question_type in source
        if target_surface == "數位"
        or _question_type_value(question_type) not in _INTERACTIVE_QUESTION_TYPE_VALUES
    ]
    if not pool:
        raise ValueError("no drawable question types remain for target_surface")
    return pool


def _draw_question_types(
    field_rng: Callable[[str], random.Random],
    pool: list[QuestionType],
    slot_indices: list[int],
) -> list[QuestionType]:
    weights = [
        _QUESTION_TYPE_WEIGHTS.get(_question_type_value(question_type), 1)
        for question_type in pool
    ]
    return [
        field_rng(f"subquestion_configs[{index}].question_type").choices(
            pool, weights=weights, k=1
        )[0]
        for index in slot_indices
    ]


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
    content_domain: str | ContentDomain | None = None,
    target_surface: str | None = None,
    seed: int | None = None,
    sub_question_count: int | None = None,
    question_word_limit: int | None = None,
    option_word_limit: int | None = None,
    subquestion_configs: list | None = None,
    difficulty: Difficulty | str | None = None,
    allow_duplicate_figure_kinds: bool = False,
    *,
    redraws: dict[str, int] | None = None,
) -> SampledParams:
    """Sample random social-studies question parameters.

    No grade_content needed — the social-studies curriculum pools are loaded by code.
    題型種類 is forced to the single 題組題 schema value.

    """
    redraws = redraws or {}

    def field_rng(field_path: str) -> random.Random:
        return draw_rng(seed, field_path, redraws.get(field_path, 0))

    resolved_difficulty: Difficulty = resolve_difficulty(difficulty)
    resolved_surface = "紙本" if target_surface is None else target_surface
    if resolved_surface not in {"紙本", "數位"}:
        raise ValueError("target_surface must be one of ['紙本', '數位']")

    selected_grade = grade if grade is not None else field_rng("grade").choice(_GRADES)

    all_contexts = list(QuestionContext)
    if context is not None:
        selected_context = context
    else:
        context_rng = field_rng("情境")
        context_count = context_rng.randint(1, len(all_contexts))
        selected_context = context_rng.sample(all_contexts, context_count)

    # 題型種類 has only one schema value, so this is deterministic.
    selected_set_type = (
        set_type if set_type is not None else field_rng("題型種類").choice(list(QuestionSetType))
    )

    if sub_question_count is not None and not 3 <= sub_question_count <= 7:
        raise ValueError("sub_question_count must be between 3 and 7")

    q_type_pool = _question_type_draw_pool(q_type, resolved_surface)

    selected_content_type = (
        content_type.strip()
        if content_type and content_type.strip()
        else field_rng("題目內容類型").choice(
            _RANDOM_CONTENT_TYPE_VALUES or _CONTENT_TYPE_VALUES or ["純文字"]
        )
    )

    selected_subject = (
        field_rng("科目").choice(subject)
        if subject is not None
        else field_rng("科目").choice(list(QuestionSubject))
    )
    # Resolve the ICCS domain before the dependent learning-content pool draw.
    domain_pinned = content_domain is not None
    domain_rng = field_rng("內容領域") if not domain_pinned else None
    selected_content_domain = (
        ContentDomain(content_domain) if content_domain is not None else None
    )

    if core_competency is not None:
        selected_competency = core_competency
    else:
        pool = _ALLOWED_COMPETENCIES
        competency_rng = field_rng("核心素養")
        competency_count = competency_rng.randint(1, min(3, len(pool)))
        selected_competency = competency_rng.sample(pool, competency_count)

    subj_key = selected_subject.value
    lc_entries = allowed_learning_content(_LC_DATA, _LEARNING_STAGE, subj_key)
    lp_entries = (
        None
        if learning_performance is not None
        else allowed_learning_performance(_LP_DATA, _LEARNING_STAGE, subj_key)
    )
    selected_content_domain, lc_entries, lp_entries = _resolve_domain_and_pools(
        domain_rng,
        selected_content_domain,
        selected_subject,
        lc_entries,
        lp_entries,
        domain_pinned=domain_pinned,
    )

    if domain_pinned and selected_subject.value in _DOMAIN_FILTER_SUBJECTS:
        admitted_codes = {entry["value"] for entry in lc_entries or []}
        if not admitted_codes:
            raise IncompatibleContentDomainError(selected_content_domain.value)
        if learning_content is not None and any(
            code not in admitted_codes for code in learning_content
        ):
            raise IncompatibleContentDomainError(selected_content_domain.value)

    if learning_content is not None:
        selected_lc_pool = learning_content
    else:
        lc_rng = field_rng("學習內容")
        lc_count = lc_rng.randint(1, min(3, max(1, len(lc_entries or []))))
        selected_lc_pool = (
            [e["value"] for e in lc_rng.sample(lc_entries or [], lc_count)]
            if lc_entries
            else []
        )

    if learning_performance is not None:
        selected_lp_pool = learning_performance
    else:
        lp_rng = field_rng("學習表現")
        lp_count = lp_rng.randint(1, min(2, max(1, len(lp_entries or []))))
        selected_lp_pool = (
            [e["value"] for e in lp_rng.sample(lp_entries or [], lp_count)]
            if lp_entries
            else []
        )

    from src.social_studies.schemas import SubQuestionConfig
    resolved_configs: list[SubQuestionConfig] = []
    if subquestion_configs:
        for cfg in subquestion_configs:
            if isinstance(cfg, dict):
                resolved_configs.append(_coerce_subquestion_config(cfg, SubQuestionConfig))
            elif isinstance(cfg, SubQuestionConfig):
                resolved_configs.append(cfg)

    if resolved_surface != "數位":
        pinned_interactive = [
            cfg.question_type.value
            for cfg in resolved_configs
            if cfg.question_type is not None
            and cfg.question_type.value in _INTERACTIVE_QUESTION_TYPE_VALUES
        ]
        if pinned_interactive:
            raise ValueError(
                "target_surface must be 數位 for digital-only question type(s): "
                + ", ".join(dict.fromkeys(pinned_interactive))
            )

    # 題型 is owned by each 小題 when the count is known. Missing row types are
    # sampled deterministically from the request pool or the full schema.
    if sub_question_count is not None:
        resolved_configs = [
            resolved_configs[i] if i < len(resolved_configs) else SubQuestionConfig()
            for i in range(sub_question_count)
        ]
        # Draw unpinned slots with ICCS composition weights. Pinned slots are
        # untouched; only blank slots consume from the weighted draw stream.
        fill_pool = q_type_pool
        blank_indices = [
            index for index, cfg in enumerate(resolved_configs) if not cfg.question_type
        ]
        fill_iter = iter(_draw_question_types(field_rng, fill_pool, blank_indices))
        resolved_configs = [
            cfg.model_copy(update={"question_type": cfg.question_type or next(fill_iter)})
            for cfg in resolved_configs
        ]
        selected_q_types: list[QuestionType] = []
        for cfg in resolved_configs:
            if cfg.question_type and cfg.question_type not in selected_q_types:
                selected_q_types.append(cfg.question_type)
    else:
        # Standalone sampler callers may still omit the count, but there is no
        # request-wide random 題型 or extra cognitive-process slot.  The resolver
        # always supplies the structural count before generation reaches here.
        selected_q_types = list(q_type_pool)

    slot_count = len(resolved_configs)
    selected_cognitive_processes = _assign_cognitive_processes(
        field_rng,
        slot_count,
        selected_subject,
        [cfg.認知歷程 for cfg in resolved_configs],
    )
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
        題目內容類型=selected_content_type,
        科目=selected_subject,
        內容領域=selected_content_domain,
        target_surface=resolved_surface,
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
