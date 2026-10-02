"""CLI entry point for PISA Science + 108課綱自然科學 generation."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import random
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.common.batch_dedup import PriorScope, extract_ns_prior_scope
from src.common.cli_resolver import resolve_and_print
from src.common.figure_policy import (
    build_figure_consistency_entries,
    effective_figure_kind,
    enforce_figure_data_consistency,
    find_figure_kind_collisions,
    normalize_figure_kind,
)
from src.common.figure_policy_trail import (
    make_collision_entry,
    make_data_inconsistency_entry,
    make_repair_entry,
    make_spec_entry,
    make_warning_entry,
)
from src.common.generation_core import (
    SubquestionParseError,
    _call_with_optional_scope,
    _scoped_callback,
    generate_one_core,
    generate_with_corrections_core,
)
from src.common.generation_events import OperationScope, new_operation_scope
from src.common.image_spec_parsing import image_spec_failure_reason, parse_image_spec
from src.common.subject_spec import NATURAL_SCIENCES, SubjectGenerationSpec
from src.common.subquestion_contract import normalize_rubric_student_examples
from src.common.subquestion_forcing import force_grade
from src.common.verification_trail import VerificationTrailEntry
from src.config import Config
from src.curriculum_context import CurriculumContext, load_curriculum_context
from src.html_renderer import PlaywrightRenderer
from src.llm_client import LLMClient, emit_stage, make_render_error_sink, make_stderr_observer
from src.natural_sciences.context_builder import (
    LC_INSTRUCTIONS,
    LP_INSTRUCTIONS,
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
    curriculum_texts,
)
from src.natural_sciences.corrector import correct_question
from src.natural_sciences.curriculum_codes import repair_lc_refs, repair_lp_refs
from src.natural_sciences.curriculum_loader import grade_to_learning_stage
from src.natural_sciences.schema_loader import load_grades, load_schemas
from src.natural_sciences.schemas import (
    ExamQuestion,
    ImageSpec,
    LearningContentRef,
    QuestionContext,
    QuestionMetadata,
    QuestionSetType,
    QuestionSubContext,
    QuestionType,
    RubricEntry,
    SampledParams,
    ScienceCompetency,
    SubQuestion,
    SubQuestionConfig,
)
from src.natural_sciences.verifier import verify_question
from src.renderer import render_image
from src.social_studies.figure_kind_loader import CANONICAL_FIGURE_KINDS

logger = logging.getLogger(__name__)

_GRADES: list[int] = load_grades(load_schemas())
_VISUAL_CONTENT_TYPES = {"含圖片", "graphs/charts/tables"}

QuestionUpdateCallback = Callable[[ExamQuestion, str], None]
VerificationTrailCallback = Callable[[VerificationTrailEntry], None]
FigurePolicyTrailCallback = Callable[..., None]

_NS_SUBQUESTION_IMAGE_REPAIR_SYSTEM_PROMPT = """\
你是一位108課綱自然科學素養導向題組的視覺素材設計教師。
請只根據既有小題內容，補上一個該小題專用的視覺素材圖片規格。

規則：
- 只輸出合法 JSON 物件，不要輸出其他文字。
- JSON 必須包含 `chart_spec` 欄位。
- `chart_spec` 必須是此小題專用的視覺素材，不是整個題組共用圖片。
- 若是統計圖，使用 `render_mode: "chart"` 並提供 `chart_type`、`data`、`labels`。
- 若是圖片式素材、表格、流程圖或圖解，使用 `render_mode: "html"`。
- 每個非 null 的 `chart_spec` 都必須宣告具體的 `figure_kind`；它是自由文字欄位，
  適用時可從 canonical vocabulary 選擇，未知類型仍可使用具體名稱。
- 不要加入答案提示。
"""

_NS_SUBQUESTION_IMAGE_REPAIR_USER_TEMPLATE = """\
以下小題的題目內容類型是「{content_type}」，但缺少小題 chart_spec。
請為此小題補上 `chart_spec`。

{figure_kind_instruction}

題組文本：
{text}

小題：
```json
{sq_json}
```
"""

_NS_TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT = """\
你是一位108課綱自然科學素養導向題組的視覺素材設計教師。
請只根據既有題組內容，補上一個整個題組共用的主要素材圖片規格。

規則：
- 只輸出合法 JSON 物件，不要輸出其他文字。
- JSON 必須包含 `chart_spec` 欄位。
- `chart_spec` 必須是整個題組共用的視覺素材，不是單一小題專用圖片。
- 每個非 null 的 `chart_spec` 都必須宣告具體的 `figure_kind`；它是自由文字欄位，
  適用時可從 canonical vocabulary 選擇，未知類型仍可使用具體名稱。
- 不要加入答案提示。
"""

_NS_TOP_LEVEL_IMAGE_REPAIR_USER_TEMPLATE = """\
以下自然科學題組的全域文本素材類型是「{content_type}」，但缺少題組頂層 chart_spec。
請為整個題組共用的主要素材補上 `chart_spec`。

{figure_kind_instruction}

```json
{question_json}
```
"""

_NS_FIGURE_KIND_DECLARATION_REPAIR_SYSTEM_PROMPT = """\
你是一位108課綱自然科學領域的視覺素材修補教師。
請只補上既有視覺素材規格缺少的圖像種類宣告，不要改變素材內容或渲染方式。

規則：
- 只輸出合法 JSON 物件，不要輸出其他文字。
- JSON 必須包含 `chart_spec`；保留原有的 render_mode、chart_type、data、labels、
  title、description 與 html。
- 每個非 null 的 `chart_spec` 都必須宣告 `figure_kind`。
- `figure_kind` 是自由文字欄位；適用時從 canonical vocabulary 選擇，未知類型仍可使用具體名稱。
"""

_NS_FIGURE_KIND_DECLARATION_REPAIR_USER_TEMPLATE = """\
以下是{label}目前的視覺素材規格；它尚未宣告 `figure_kind`。

{figure_kind_instruction}

