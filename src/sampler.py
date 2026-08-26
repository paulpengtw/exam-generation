"""Random parameter selection for exam question generation."""

from __future__ import annotations

from pathlib import Path

from src.common.core_competency_loader import (
    allowed_competencies,
    load_core_competencies,
)
from src.common.curriculum_loader import (
    allowed_learning_content,
    allowed_learning_performance,
    load_learning_content,
    load_learning_performance,
)
from src.common.difficulty import Difficulty, resolve_difficulty
from src.common.randomness import draw_rng
from src.schema_loader import load_grades, load_schemas
from src.schemas import (
    CoreCompetency,
    LearningContentItem,
    MathThinking,
    QuestionContext,
    QuestionSetType,
    QuestionStyle,
    QuestionType,
    SampledParams,
)

_GRADES: list[int] = load_grades(load_schemas())

# Math 科目 → 學習內容/學習表現 prefix-letter set.
_MATH_SUBJECT_TO_PREFIXES: dict[str, set[str]] = {
    "數與量": {"N", "n"},
    "代數": {"A", "F", "R", "a", "f", "r"},
    "幾何": {"S", "G", "s", "g"},
    "統計與機率": {"D", "P", "d", "p"},
    "跨領域": {"N", "A", "F", "R", "S", "G", "D", "P", "n", "a", "f", "r", "s", "g", "d", "p"},
}

# Math curriculum data, materialized in Phase 2.
_MATH_DATA_DIR = Path(__file__).parent.parent / "data" / "math" / "curriculum"
_LC_DATA: dict = load_learning_content(
    _MATH_DATA_DIR,
    subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES,
)
_LP_DATA: dict = load_learning_performance(
    _MATH_DATA_DIR,
    subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES,
)
_CC_DATA: dict = load_core_competencies(_MATH_DATA_DIR / "core_competencies.json")

_CONTENT_TYPE_VALUES: list[str] = ["純文字", "含圖片", "graphs/charts/tables", "customized"]
_RANDOM_CONTENT_TYPE_VALUES: list[str] = [v for v in _CONTENT_TYPE_VALUES if v != "customized"]


def grade_to_learning_stage(grade: int) -> str:
    """Map a K-12 grade (1-12) to its 108課綱 學習階段 string."""
    if 1 <= grade <= 2:
        return "第一學習階段"
    if 3 <= grade <= 4:
        return "第二學習階段"
    if 5 <= grade <= 6:
        return "第三學習階段"
    if 7 <= grade <= 9:
        return "第四學習階段"
    if 10 <= grade <= 12:
        return "第五學習階段"
    raise ValueError(f"grade {grade} not in 1-12")


