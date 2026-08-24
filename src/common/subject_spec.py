"""Per-subject loader spec — the single source of truth for subject-specific config.

``src.common`` modules (``core_competency_loader``, ``curriculum_loader``,
``schema_loader``) are parameterised by the data in this module.

Design constraint: ``src/`` must NOT import from ``server/``.  The server's
``SubjectSpec`` in ``server/generate/subjects.py`` may reference these specs if
helpful, but the loader-facing configuration lives here to avoid a circular
dependency (``server/`` imports ``src/``; the reverse is forbidden).

``SubjectLoaderSpec`` is intentionally small — it holds only scalar/path data
needed by the three common loader families.  Behaviour (functions) stays in the
individual loaders; this module is pure data.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent


@dataclasses.dataclass(frozen=True)
class SubjectLoaderSpec:
    """All per-subject data needed to parameterise the common loaders.

    Fields
    ------
    data_dir
        Default path for curriculum JSON files
        (``learning_content.json``, ``learning_performance.json``).
    curriculum_dir_env
        Env-var that overrides the whole curriculum directory for the schema
        loader (``schema_meta.csv`` / ``schema_parameters.csv``).
    lc_path_env
        Env-var override for the ``learning_content.json`` path (``None`` if
        the subject has no per-file override; currently both SS and NS have
        one).
    lp_path_env
        Env-var override for the ``learning_performance.json`` path.
    lp_intro_path_env
        Env-var override for the ``learning_performance_intro.md`` path.
    subject_to_prefixes
        Map from 科目 value → set of 科目 prefix chars used by
        ``curriculum_loader`` filters.  An **empty dict** signals the NS
        convention: no prefix bucketing — ``subject=None`` returns all stage
        entries, an explicit subject filters by exact ``科目`` match (falling
        back to ``{subject}`` since the map has no entry for it).
    core_competency_data_path
        Default path for ``core_competencies.json``.
    core_competency_path_env
        Env-var override for the ``core_competencies.json`` path.
    core_competency_subject_prefix
        Short subject character passed to ``build_core_competency_enum``
        (``"社"`` / ``"自"``).
    core_competency_enum_name
        Name for the generated Enum class
        (``"CoreCompetency"`` / ``"NaturalCoreCompetency"``).
    schema_categories
        Ordered tuple of category names for the schema loader.
    """

    # ── curriculum loader ────────────────────────────────────────────────────
    data_dir: Path
    curriculum_dir_env: str
    lc_path_env: str | None
    lp_path_env: str | None
    lp_intro_path_env: str | None
    subject_to_prefixes: dict[str, set[str]]

    # ── core competency loader ───────────────────────────────────────────────
    core_competency_data_path: Path
    core_competency_path_env: str
    core_competency_subject_prefix: str
    core_competency_enum_name: str

    # ── schema loader ────────────────────────────────────────────────────────
    schema_categories: tuple[str, ...]


# ── Social studies ──────────────────────────────────────────────────────────

SOCIAL_STUDIES = SubjectLoaderSpec(
    data_dir=_REPO_ROOT / "data" / "social_studies" / "curriculum",
    curriculum_dir_env="SOCIAL_STUDIES_CURRICULUM_DIR",
    lc_path_env="SOCIAL_STUDIES_LEARNING_CONTENT_PATH",
    lp_path_env="SOCIAL_STUDIES_LEARNING_PERFORMANCE_PATH",
    lp_intro_path_env="SOCIAL_STUDIES_LEARNING_PERFORMANCE_INTRO_PATH",
    # 社_* codes are cross-subject; empty-string 科目 entries appear in all pools.
    subject_to_prefixes={
        "歷史": {"歷", "社", ""},
        "地理": {"地", "社", ""},
        "公民與社會": {"公", "社", ""},
        "跨科": {"歷", "地", "公", "社", ""},
    },
    core_competency_data_path=(
        _REPO_ROOT / "data" / "social_studies" / "curriculum" / "core_competencies.json"
    ),
    core_competency_path_env="SOCIAL_STUDIES_CORE_COMPETENCIES_PATH",
    core_competency_subject_prefix="社",
    core_competency_enum_name="CoreCompetency",
    schema_categories=(
        "情境", "題型種類", "題型", "認知歷程", "內容領域", "科目", "題目內容類型", "難度",
    ),
)


# ── Natural sciences ────────────────────────────────────────────────────────

NATURAL_SCIENCES = SubjectLoaderSpec(
    data_dir=_REPO_ROOT / "data" / "natural_sciences" / "curriculum",
    curriculum_dir_env="NATURAL_SCIENCES_CURRICULUM_DIR",
    lc_path_env="NATURAL_SCIENCES_LEARNING_CONTENT_PATH",
    lp_path_env="NATURAL_SCIENCES_LEARNING_PERFORMANCE_PATH",
    lp_intro_path_env="NATURAL_SCIENCES_LEARNING_PERFORMANCE_INTRO_PATH",
    # NS has no subject bucketing at the sampler level.  An empty dict causes
    # the common _subject_prefixes() helper to fall back to {subject} for an
    # explicit value and to return None (= no filter) for subject=None.
    subject_to_prefixes={},
    core_competency_data_path=(
        _REPO_ROOT / "data" / "natural_sciences" / "curriculum" / "core_competencies.json"
    ),
    core_competency_path_env="NATURAL_SCIENCES_CORE_COMPETENCIES_PATH",
    core_competency_subject_prefix="自",
    core_competency_enum_name="NaturalCoreCompetency",
    schema_categories=(
        "情境", "情境子類別", "題型種類", "題型", "科學能力", "題目內容類型",
    ),
)


@dataclasses.dataclass(frozen=True)
class SubjectGenerationSpec:
    """Per-subject wiring for the shared NS/SS generation core.

    Instances are created at module import time in each subject's ``cli.py``
    and passed to ``generate_one_core`` / ``generate_with_corrections_core``
    in ``src.common.generation_core``.
    """

    # Data subdirectory name under config.data_dir for few-shot examples.
    # Core computes: config.data_dir / few_shot_subdir / "few_shot"
    few_shot_subdir: str

    # Build text-generator system prompt.
    # Signature: (params: Any) -> tuple[str, dict]
    # Returns (system_prompt, stage_ctx) where stage_ctx is subject-specific
    # context forwarded to build_subquestion_system_fn and used in
    # build_subquestion_user_fn.
    build_text_system_fn: Callable

    # Build text-generator user prompt.
    # Signature: (params, few_shot_dir, user_passage, user_options, user_topic,
    #              user_core_question, image_generation_mode,
    #              disable_reference_fewshot, prior_scopes,
    #              core_question_callback) -> tuple[str, list]
    build_text_user_fn: Callable

    # Build subquestion system prompt.
    # Signature: (stage_ctx: dict) -> str
    build_subquestion_system_fn: Callable

    # Build subquestion user prompt.
    # Signature: (text_raw, params, few_shot_dir, sq_plan, slot_cfg,
    #              image_generation_mode, disable_reference_fewshot,
    #              core_question_callback, is_last) -> tuple[str, list]
    build_subquestion_user_fn: Callable

    # Parse text-generator JSON into an ExamQuestion shell (subquestions=[]).
    # Signature: (raw, question_id, params, model) -> ExamQuestion
    parse_text_shell_fn: Callable

    # Parse one subquestion dict into a SubQuestion.
    # Signature: (sq_raw, question_id, params, idx) -> SubQuestion | None
    parse_subquestion_fn: Callable

    # Generate fallback sq-plan list when text-generator emits none.
    # Signature: (params, n: int) -> list[dict]
    make_fallback_sq_plans_fn: Callable

    # SS-only: ensure a top-level visual spec exists after subquestions assemble.
    # Mutates question in-place. Returns True if question.chart_spec changed.
    # Signature: (question, params, client) -> bool
    # None → no-op (NS uses None)
    ensure_visual_spec_fn: Callable | None

    # Render per-subquestion image specs to PNGs.
    # Signature: (question, config, client, html_renderer, image_generation_mode,
    #              obs, params, on_figure_policy_entry=...) -> list[str]
    # None → no-op
    render_subquestion_images_fn: Callable | None

    # Extract the question-text string for image rendering / re-rendering.
    # NS: lambda q: "\n".join(q.題目)
    # SS: lambda q: "\n".join(q.題目) or q.文本
    # Signature: (question) -> str
    image_question_text_fn: Callable

    # Verify the assembled question.
    # Signature: (client, question, *, chart_image_path, curriculum_context) -> VerificationResult
    verify_fn: Callable

    # Correct a failed question given the verification result.
    # Signature: (client, question, verification, *, chart_image_path,
    #              curriculum_context) -> question
    correct_fn: Callable