```json
{spec_json}
```
請只回傳包含 `chart_spec.figure_kind` 的 JSON。
"""


def _emit_question_update(
    callback: QuestionUpdateCallback | None,
    question: ExamQuestion,
    phase: str,
) -> None:
    if callback is None:
        return
    callback(question, phase)


def _with_text_word_limit(
    params: SampledParams,
    text_word_limit: int | None,
) -> SampledParams:
    if text_word_limit is None:
        return params
    return params.model_copy(update={"text_word_limit": text_word_limit})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="natural-sciences-exam-generation",
        description="Generate PISA Science + Taiwan natural-sciences exam questions",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate exam questions")
    gen.add_argument("--grade", type=int, choices=_GRADES, help="Target grade level")
    gen.add_argument("--context", type=str, nargs="+", choices=[c.value for c in QuestionContext])
    gen.add_argument("--sub-context", type=str, choices=[c.value for c in QuestionSubContext])
    gen.add_argument("--set-type", type=str, choices=[s.value for s in QuestionSetType])
    gen.add_argument("--q-type", type=str, nargs="+", choices=[q.value for q in QuestionType])
    gen.add_argument(
        "--science-competency",
        type=str,
        nargs="+",
        choices=[c.value for c in ScienceCompetency],
        help="PISA Science / Environmental Science competency pool",
    )
    gen.add_argument("--learning-content", type=str, nargs="+", help="指定學習內容 編碼")
    gen.add_argument("--learning-performance", type=str, nargs="+", help="指定學習表現 編碼")
    gen.add_argument("--content-type", type=str, help="題目內容類型")
    from src.natural_sciences.reporting_scale import REPORTING_SCALE_ORDER as _RS_ORDER
    gen.add_argument(
        "--reporting-scale",
        type=str,
        choices=list(_RS_ORDER),
        default=None,
        help="目標 PISA Science Reporting Scale 等級（取代舊有 --difficulty，自然科學專用）",
    )
    gen.add_argument("--count", type=int, default=1, help="Number of question sets to generate")
    gen.add_argument("--batch", action="store_true", help="Output as single JSON array")
    gen.add_argument("--seed", type=int, help="Random seed for reproducibility")
    gen.add_argument(
        "--no-core-question-callback",
        dest="core_question_callback",
        action="store_false",
        default=True,
        help="關閉最後小題回扣本題組核心問題的提示",
    )
    gen.add_argument("--no-verify", action="store_true", help="Skip verification pass")
    gen.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Max retries when verification fails (default: LLM_MAX_RETRIES env, fallback 3)",
    )
    gen.add_argument(
        "--image-generation-mode",
        choices=["html", "gpt_image"],
        default="html",
        help="Image creation mode for HTML image specs",
    )
    gen.add_argument("--output", type=str, help="Output directory")
    gen.add_argument("--dry-run", action="store_true", help="Show prompt without calling LLM")
    gen.add_argument("--env-file", type=str, help="Path to .env file")
    gen.add_argument(
        "--text-instruction",
        type=str,
        default=None,
        help="文本出題指示：傳給每個題組的文本生成器，作為建議值指引取材與出題方向",
    )

    res = sub.add_parser("resolve", help="Resolve and print generation parameters")
    res.add_argument("--grade", type=int, choices=_GRADES, help="Target grade level")
    res.add_argument(
        "--context",
        type=str,
        nargs="+",
        choices=[c.value for c in QuestionContext],
        help="情境",
    )
    res.add_argument(
        "--sub-context",
        type=str,
        choices=[c.value for c in QuestionSubContext],
        help="情境子類別",
    )
    res.add_argument(
        "--set-type",
        type=str,
        choices=[s.value for s in QuestionSetType],
        help="題型種類",
    )
    res.add_argument(
        "--q-type",
        type=str,
        nargs="+",
        choices=[q.value for q in QuestionType],
        help="題型",
    )
    res.add_argument(
        "--science-competency",
        type=str,
        nargs="+",
        choices=[c.value for c in ScienceCompetency],
        help="科學能力 pool",
    )
    res.add_argument("--learning-content", type=str, nargs="+", help="學習內容 編碼")
    res.add_argument("--learning-performance", type=str, nargs="+", help="學習表現 編碼")
    res.add_argument("--content-type", type=str, help="題目內容類型")
    from src.natural_sciences.reporting_scale import REPORTING_SCALE_ORDER as _RS_RESOLVE_ORDER
    res.add_argument(
        "--reporting-scale",
        type=str,
        choices=list(_RS_RESOLVE_ORDER),
        default=None,
        help="目標 PISA Science Reporting Scale 等級",
    )
    res.add_argument("--count", type=int, default=1, help="Number of payloads to resolve")
    res.add_argument("--seed", type=int, help="Random seed for reproducibility")

    return parser.parse_args(argv)


def _ns_partial_payload(args: argparse.Namespace, seed: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"subject": "natural_sciences"}
    if seed is not None:
        payload["seed"] = seed
    fields = {
        "grade": args.grade,
        "context": args.context,
        "sub_context": args.sub_context,
        "set_type": args.set_type,
        "q_type": args.q_type,
        "science_competency": args.science_competency,
        "learning_content": args.learning_content,
        "learning_performance": args.learning_performance,
        "content_type": args.content_type,
        "reporting_scale": args.reporting_scale,
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    return payload


def _ns_params_from_resolved(payload: dict[str, Any]) -> SampledParams:
    raw_configs = payload.get("subquestion_configs") or []
    if isinstance(raw_configs, str):
        raw_configs = json.loads(raw_configs)
    if not isinstance(raw_configs, list):
        raise ValueError("resolved subquestion_configs must be a list")
    configs = [SubQuestionConfig.model_validate(item) for item in raw_configs]

    question_type = next(
        (
            config.question_type
            for config in configs
            if config.question_type is not None
        ),
        None,
    )
    if question_type is None:
        q_type_values = payload.get("q_type") or []
        if not q_type_values:
            raise ValueError("resolved natural-sciences payload has no question type")
        question_type = QuestionType(q_type_values[0])

    # Difficulty is a shared request field; natural sciences uses Reporting
    # Scale instead, so the resolved value is intentionally ignored here.
    _ = payload.get("difficulty")

    return SampledParams(
        grade=payload["grade"],
        seed=payload.get("seed"),
        情境=[QuestionContext(value) for value in payload["context"]],
        情境子類別=QuestionSubContext(payload["sub_context"]),
        題型種類=QuestionSetType(payload["set_type"]),
        題型=question_type,
        科學能力=[
            ScienceCompetency(value) for value in payload["science_competency"]
        ],
        題目內容類型=payload["content_type"],
        學習內容_pool=list(payload["learning_content"]),
        學習表現_pool=list(payload["learning_performance"]),
        sub_question_count=payload.get("sub_question_count") or len(configs) or None,
        question_word_limit=payload.get("question_word_limit"),
        option_word_limit=payload.get("option_word_limit"),
        text_word_limit=payload.get("text_word_limit"),
        subquestion_configs=configs,
        reporting_scale=payload.get("reporting_scale"),
        allow_duplicate_figure_kinds=payload.get("allow_duplicate_figure_kinds", False),
    )


def _resolve_enum(value: str | None, enum_cls: type) -> object | None:
    if value is None:
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    raise ValueError(f"Invalid value '{value}' for {enum_cls.__name__}")


def _parse_subquestion(
    sq_raw: dict,
    question_id: str,
    params: SampledParams,
    i: int,
) -> SubQuestion:
    if not isinstance(sq_raw, dict):
        raise SubquestionParseError("子題回應不是 JSON 物件")
    try:
        cfg = (
            params.subquestion_configs[i - 1]
            if 1 <= i <= len(params.subquestion_configs) else None
        )
        lc_refs = [
            LearningContentRef(編碼=r.get("編碼", ""), 說明=r.get("說明", ""))
            for r in sq_raw.get("學習內容", [])
            if isinstance(r, dict) and r.get("編碼")
        ]
        lp_refs = [
            LearningContentRef(編碼=r.get("編碼", ""), 說明=r.get("說明", ""))
            for r in sq_raw.get("學習表現", [])
            if isinstance(r, dict) and r.get("編碼")
        ]
        learning_stage = grade_to_learning_stage(params.grade)
        if cfg and cfg.learning_content:
            lc_refs = [
                LearningContentRef(編碼=code, 說明=LC_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_content
            ]
        else:
            # Issue #92: canonicalize LLM-emitted codes; unknown codes are
            # dropped and an empty result falls back to the sampled pool.
            # Issue #287: off-stage codes are also dropped and fall back.
            lc_refs = repair_lc_refs(lc_refs, params.學習內容_pool, learning_stage=learning_stage)
        if cfg and cfg.learning_performance:
            lp_refs = [
                LearningContentRef(編碼=code, 說明=LP_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_performance
            ]
        else:
            lp_refs = repair_lp_refs(lp_refs, params.學習表現_pool, learning_stage=learning_stage)
        rubric_rows = normalize_rubric_student_examples([
            r
            for r in (sq_raw.get("評分規準") or sq_raw.get("評分標準") or [])
            if isinstance(r, dict)
        ])
        rubric = [
            RubricEntry(
                code=str(r.get("code", "")),
                規準說明=r.get("規準說明", ""),
                學生作答實例=r.get("學生作答實例", []),
            )
            for r in rubric_rows
        ]
        raw_distractor = sq_raw.get("誘答分析", {})
        if isinstance(raw_distractor, dict):
            distractor = {str(k): str(v) for k, v in raw_distractor.items()}
        else:
            distractor = {}
        primary_spec = sq_raw.get("image_spec")
        fallback_spec = sq_raw.get("chart_spec")
        raw_sq_spec = primary_spec or fallback_spec
        if raw_sq_spec is None:
            raw_sq_spec = primary_spec
        sq_chart_spec = (
            parse_image_spec(raw_sq_spec, ImageSpec)
            if raw_sq_spec is not None
            else None
        )
        raw_question_type = sq_raw.get("題型", params.題型.value)
        if raw_question_type not in tuple(member.value for member in QuestionType):
            raise SubquestionParseError("題型欄位不是可辨識的題型")
        題目 = sq_raw.get("題目", "")
        if not isinstance(題目, str) or not 題目.strip():
            raise SubquestionParseError("子題缺少必要的「題目」文字（空白或遺漏）")
        result = SubQuestion(
            id=sq_raw.get("id", f"{question_id}-{sq_raw.get('序號', i):02d}"),
            序號=sq_raw.get("序號", i),
            年級=sq_raw.get("年級", params.grade),
            科目=sq_raw.get("科目", ["自然科學"]),
            科學能力=sq_raw.get("科學能力", [c.value for c in params.科學能力]),
            核心素養=sq_raw.get("核心素養", []),
            學習內容=lc_refs,
            學習表現=lp_refs,
            出題概念=sq_raw.get("出題概念", ""),
            reporting_scale=sq_raw.get("reporting_scale") or (cfg.reporting_scale if cfg else None),
            題型=raw_question_type,
            題目=題目,
            答案=sq_raw.get("答案", ""),
            答案解析=sq_raw.get("答案解析", ""),
            評分規準=rubric,
            誘答分析=distractor,
            題目內容類型=sq_raw.get("題目內容類型"),
            image_generation_mode=sq_raw.get("image_generation_mode"),
            圖片=sq_raw.get("圖片"),
            chart_spec=sq_chart_spec,
        )
        result.科目 = ["自然科學"]
        result.科學能力 = [competency.value for competency in params.科學能力]
        # Issue #286: force 年級 from sampled params, never trust the LLM value.
        # The prompt's own JSON example hard-codes 年級=8, causing junior-high
        # values to leak into senior-high requests.  科目 is already forced
        # above; 年級 gets the same treatment via the shared helper so that
        # 社會領域 (issue #290) can reuse it later.
        force_grade(result, params.grade)
        if cfg and cfg.figure_kind and result.chart_spec:
            result.chart_spec = result.chart_spec.model_copy(
                update={"figure_kind": cfg.figure_kind.strip()}
            )
        result._plan_index = i
        if raw_sq_spec is not None and sq_chart_spec is None:
            logger.warning(
                "Discarded natural-sciences subquestion visual specification: "
                "question_id=%s slot=%d reason=%s",
                question_id,
                i,
                image_spec_failure_reason(raw_sq_spec),
            )
        return result
    except SubquestionParseError:
        raise
    except ValidationError as exc:
        raise SubquestionParseError.from_validation(exc) from None


def _parse_text_shell(
    raw: dict,
    question_id: str,
    params: SampledParams,
    model: str,
) -> ExamQuestion:
    """Parse text-generator JSON output into an ExamQuestion without subquestions."""
    raw_spec = raw.get("image_spec") or raw.get("chart_spec")
    chart_spec = parse_image_spec(raw_spec, ImageSpec) if raw_spec else None

    return ExamQuestion(
        id=question_id,
        核心問題=raw.get("核心問題", ""),
        文本=raw.get("文本", ""),
        取材來源=raw.get("取材來源", []),
        subquestions=[],
        情境=[c.value for c in params.情境],
        情境子類別=params.情境子類別.value,
        題型種類=params.題型種類.value,
        題型=params.題型.value,
        科學能力=[c.value for c in params.科學能力],
        題目內容類型=params.題目內容類型,
        題目=raw.get("題目", []),
        正確解題分析=raw.get("正確解題分析", []),
        chart_spec=chart_spec,
        metadata=QuestionMetadata(
            grade=params.grade,
            model=model,
            seed=None,
        ),
    )


def _ns_build_text_system(params: SampledParams) -> tuple[str, dict]:
    learning_stage = grade_to_learning_stage(params.grade)
    content_text, performance_text = curriculum_texts(learning_stage, params.學習內容_pool)
    system = build_text_system_prompt(
        learning_stage=learning_stage,
        content_text=content_text,
        performance_text=performance_text,
    )
    return system, {
        "learning_stage": learning_stage,
        "content_text": content_text,
        "performance_text": performance_text,
    }


def _ns_build_text_user(
    params, few_shot_dir,
    user_passage, user_options, user_topic, user_core_question, text_instruction,
    image_generation_mode, disable_reference_fewshot, prior_scopes,
    core_question_callback,
    balanced_batch: bool = False,
):
    return build_text_user_prompt(
        params,
        few_shot_dir,
        rng=random.Random(params.seed),
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        text_instruction=text_instruction,
        image_generation_mode=image_generation_mode,
        disable_reference_fewshot=disable_reference_fewshot,
        prior_scopes=prior_scopes,
        core_question_callback=core_question_callback,
        balanced_batch=balanced_batch,
    )


def _ns_build_subquestion_system(stage_ctx: dict) -> str:
    return build_subquestion_system_prompt(
        learning_stage=stage_ctx["learning_stage"],
        content_text=stage_ctx["content_text"],
        performance_text=stage_ctx["performance_text"],
    )


def _ns_build_subquestion_user(
    text_raw, params, few_shot_dir, sq_plan, slot_cfg,
    image_generation_mode, disable_reference_fewshot,
    core_question_callback, is_last,
):
    return build_subquestion_user_prompt(
        核心問題=text_raw.get("核心問題", ""),
        文本=text_raw.get("文本", ""),
        取材來源=text_raw.get("取材來源", []),
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=few_shot_dir,
        image_generation_mode=image_generation_mode,
        cfg=slot_cfg,
        disable_reference_fewshot=disable_reference_fewshot,
        core_question_callback=core_question_callback,
        is_last=is_last,
    )


def _ns_make_fallback_sq_plans(params: SampledParams, n: int) -> list[dict]:
    return [
        {"序號": i, "題型": params.題型.value, "出題概念": ""}
        for i in range(1, n + 1)
    ]


def _parse_subquestion_image_spec(raw_spec: object) -> ImageSpec | None:
    return parse_image_spec(raw_spec, ImageSpec)


def _ns_subquestion_config_for(
    params: SampledParams,
    sub: SubQuestion,
) -> SubQuestionConfig | None:
    plan_index = sub._plan_index if sub._plan_index is not None else sub.序號
    if plan_index < 1 or plan_index > len(params.subquestion_configs):
        return None
    return params.subquestion_configs[plan_index - 1]


def _ns_figure_kind_repair_instruction(
    params: SampledParams | None,
    forbidden_kinds: list[str] | None = None,
    required_kind: str | None = None,
    allow_duplicates: bool | None = None,
) -> str:
    vocabulary = "、".join(CANONICAL_FIGURE_KINDS)
    lines = [
        "- **圖像種類宣告**：每個非 null 的 `chart_spec` 都必須宣告 `figure_kind`；",
        "  它是自由文字欄位，未知類型仍可使用具體名稱。",
        "- 適用時請從 canonical vocabulary 選擇：" + vocabulary + "。",
    ]
    if required_kind and required_kind.strip():
        lines.append(f"- 本小題的 `figure_kind` 是強制值：`{required_kind.strip()}`。")
    duplicate_allowed = (
        getattr(params, "allow_duplicate_figure_kinds", False)
        if allow_duplicates is None
        else allow_duplicates
    )
    if duplicate_allowed:
        lines.append("- 本請求允許圖像種類重複；不需套用不得重複限制。")
    elif forbidden_kinds:
        unique_kinds = list(
            dict.fromkeys(
                normalize_figure_kind(kind)
                for kind in forbidden_kinds
                if isinstance(kind, str) and kind.strip()
            )
        )
        if unique_kinds:
            lines.append("- **圖像種類不得為：**" + "、".join(unique_kinds))
    else:
        lines.append(
            "- 預設每張圖（含題幹與所有小題）的圖像種類不得重複；"
            "不同 render_mode 的同一具體種類仍視為重複。"
        )
    return "\n".join(lines)


def _ns_declared_figure_kind(spec: ImageSpec | None) -> str:
    if spec is None or not isinstance(spec.figure_kind, str):
        return ""
    return spec.figure_kind.strip()


def _ns_canonicalize_repaired_figure_kind(value: str) -> str:
    stripped = value.strip()
    normalized = normalize_figure_kind(stripped)
    return normalized if normalized in CANONICAL_FIGURE_KINDS else stripped


def _ns_figure_kind_repair_key(sub: SubQuestion) -> str:
    if sub._plan_index is not None:
        return f"小題 plan {sub._plan_index}"
    return f"小題 object {id(sub)}"


def _ns_repair_figure_kind_declaration(
    *,
    question: ExamQuestion,
    label: str,
    spec: ImageSpec,
    params: SampledParams,
    client: Any,
    set_spec: Callable[[ImageSpec], None],
    on_figure_policy_entry: FigurePolicyTrailCallback | None,
    forbidden_kinds: list[str] | None = None,
    scope: OperationScope | None = None,
) -> None:
    before_kind = effective_figure_kind(spec)
    after_kind = before_kind
    succeeded = False
    repair_error: str | None = None
    try:
        response = _call_with_optional_scope(
            client.generate_json,
            _NS_FIGURE_KIND_DECLARATION_REPAIR_SYSTEM_PROMPT,
            _NS_FIGURE_KIND_DECLARATION_REPAIR_USER_TEMPLATE.format(
                label=label,
                figure_kind_instruction=_ns_figure_kind_repair_instruction(
                    params,
                    forbidden_kinds=forbidden_kinds,
                ),
                spec_json=spec.model_dump_json(exclude_none=True),
            ),
            purpose="generate",
            scope=scope,
        )
        raw_spec = response.get("chart_spec") or response.get("image_spec")
        raw_kind = (
            raw_spec.get("figure_kind")
            if isinstance(raw_spec, dict)
            else response.get("figure_kind")
        )
        if isinstance(raw_kind, str) and raw_kind.strip():
            repaired_spec = spec.model_copy(
                update={"figure_kind": _ns_canonicalize_repaired_figure_kind(raw_kind)}
            )
            set_spec(repaired_spec)
            after_kind = effective_figure_kind(repaired_spec)
            succeeded = bool(_ns_declared_figure_kind(repaired_spec))
    except Exception as exc:
        repair_error = str(exc)

    if on_figure_policy_entry is not None:
        on_figure_policy_entry(
            make_repair_entry(
                question.id,
                label,
                before_kind,
                after_kind,
                [
                    normalize_figure_kind(kind)
                    for kind in (forbidden_kinds or [])
                    if isinstance(kind, str) and kind.strip()
                ],
                succeeded,
                repair_error,
            )
        )


def _ns_force_subquestion_figure_kind(
    sub: SubQuestion,
    figure_kind: str | None,
) -> None:
    if not sub.chart_spec or not isinstance(figure_kind, str) or not figure_kind.strip():
        return
    sub.chart_spec = sub.chart_spec.model_copy(update={"figure_kind": figure_kind.strip()})


def _ns_ensure_subquestion_visual_spec(
    sub: SubQuestion,
    question: ExamQuestion,
    content_type: str,
    client: Any,
    *,
    figure_kind: str | None = None,
    forbidden_kinds: list[str] | None = None,
    force_repair: bool = False,
    allow_duplicates: bool = False,
    scope: OperationScope | None = None,
) -> None:
    """Repair a missing chart_spec for one NS 小題 configured as visual."""
    _ns_force_subquestion_figure_kind(sub, figure_kind)
    if (
        (sub.chart_spec and not force_repair)
        or (
            content_type not in _VISUAL_CONTENT_TYPES
            and not figure_kind
            and not force_repair
        )
        or client is None
    ):
        return

    sq_json = sub.model_dump_json(
        exclude_none=True,
        exclude={"圖片", "答案", "答案解析", "評分規準", "誘答分析"},
    )
    user_prompt = _NS_SUBQUESTION_IMAGE_REPAIR_USER_TEMPLATE.format(
        content_type=content_type,
        figure_kind_instruction=_ns_figure_kind_repair_instruction(
            None,
            forbidden_kinds=forbidden_kinds,
            required_kind=figure_kind,
            allow_duplicates=allow_duplicates,
        ),
        text=question.文本,
        sq_json=sq_json,
    )

    try:
        repaired = _call_with_optional_scope(
            client.generate_json,
            _NS_SUBQUESTION_IMAGE_REPAIR_SYSTEM_PROMPT,
            user_prompt,
            purpose="generate",
            scope=scope,
        )
    except Exception as exc:
        print(
            f"  Warning: NS subquestion image spec repair failed for 小題 {sub.序號}: {exc}",
            file=sys.stderr,
        )
        return

    if not isinstance(repaired, dict):
        return
    raw_spec = repaired.get("image_spec") or repaired.get("chart_spec")
    image_spec = _parse_subquestion_image_spec(raw_spec)
    if image_spec:
        _ns_force_subquestion_figure_kind(sub, figure_kind)
        if figure_kind and figure_kind.strip():
            image_spec = image_spec.model_copy(update={"figure_kind": figure_kind.strip()})
        sub.chart_spec = image_spec


def _ns_ensure_top_level_visual_spec(
    question: ExamQuestion,
    params: SampledParams,
    client: Any,
    *,
    forbidden_kinds: list[str] | None = None,
    force_repair: bool = False,
    scope: OperationScope | None = None,
) -> None:
    if (
        (question.chart_spec and not force_repair)
        or (params.題目內容類型 not in _VISUAL_CONTENT_TYPES and not force_repair)
        or client is None
    ):
        return

    try:
        repaired = _call_with_optional_scope(
            client.generate_json,
            _NS_TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT,
            _NS_TOP_LEVEL_IMAGE_REPAIR_USER_TEMPLATE.format(
                content_type=params.題目內容類型,
                figure_kind_instruction=_ns_figure_kind_repair_instruction(
                    params,
                    forbidden_kinds=forbidden_kinds,
                ),
                question_json=question.model_dump_json(
                    exclude_none=True,
                    exclude={"verification", "圖片"},
                ),
            ),
            purpose="generate",
            scope=scope,
        )
    except Exception as exc:
        print(f"  Warning: NS top-level image spec repair failed: {exc}", file=sys.stderr)
        return

    if not isinstance(repaired, dict):
        return
    raw_spec = repaired.get("image_spec") or repaired.get("chart_spec")
    image_spec = _parse_subquestion_image_spec(raw_spec)
    if image_spec:
        question.chart_spec = image_spec


def _ns_known_figure_kinds_for_subquestion_repair(
    question: ExamQuestion,
    params: SampledParams,
    sub: SubQuestion,
) -> list[str]:
    known: list[str] = []
    if question.chart_spec is not None:
        kind = effective_figure_kind(question.chart_spec)
        if kind:
            known.append(kind)
    for other in question.subquestions:
        if other is sub or other.chart_spec is None:
            continue
        kind = effective_figure_kind(other.chart_spec)
        if kind:
            known.append(kind)
    current_plan_index = sub._plan_index
    for index, cfg in enumerate(params.subquestion_configs, start=1):
        if index != current_plan_index and cfg.figure_kind:
            known.append(cfg.figure_kind)
    return list(dict.fromkeys(known))


def _ns_ensure_visual_spec(
    question: ExamQuestion,
    params: SampledParams,
    client: Any,
    *,
    scope: OperationScope | None = None,
) -> None:
    """Repair missing NS visual specs before the rendering stage."""
    _ns_ensure_top_level_visual_spec(question, params, client, scope=scope)
    for sub in question.subquestions:
        cfg = _ns_subquestion_config_for(params, sub)
        if cfg is None or (
            cfg.content_type not in _VISUAL_CONTENT_TYPES and not cfg.figure_kind
        ):
            continue
        if sub.chart_spec is None and client is not None:
            question._figure_kind_repair_attempted.add(_ns_figure_kind_repair_key(sub))
        _ns_ensure_subquestion_visual_spec(
            sub,
            question,
            cfg.content_type or "",
            client,
            figure_kind=cfg.figure_kind,
            forbidden_kinds=_ns_known_figure_kinds_for_subquestion_repair(
                question, params, sub
            ),
            allow_duplicates=params.allow_duplicate_figure_kinds,
            scope=scope,
        )


def _ns_prepare_visual_policy(
    question: ExamQuestion,
    params: SampledParams,
    client: Any,
    *,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
    scope: OperationScope | None = None,
) -> None:
    """Declare every existing NS visual spec before the shared renderer."""
    if client is None:
        return
    on_figure_policy_entry = _scoped_callback(on_figure_policy_entry, scope)

    attempted = question._figure_kind_repair_attempted
    if question.chart_spec is not None and not _ns_declared_figure_kind(question.chart_spec):
        if "題幹" not in attempted:
            attempted.add("題幹")
            _ns_repair_figure_kind_declaration(
                question=question,
                label="題幹",
                spec=question.chart_spec,
                params=params,
                client=client,
                set_spec=lambda repaired: setattr(question, "chart_spec", repaired),
                on_figure_policy_entry=on_figure_policy_entry,
                scope=scope,
            )

    for sub in question.subquestions:
        if sub.chart_spec is None or _ns_declared_figure_kind(sub.chart_spec):
            continue
        attempt_key = _ns_figure_kind_repair_key(sub)
        if attempt_key in attempted:
            continue
        attempted.add(attempt_key)
        _ns_repair_figure_kind_declaration(
            question=question,
            label=f"小題 {sub.序號}",
            spec=sub.chart_spec,
            params=params,
            client=client,
            set_spec=lambda repaired, sub=sub: setattr(sub, "chart_spec", repaired),
            on_figure_policy_entry=on_figure_policy_entry,
            forbidden_kinds=_ns_known_figure_kinds_for_subquestion_repair(
                question, params, sub
            ),
            scope=scope,
        )


def _ns_figure_spec_entries(
    question: ExamQuestion,
    params: SampledParams,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if question.chart_spec is not None:
        entries.append(
            {
                "spec": question.chart_spec,
                "sub": None,
                "config": None,
                "label": "題幹",
                "序號": 0,
                "plan_index": 0,
                "pinned": False,
            }
        )
    for sub in question.subquestions:
        if sub.chart_spec is None:
            continue
        cfg = _ns_subquestion_config_for(params, sub)
        entries.append(
            {
                "spec": sub.chart_spec,
                "sub": sub,
                "config": cfg,
                "label": f"小題 {sub.序號}",
                "序號": sub.序號,
                "plan_index": sub._plan_index if sub._plan_index is not None else sub.序號,
                "pinned": bool(cfg and cfg.figure_kind and cfg.figure_kind.strip()),
            }
        )
    return entries


def _ns_figure_data_consistency_entries(
    question: ExamQuestion,
) -> list[Any]:
    return build_figure_consistency_entries(
        question,
        _parse_subquestion_image_spec,
        _ns_figure_kind_repair_key,
    )


def _ns_enforce_figure_data_consistency(
    question: ExamQuestion,
    client: Any,
    obs: Any,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
    scope: OperationScope | None = None,
) -> None:
    """Repair or warn for contradictory values shared by NS figures."""
    def on_unresolved(conflict: Any, entries: Sequence[Any]) -> None:
        entry = make_data_inconsistency_entry(
            question.id,
            entries[conflict.left_index].label,
            entries[conflict.right_index].label,
            conflict,
        )
        print(f"  {entry.message}", file=sys.stderr)
        emit_stage(
            obs, "image_agent", "render_image", "warning", message=entry.message,
            scope=scope,
        )
        if on_figure_policy_entry is not None:
            on_figure_policy_entry(entry)

    enforce_figure_data_consistency(
        lambda: _ns_figure_data_consistency_entries(question),
        attempted=question._figure_kind_repair_attempted,
        client=client,
        on_unresolved=on_unresolved,
    )


def _ns_collision_repair_target(
    entries: list[dict[str, Any]],
    left: int,
    right: int,
) -> int | None:
    candidates = [
        index for index in (left, right) if not entries[index]["pinned"]
    ]
    if not candidates:
        return None
    sub_candidates = [index for index in candidates if entries[index]["sub"] is not None]
    top_candidates = [index for index in candidates if entries[index]["sub"] is None]
    if sub_candidates:
        return max(sub_candidates, key=lambda index: (entries[index]["plan_index"], index))
    return top_candidates[0] if top_candidates else candidates[0]


def _ns_rerender_top_level_image(
    question: ExamQuestion,
    config: Config,
    client: Any,
    html_renderer: Any,
    image_generation_mode: str,
    obs: Any,
    scope: OperationScope | None = None,
) -> None:
    if question.chart_spec is None:
        return
    img_path = config.output_dir / f"{question.id}.png"
    print(f"  Re-rendering image after figure-kind repair: {img_path}", file=sys.stderr)
    image_scope = new_operation_scope(scope, kind="image") if scope is not None else None
    on_render_error, render_failed = make_render_error_sink(obs, scope=image_scope)
    emit_stage(obs, "image_agent", "render_image", "start", scope=image_scope)
    rendered = render_image(
        question.chart_spec.model_dump(),
        img_path,
        question_text="\n".join(question.題目) or question.文本,
        html_renderer=html_renderer,
        llm_client=client,
        image_generation_mode=image_generation_mode,
        on_error=on_render_error,
        scope=image_scope,
    )
    if not render_failed:
        emit_stage(obs, "image_agent", "render_image", "end", scope=image_scope)
    if rendered:
        question.圖片 = img_path.name


def _ns_enforce_figure_kind_diversity(
    question: ExamQuestion,
    config: Config,
    client: Any,
    html_renderer: Any,
    image_generation_mode: str,
    obs: Any,
    params: SampledParams,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
    scope: OperationScope | None = None,
) -> None:
    """Repair detected NS collisions once each, then warn if any remain."""
    entries = _ns_figure_spec_entries(question, params)
    if not entries:
        return

    def emit_spec_entries() -> None:
        if on_figure_policy_entry is None:
            return
        for entry in _ns_figure_spec_entries(question, params):
            on_figure_policy_entry(
                make_spec_entry(question.id, entry["label"], entry["spec"])
            )

    emit_spec_entries()
    _ns_enforce_figure_data_consistency(
        question,
        client,
        obs,
        on_figure_policy_entry,
        scope=scope,
    )
    entries = _ns_figure_spec_entries(question, params)
    if params.allow_duplicate_figure_kinds:
        return

    collisions = find_figure_kind_collisions(
        [entry["spec"] for entry in entries],
        {index for index, entry in enumerate(entries) if entry["pinned"]},
        allow_duplicates=False,
    )
    for left, right, kind in collisions:
        entries = _ns_figure_spec_entries(question, params)
        if left >= len(entries) or right >= len(entries):
            continue
        target = _ns_collision_repair_target(entries, left, right)
        if target is None:
            continue
        left_label = entries[left]["label"]
        right_label = entries[right]["label"]
        if on_figure_policy_entry is not None:
            on_figure_policy_entry(
                make_collision_entry(question.id, left_label, right_label, kind)
            )
        forbidden = [
            normalize_figure_kind(effective_figure_kind(entry["spec"]))
            for index, entry in enumerate(entries)
            if index != target and effective_figure_kind(entry["spec"])
        ]
        target_entry = entries[target]
        before_spec = target_entry["spec"]
        before_kind = effective_figure_kind(before_spec)
        after_kind = before_kind
        succeeded = False
        repair_error: str | None = None
        try:
            if target_entry["sub"] is None:
                _ns_ensure_top_level_visual_spec(
                    question,
                    params,
                    client,
                    forbidden_kinds=forbidden,
                    force_repair=True,
                    scope=scope,
                )
                if question.chart_spec != before_spec:
                    _ns_rerender_top_level_image(
                        question,
                        config,
                        client,
                        html_renderer,
                        image_generation_mode,
                        obs,
                        scope=scope,
                    )
                after_kind = effective_figure_kind(question.chart_spec)
                succeeded = question.chart_spec != before_spec
            else:
                sub = target_entry["sub"]
                cfg = target_entry["config"]
                _ns_ensure_subquestion_visual_spec(
                    sub,
                    question,
                    cfg.content_type if cfg and cfg.content_type else "",
                    client,
                    forbidden_kinds=forbidden,
                    force_repair=True,
                    allow_duplicates=params.allow_duplicate_figure_kinds,
                    scope=scope,
                )
                after_kind = effective_figure_kind(sub.chart_spec)
                succeeded = sub.chart_spec != before_spec
        except Exception as exc:
            repair_error = str(exc)
            message = (
                f"Warning: NS 圖像種類 targeted repair failed for "
                f"{target_entry['label']}: {exc}; duplicate image shipped"
            )
            print(f"  {message}", file=sys.stderr)
            emit_stage(
                obs, "image_agent", "render_image", "warning", message=message,
                scope=scope,
            )
        if on_figure_policy_entry is not None:
            on_figure_policy_entry(
                make_repair_entry(
                    question.id,
                    target_entry["label"],
                    before_kind,
                    after_kind,
                    forbidden,
                    succeeded,
                    repair_error,
                )
            )
        emit_spec_entries()

    entries = _ns_figure_spec_entries(question, params)
    final_collisions = find_figure_kind_collisions(
        [entry["spec"] for entry in entries],
        {index for index, entry in enumerate(entries) if entry["pinned"]},
        allow_duplicates=False,
    )
    for left, right, kind in final_collisions:
        left_label = entries[left]["label"]
        right_label = entries[right]["label"]
        message = (
            f"Warning: NS 圖像種類 diversity violation remains between "
            f"{left_label} and {right_label} ({kind}); duplicate image shipped"
        )
        print(f"  {message}", file=sys.stderr)
        emit_stage(
            obs, "image_agent", "render_image", "warning", message=message,
            scope=scope,
        )
        if on_figure_policy_entry is not None:
            on_figure_policy_entry(
                make_warning_entry(
                    question.id,
                    message,
                    left=left_label,
                    right=right_label,
                    effective_kind=kind,
                )
            )


def _ns_warn_about_undeclared_figure_kinds(
    question: ExamQuestion,
    params: SampledParams,
    obs: Any,
    on_figure_policy_entry: FigurePolicyTrailCallback | None,
    scope: OperationScope | None = None,
) -> None:
    for entry in _ns_figure_spec_entries(question, params):
        if _ns_declared_figure_kind(entry["spec"]):
            continue
        effective_kind = effective_figure_kind(entry["spec"])
        message = f"Warning: NS {entry['label']} 未宣告圖像種類；視覺素材仍繼續渲染"
        print(f"  {message}", file=sys.stderr)
        emit_stage(
            obs, "image_agent", "render_image", "warning", message=message,
            scope=scope,
        )
        if on_figure_policy_entry is not None:
            on_figure_policy_entry(
                make_warning_entry(
                    question.id,
                    message,
                    duplicate_image_shipped=False,
                    right=entry["label"],
                    effective_kind=effective_kind or None,
                )
            )


def _ns_render_subquestion_images(
    question: ExamQuestion,
    config: Config,
    client: Any,
    html_renderer: Any,
    image_generation_mode: str,
    obs: Any,
    params: SampledParams,
    on_figure_policy_entry: Callable[..., None] | None = None,
    scope: OperationScope | None = None,
) -> list[str]:
    """Apply NS figure policy, then render non-null subquestion chart specs."""
    on_figure_policy_entry = _scoped_callback(on_figure_policy_entry, scope)
    for sub in question.subquestions:
        cfg = _ns_subquestion_config_for(params, sub)
        if cfg is None or (
            cfg.content_type not in _VISUAL_CONTENT_TYPES and not cfg.figure_kind
        ):
            continue
        if sub.chart_spec is None and client is not None:
            attempt_key = _ns_figure_kind_repair_key(sub)
            if attempt_key in question._figure_kind_repair_attempted:
                continue
            question._figure_kind_repair_attempted.add(attempt_key)
        _ns_ensure_subquestion_visual_spec(
            sub,
            question,
            cfg.content_type or "",
            client,
            figure_kind=cfg.figure_kind,
            forbidden_kinds=_ns_known_figure_kinds_for_subquestion_repair(
                question, params, sub
            ),
            allow_duplicates=params.allow_duplicate_figure_kinds,
            scope=scope,
        )

    for sub in question.subquestions:
        if sub.chart_spec is None or _ns_declared_figure_kind(sub.chart_spec) or client is None:
            continue
        attempt_key = _ns_figure_kind_repair_key(sub)
        if attempt_key in question._figure_kind_repair_attempted:
            continue
        question._figure_kind_repair_attempted.add(attempt_key)
        _ns_repair_figure_kind_declaration(
            question=question,
            label=f"小題 {sub.序號}",
            spec=sub.chart_spec,
            params=params,
            client=client,
            set_spec=lambda repaired, sub=sub: setattr(sub, "chart_spec", repaired),
            on_figure_policy_entry=on_figure_policy_entry,
            forbidden_kinds=_ns_known_figure_kinds_for_subquestion_repair(
                question, params, sub
            ),
            scope=scope,
        )

    _ns_enforce_figure_kind_diversity(
        question,
        config,
        client,
        html_renderer,
        image_generation_mode,
        obs,
        params,
        on_figure_policy_entry,
        scope=scope,
    )
    _ns_warn_about_undeclared_figure_kinds(
        question, params, obs, on_figure_policy_entry, scope=scope
    )

    rendered_paths: list[str] = []
    subquestion_image_modes = {
        i: cfg.image_generation_mode
        for i, cfg in enumerate(params.subquestion_configs, start=1)
        if cfg.image_generation_mode
    }
    for sub in question.subquestions:
        if not sub.chart_spec:
            continue
        plan_index = sub._plan_index if sub._plan_index is not None else sub.序號
        img_path = config.output_dir / f"{question.id}_sq{plan_index}.png"
        mode = subquestion_image_modes.get(plan_index, image_generation_mode)
        sub.image_generation_mode = mode
        question_text = "\n\n".join(
            part for part in (question.文本, sub.題目) if part
        )
        print(f"  Rendering subquestion image: {img_path}", file=sys.stderr)
        image_scope = (
            new_operation_scope(
                scope,
                kind="image",
                subquestion_index=plan_index - 1,
            )
            if scope is not None else None
        )
        on_render_error, render_failed = make_render_error_sink(obs, scope=image_scope)
        emit_stage(obs, "image_agent", "render_image", "start", scope=image_scope)
        rendered = render_image(
            sub.chart_spec.model_dump(),
            img_path,
            question_text=question_text,
            html_renderer=html_renderer,
            llm_client=client,
            image_generation_mode=mode,
            on_error=on_render_error,
            scope=image_scope,
        )
        if not render_failed:
            emit_stage(obs, "image_agent", "render_image", "end", scope=image_scope)
        if rendered:
            sub.圖片 = img_path.name
            rendered_paths.append(rendered)
    return rendered_paths


def _ns_post_correction_visual_policy(
    question: ExamQuestion,
    config: Config,
    client: Any,
    html_renderer: Any,
    image_generation_mode: str,
    obs: Any,
    params: SampledParams,
    *,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
    scope: OperationScope | None = None,
) -> None:
    """Reapply NS policy when a correction pass changes visual specs."""
    prior_top_spec = question.chart_spec.model_copy() if question.chart_spec else None
    _ns_prepare_visual_policy(
        question,
        params,
        client,
        on_figure_policy_entry=on_figure_policy_entry,
        scope=scope,
    )
    if question.chart_spec != prior_top_spec:
        _ns_rerender_top_level_image(
            question,
            config,
            client,
            html_renderer,
            image_generation_mode,
            obs,
            scope=scope,
        )
    _ns_render_subquestion_images(
        question,
        config,
        client,
        html_renderer,
        image_generation_mode,
        obs,
        params,
        on_figure_policy_entry=on_figure_policy_entry,
        scope=scope,
    )


_NS_SPEC = SubjectGenerationSpec(
    few_shot_subdir="natural_sciences",
    build_text_system_fn=_ns_build_text_system,
    build_text_user_fn=_ns_build_text_user,
    build_subquestion_system_fn=_ns_build_subquestion_system,
    build_subquestion_user_fn=_ns_build_subquestion_user,
    parse_text_shell_fn=_parse_text_shell,
    parse_subquestion_fn=_parse_subquestion,
    make_fallback_sq_plans_fn=_ns_make_fallback_sq_plans,
    ensure_visual_spec_fn=_ns_ensure_visual_spec,
    render_subquestion_images_fn=_ns_render_subquestion_images,
    prepare_visual_policy_fn=_ns_prepare_visual_policy,
    post_correction_visual_policy_fn=_ns_post_correction_visual_policy,
    image_question_text_fn=lambda q: "\n".join(q.題目),
    verify_fn=verify_question,
    correct_fn=correct_question,
    fixed_subquestion_identity=True,
)


def _ns_spec_for_batch(balanced_batch: bool) -> SubjectGenerationSpec:
    if not balanced_batch:
        return _NS_SPEC

    def build_text_user(*args: Any) -> tuple[str, list[Path]]:
        return _ns_build_text_user(*args, balanced_batch=True)

    return dataclasses.replace(_NS_SPEC, build_text_user_fn=build_text_user)


def generate_one(
    config: Config,
    client: LLMClient | None,
    params: SampledParams,
    question_id: str,
    dry_run: bool = False,
    skip_verify: bool = False,
    disable_reference_fewshot: bool = False,
    html_renderer: PlaywrightRenderer | None = None,
    image_generation_mode: str = "html",
    user_passage: str | None = None,
    text_word_limit: int | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    text_instruction: str | None = None,
    on_question_update: QuestionUpdateCallback | None = None,
    on_trail_entry: VerificationTrailCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
    curriculum_context: CurriculumContext | None = None,
    balanced_batch: bool = False,
    core_question_callback: bool = True,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
    on_reference_example_entry: "Callable | None" = None,
    question_context: Any | None = None,
) -> ExamQuestion | str:
    """Generate a single PISA Science question set."""
    params = _with_text_word_limit(params, text_word_limit)
    return generate_one_core(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        spec=_ns_spec_for_batch(balanced_batch),
        dry_run=dry_run,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        text_instruction=text_instruction,
        core_question_callback=core_question_callback,
        on_question_update=on_question_update,
        on_trail_entry=on_trail_entry,
        on_figure_policy_entry=on_figure_policy_entry,
        sub_client_factory=sub_client_factory,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
        question_context=question_context,
    )


def build_generation_prompts(
    config: Config,
    params: SampledParams,
    **kwargs: Any,
) -> tuple[str, str, list]:
    """Build the exact prompts used by the 自然科學文本生成器."""
    from src.common.generation_core import build_text_generation_prompts

    params = _with_text_word_limit(params, kwargs.pop("text_word_limit", None))
    spec = _ns_spec_for_batch(kwargs.pop("balanced_batch", False))
    kwargs.setdefault("core_question_callback", True)
    system, user, images, _stage_ctx, _draws = build_text_generation_prompts(
        config, params, spec, **kwargs
    )
    return system, user, images


def build_subquestion_prompt_previews(
    config: Config,
    params: SampledParams,
    **kwargs: Any,
) -> list[tuple[int, str, str, list]]:
    """Build 子題產生器 prompts without invoking either generation stage."""
    from src.common.generation_core import (  # noqa: PLC0415
        build_subquestion_generation_prompts,
    )

    return build_subquestion_generation_prompts(
        config,
        params,
        _NS_SPEC,
        disable_reference_fewshot=kwargs.get("disable_reference_fewshot", False),
        image_generation_mode=kwargs.get("image_generation_mode", "html"),
        user_passage=kwargs.get("user_passage"),
        user_options=kwargs.get("user_options"),
        user_topic=kwargs.get("user_topic"),
        user_core_question=kwargs.get("user_core_question"),
        text_instruction=kwargs.get("text_instruction"),
        prior_scopes=kwargs.get("prior_scopes"),
        core_question_callback=kwargs.get("core_question_callback", True),
    )


def generate_with_corrections(
    config: Config,
    client: LLMClient | None,
    params: SampledParams,
    question_id: str,
    max_retries: int = 3,
    skip_verify: bool = False,
    disable_reference_fewshot: bool = False,
    html_renderer: PlaywrightRenderer | None = None,
    image_generation_mode: str = "html",
    dry_run: bool = False,
    user_passage: str | None = None,
    text_word_limit: int | None = None,
    user_options: list[str] | None = None,
    user_topic: str | None = None,
    user_core_question: str | None = None,
    text_instruction: str | None = None,
    on_question_update: QuestionUpdateCallback | None = None,
    on_trail_entry: VerificationTrailCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
    curriculum_context: CurriculumContext | None = None,
    balanced_batch: bool = False,
    core_question_callback: bool = True,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
    on_reference_example_entry: "Callable | None" = None,
    is_cancelled: Callable[[], bool] | None = None,
    question_context: Any | None = None,
) -> ExamQuestion | str:
    """generate_one followed by up to max_retries correction passes.

    ``metadata.reporting_scales`` is set to the resolved Reporting Scale of
    each surviving 小題 in 序號 order.  The list is written once here — after
    the correction loop — so it is consistent with the final subquestion list
    and cannot drift across correction passes.
    """
    result = generate_with_corrections_core(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        spec=_ns_spec_for_batch(balanced_batch),
        max_retries=max_retries,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        dry_run=dry_run,
        user_passage=user_passage,
        text_word_limit=text_word_limit,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        text_instruction=text_instruction,
        core_question_callback=core_question_callback,
        on_question_update=on_question_update,
        on_trail_entry=on_trail_entry,
        on_figure_policy_entry=on_figure_policy_entry,
        on_reference_example_entry=on_reference_example_entry,
        sub_client_factory=sub_client_factory,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
        is_cancelled=is_cancelled,
        question_context=question_context,
    )
    if isinstance(result, ExamQuestion) and result.metadata is not None:
        result.metadata.reporting_scales = [
            sq.reporting_scale or ""
            for sq in result.subquestions
        ]
    return result


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.command == "resolve":
        for index in range(args.count):
            seed = args.seed + index if args.seed is not None else None
            resolve_and_print(_ns_partial_payload(args, seed))
        return

    if args.command != "generate":
        return

    config = Config.from_env(args.env_file)
    if args.output:
        config.output_dir = Path(args.output)

    if not args.dry_run:
        config.validate()

    config.output_dir.mkdir(parents=True, exist_ok=True)

    client = None if args.dry_run else LLMClient(config)
    if client is not None:
        client.set_observer(make_stderr_observer(truncate=config.log_truncate))

    html_renderer = None
    if not args.dry_run:
        try:
            html_renderer = PlaywrightRenderer()
            html_renderer.start()
            print("  Playwright browser started.", file=sys.stderr)
        except Exception as e:
            print(
                f"  Warning: Playwright unavailable ({e}). HTML images will be skipped.",
                file=sys.stderr,
            )

    # Build the canonical NS curriculum context once per run; all pipeline stages share it.
    ns_curriculum_context = load_curriculum_context(NATURAL_SCIENCES.data_dir)

    results = []
    prior_scopes: list[PriorScope] = []
    base_seed = args.seed
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
            question_id = f"ns_{timestamp}_{i+1:03d}"

            resolved = resolve_and_print(
                _ns_partial_payload(args, seed),
                delimited=args.dry_run,
            )
            params = _ns_params_from_resolved(resolved.payload)

            print(
                f"\n[{i + 1}/{args.count}] Sampled: grade={params.grade}, "
                f"情境={'、'.join(c.value for c in params.情境)}, "
                f"情境子類別={params.情境子類別.value}, "
                f"題型={params.題型.value}, "
                f"科學能力={'、'.join(c.value for c in params.科學能力)}, "
                f"題目內容類型={params.題目內容類型}",
                file=sys.stderr,
            )

            text_instruction = args.text_instruction or None
            if text_instruction and not text_instruction.strip():
                text_instruction = None

            result = generate_with_corrections(
                config=config,
                client=client,
                params=params,
                question_id=question_id,
                max_retries=max_retries,
                skip_verify=args.no_verify,
                html_renderer=html_renderer,
                image_generation_mode=args.image_generation_mode,
                dry_run=args.dry_run,
                core_question_callback=args.core_question_callback,
                prior_scopes=list(prior_scopes),
                curriculum_context=ns_curriculum_context,
                text_instruction=text_instruction,
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)
            results.append(question)

            scope = extract_ns_prior_scope(question)
            if scope is not None:
                prior_scopes.append(scope)

            if not args.batch:
                out_path = config.output_dir / f"{question_id}.json"
                out_path.write_text(
                    question.model_dump_json(indent=2, exclude_none=True),
                    encoding="utf-8",
                )
                print(f"  Saved: {out_path}", file=sys.stderr)

        if args.batch and results:
            batch_path = config.output_dir / f"batch_{timestamp}.json"
            batch_data = [json.loads(q.model_dump_json(exclude_none=True)) for q in results]
            batch_path.write_text(
                json.dumps(batch_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\nBatch saved: {batch_path}", file=sys.stderr)

        print(f"\nDone. Generated {len(results)} question set(s).", file=sys.stderr)

    finally:
        if html_renderer is not None:
            html_renderer.stop()


if __name__ == "__main__":
    main()