def sample_params(
    grade_content: dict[int, list[LearningContentItem]] | None = None,
    grade: int | None = None,
    style: list[QuestionStyle] | None = None,  # type: ignore[valid-type]
    context: list[QuestionContext] | None = None,  # type: ignore[valid-type]
    set_type: QuestionSetType | None = None,  # type: ignore[valid-type]
    q_type: list[QuestionType] | None = None,  # type: ignore[valid-type]
    seed: int | None = None,
    *,
    math_thinking: list[MathThinking] | None = None,  # type: ignore[valid-type]
    core_competency: list[CoreCompetency] | None = None,  # type: ignore[valid-type]
    learning_content: list[str] | None = None,
    learning_performance: list[str] | None = None,
    content_type: str | None = None,
    subject_filter: str | None = None,
    sub_question_count: int | None = None,
    text_word_limit: int | None = None,
    difficulty: Difficulty | str | None = None,
    redraws: dict[str, int] | None = None,
) -> SampledParams:
    """Sample random question parameters.

    Curriculum-aware (Phase 3): 學習內容 / 學習表現 / 核心素養 are sampled from
    the materialized data/math/curriculum/ files, optionally filtered by 科目.
    `grade_content` is accepted but unused — kept for backward-compat with
    older callers.
    """
    del grade_content  # legacy; curriculum data now loaded directly

    redraws = redraws or {}

    def field_rng(field_path: str):
        return draw_rng(seed, field_path, redraws.get(field_path, 0))

    resolved_difficulty: Difficulty = resolve_difficulty(difficulty)

    # Grade
    selected_grade = grade if grade is not None else field_rng("grade").choice(_GRADES)
    learning_stage = grade_to_learning_stage(selected_grade)

    # 情境
    all_contexts = list(QuestionContext)
    if context is not None:
        selected_context = context
    else:
        context_rng = field_rng("情境")
        context_count = context_rng.randint(1, len(all_contexts))
        selected_context = context_rng.sample(all_contexts, context_count)

    # 題型種類
    selected_set_type = (
        set_type
        if set_type is not None
        else (
            QuestionSetType("題組題")
            if sub_question_count is not None
            else field_rng("題型種類").choice(list(QuestionSetType))
        )
    )
    if selected_set_type == QuestionSetType("題組題") and sub_question_count is None:
        sub_question_count = field_rng("sub_question_count").randint(3, 7)

    # 題型
    selected_q_type = (
        field_rng("題型").choice(q_type)
        if q_type is not None
        else field_rng("題型").choice(list(QuestionType))
    )

    # 數學思考 (1-3 items)
    if math_thinking is not None:
        selected_thinking = math_thinking
    else:
        all_thinking = list(MathThinking)
        thinking_rng = field_rng("數學思考")
        thinking_count = thinking_rng.randint(1, 3)
        selected_thinking = thinking_rng.sample(
            all_thinking, min(thinking_count, len(all_thinking))
        )

    # 學習內容 — pull from curriculum data filtered by stage + 科目.
    lc_entries = allowed_learning_content(
        _LC_DATA,
        learning_stage,
        subject=subject_filter,
        subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES,
    )
    if learning_content is not None:
        selected_lc_codes = list(learning_content)
    else:
        if not lc_entries:
            raise ValueError(
                f"No 學習內容 entries for stage={learning_stage} subject={subject_filter}"
            )
        lc_rng = field_rng("學習內容")
        lc_count = lc_rng.randint(1, min(3, len(lc_entries)))
        selected_lc_codes = [e["value"] for e in lc_rng.sample(lc_entries, lc_count)]

    lc_by_code = {e["value"]: e for e in _LC_DATA["學習內容"]}
    selected_content = [
        LearningContentItem(編碼=code, 說明=lc_by_code.get(code, {}).get("條目說明", ""))
        for code in selected_lc_codes
    ]

    # 學習表現 — same pattern.
    lp_entries = allowed_learning_performance(
        _LP_DATA,
        learning_stage,
        subject=subject_filter,
        subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES,
    )
    if learning_performance is not None:
        selected_lp_codes = list(learning_performance)
    else:
        if lp_entries:
            lp_rng = field_rng("學習表現")
            lp_count = lp_rng.randint(1, min(3, len(lp_entries)))
            selected_lp_codes = [e["value"] for e in lp_rng.sample(lp_entries, lp_count)]
        else:
            selected_lp_codes = []
    lp_by_code = {e["value"]: e for e in _LP_DATA["學習表現"]}
    selected_performance = [
        LearningContentItem(編碼=code, 說明=lp_by_code.get(code, {}).get("說明", ""))
        for code in selected_lp_codes
    ]

    # 核心素養 — 1-3 codes for this learning stage.
    if core_competency is not None:
        selected_competency_values = [
            c.value if hasattr(c, "value") else str(c) for c in core_competency
        ]
    else:
        cc_pool = allowed_competencies(_CC_DATA, learning_stage)
        if cc_pool:
            competency_rng = field_rng("核心素養")
            cc_count = competency_rng.randint(1, min(3, len(cc_pool)))
            selected_competency_values = competency_rng.sample(cc_pool, cc_count)
        else:
            selected_competency_values = []

    # 題目內容類型
    if content_type and content_type.strip():
        selected_content_type = content_type.strip()
    else:
        selected_content_type = field_rng("題目內容類型").choice(_RANDOM_CONTENT_TYPE_VALUES)

    # Question style
    selected_style = (
        field_rng("style").choice(style)
        if style is not None
        else field_rng("style").choice(list(QuestionStyle))
    )

    return SampledParams(
        grade=selected_grade,
        seed=seed,
        情境=selected_context,
        題型種類=selected_set_type,
        題型=selected_q_type,
        數學思考=selected_thinking,
        學習內容=selected_content,
        style=selected_style,
        核心素養=selected_competency_values,
        學習表現=selected_performance,
        題目內容類型=selected_content_type,
        subject_filter=subject_filter,
        sub_question_count=sub_question_count,
        text_word_limit=text_word_limit,
        difficulty=resolved_difficulty,
    )
