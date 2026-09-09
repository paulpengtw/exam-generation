"""CLI entry point for social-studies exam question generation."""

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

from src.common.batch_dedup import PriorScope, extract_ss_prior_scope
from src.common.cli_resolver import resolve_and_print
from src.common.difficulty import DEFAULT_DIFFICULTY
from src.common.figure_policy import (
    build_figure_consistency_entries,
    effective_figure_kind,
    enforce_figure_data_consistency,
    find_figure_kind_collisions,
    normalize_figure_kind,
)
from src.common.figure_policy_trail import (
    FigurePolicyTrailEvent,
    make_collision_entry,
    make_data_inconsistency_entry,
    make_repair_entry,
    make_spec_entry,
    make_warning_entry,
)
from src.common.generation_core import generate_one_core, generate_with_corrections_core
from src.common.subject_spec import SOCIAL_STUDIES, SubjectGenerationSpec
from src.common.subquestion_forcing import force_grade
from src.common.verification_trail import VerificationTrailEntry
from src.config import Config
from src.curriculum_context import CurriculumContext, load_curriculum_context
from src.html_renderer import PlaywrightRenderer
from src.llm_client import LLMClient, emit_stage, make_render_error_sink, make_stderr_observer
from src.renderer import render_image
from src.social_studies.context_builder import (
    _LEARNING_STAGE,
    LC_INSTRUCTIONS,
    LP_INSTRUCTIONS,
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
)
from src.social_studies.corrector import correct_question
from src.social_studies.figure_kind_loader import CANONICAL_FIGURE_KINDS
from src.social_studies.planner import plan_context_angles
from src.social_studies.schema_loader import load_grades, load_schemas
from src.social_studies.schemas import (
    CoreCompetency,
    CreativeBrief,
    ExamQuestion,
    ImageSpec,
    LearningContentRef,
    QuestionContext,
    QuestionMetadata,
    QuestionSetType,
    QuestionSubject,
    QuestionType,
    RubricEntry,
    SampledParams,
    SubQuestion,
    SubQuestionConfig,
)
from src.social_studies.verifier import verify_question

logger = logging.getLogger(__name__)

_GRADES: list[int] = load_grades(load_schemas())
_VISUAL_CONTENT_TYPES = {"含圖片", "graphs/charts/tables"}

QuestionUpdateCallback = Callable[[ExamQuestion, str], None]
VerificationTrailCallback = Callable[[VerificationTrailEntry], None]
FigurePolicyTrailCallback = Callable[[FigurePolicyTrailEvent], None]


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


def _figure_kind_repair_instruction(
    params: SampledParams | None,
    forbidden_kinds: list[str] | None = None,
    required_kind: str | None = None,
    allow_duplicates: bool | None = None,
) -> str:
    """Return the figure-kind constraints for a targeted image-spec repair."""
    vocabulary = "、".join(CANONICAL_FIGURE_KINDS)
    lines = [
        "- **圖像種類宣告**：每個視覺素材規格（每個非 null 的 `chart_spec`）"
        "都必須宣告 `figure_kind`；"
        "它是自由文字欄位，未知類型仍可使用具體名稱。",
        "- `figure_kind` 必須描述具體圖像種類；適用時請從 canonical vocabulary 選擇："
        f"{vocabulary}。未知類型仍可使用具體自由文字。"
    ]
    if required_kind:
        lines.append(f"- 本小題的 `figure_kind` 是強制值：`{required_kind}`。")
    if (
        getattr(params, "allow_duplicate_figure_kinds", False)
        if allow_duplicates is None
        else allow_duplicates
    ):
        lines.append("- 本請求允許圖像種類重複；不需套用不得重複限制。")
    elif forbidden_kinds:
        unique_kinds = list(
            dict.fromkeys(
                normalize_figure_kind(kind)
                for kind in forbidden_kinds
                if isinstance(kind, str) and kind.strip()
            )
        )
        lines.append("- **圖像種類不得為：**" + "、".join(unique_kinds))
    else:
        lines.append(
            "- 預設每張圖（含題幹與所有小題）的圖像種類不得重複；"
            "不同 render_mode 的同一具體種類仍視為重複。"
        )
    return "\n".join(lines)


_TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT = """\
你是一位108課綱社會領域素養導向題組的視覺素材設計教師。
請只根據既有題組內容，補上一個整個題組共用的主要素材圖片規格。

規則：
- 只輸出合法 JSON 物件，不要輸出其他文字。
- JSON 必須包含 `chart_spec` 欄位。
- `chart_spec` 必須是整個題組共用的視覺素材，不是單一小題專用圖片。
- 若是圖片式素材、地圖、海報、表單、網頁畫面、流程圖或圖解，使用 `render_mode: "html"`。
- 若是統計圖，使用 `render_mode: "chart"` 並提供 `chart_type`、`data`、`labels`。
- 每個視覺素材規格（每個非 null 的 `chart_spec`）都必須宣告具體的 `figure_kind`；
  它是自由文字欄位，適用時從 canonical vocabulary 選擇。
- 不要加入答案提示。
"""

_TOP_LEVEL_IMAGE_REPAIR_USER_TEMPLATE = """\
以下題組的全域文本素材類型是「{content_type}」，但缺少題組頂層 chart_spec。
請為整個題組共用的主要素材補上 `chart_spec`。

{figure_kind_instruction}

```json
{question_json}
```
"""

_SQ_IMAGE_REPAIR_SYSTEM_PROMPT = """\
你是一位108課綱社會領域素養導向題組的視覺素材設計教師。
請只根據既有小題內容，補上一個該小題專用的視覺素材圖片規格。

規則：
- 只輸出合法 JSON 物件，不要輸出其他文字。
- JSON 必須包含 `chart_spec` 欄位。
- `chart_spec` 必須是此小題專用的視覺素材，不是整個題組共用圖片。
- 若是圖片式素材、地圖、海報、表單、網頁畫面、流程圖或圖解，使用 `render_mode: "html"`。
- 若是統計圖，使用 `render_mode: "chart"` 並提供 `chart_type`、`data`、`labels`。
- 每個視覺素材規格（每個非 null 的 `chart_spec`）都必須宣告具體的 `figure_kind`；
  它是自由文字欄位，適用時從 canonical vocabulary 選擇。
- 不要加入答案提示。
"""

_SQ_IMAGE_REPAIR_USER_TEMPLATE = """\
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

_FIGURE_KIND_DECLARATION_REPAIR_SYSTEM_PROMPT = """\
你是一位108課綱社會領域素養導向題組的視覺素材修補教師。
請只補上既有視覺素材規格缺少的圖像種類宣告，不要改變素材內容或渲染方式。

規則：
- 只輸出合法 JSON 物件，不要輸出其他文字。
- JSON 必須包含 `chart_spec`；保留原有的 render_mode、chart_type、data、labels、
  title、description 與 html。
- 每個視覺素材規格（每個非 null 的 `chart_spec`）都必須宣告 `figure_kind`。
- `figure_kind` 是自由文字欄位；適用時從 canonical vocabulary 選擇，未知類型仍可使用具體名稱。
"""

_FIGURE_KIND_DECLARATION_REPAIR_USER_TEMPLATE = """\
以下是{label}目前的視覺素材規格；它尚未宣告 `figure_kind`。
請只在 `chart_spec` 中補上具體的圖像種類宣告，並保留其他欄位。

{figure_kind_instruction}

```json
{spec_json}
```
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="social-studies-exam-generation",
        description="Generate social-studies exam questions using LLMs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate exam questions")
    gen.add_argument("--grade", type=int, choices=_GRADES, help="Target grade level")
    gen.add_argument("--context", type=str, nargs="+", help="情境 (e.g. 個人 公共)")
    gen.add_argument("--set-type", type=str, help="題型種類 (always 題組題)")
    gen.add_argument(
        "--q-type",
        type=str,
        nargs="+",
        choices=[q.value for q in QuestionType],
        help="題型 (one or more values)",
    )
    gen.add_argument(
        "--subject",
        type=str,
        nargs="+",
        choices=[s.value for s in QuestionSubject],  # type: ignore[attr-defined]
        help="科目焦點 (e.g. 歷史 地理 公民與社會 跨科)",
    )
    gen.add_argument(
        "--core-competency",
        type=str,
        nargs="+",
        choices=[c.value for c in CoreCompetency],  # type: ignore[attr-defined]
        help="核心素養代號 pool (e.g. 社-J-A2 社-J-C3)；多值時隨機選 1–3 個",
    )
    gen.add_argument(
        "--learning-content",
        type=str,
        nargs="+",
        help="指定學習內容 編碼 (e.g. 地Aa-Ⅳ-2 地Ad-Ⅳ-1)；覆蓋隨機取樣",
    )
    gen.add_argument(
        "--learning-performance",
        type=str,
        nargs="+",
        help="指定學習表現 編碼 (e.g. 社1b-Ⅳ-1)；覆蓋隨機取樣",
    )
    gen.add_argument(
        "--content-type",
        type=str,
        help="題目內容類型 (純文字 / 含圖片 / graphs/charts/tables / 自訂文字)",
    )
    gen.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        default=None,
        help="題組難度（easy / medium / hard；預設 medium，純粹傳遞不參與隨機抽樣）",
    )
    gen.add_argument("--count", type=int, default=1, help="Number of question sets to generate")
    gen.add_argument("--batch", action="store_true", help="Output as single JSON array")
    gen.add_argument("--seed", type=int, help="Random seed for reproducibility")
    gen.add_argument(
        "--coverage-mode",
        choices=["balanced", "random"],
        default="balanced",
        help="出題模式：balanced（跨題目平均分配題型/學習內容）或 random（每題獨立隨機）",
    )
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

    res = sub.add_parser("resolve", help="Resolve and print generation parameters")
    res.add_argument("--grade", type=int, choices=_GRADES, help="Target grade level")
    res.add_argument("--context", type=str, nargs="+", help="情境")
    res.add_argument("--set-type", type=str, help="題型種類")
    res.add_argument(
        "--q-type",
        type=str,
        nargs="+",
        choices=[q.value for q in QuestionType],
        help="題型",
    )
    res.add_argument(
        "--subject",
        type=str,
        nargs="+",
        choices=[s.value for s in QuestionSubject],  # type: ignore[attr-defined]
        help="科目焦點",
    )
    res.add_argument(
        "--core-competency",
        type=str,
        nargs="+",
        choices=[c.value for c in CoreCompetency],  # type: ignore[attr-defined]
        help="核心素養代號 pool",
    )
    res.add_argument("--learning-content", type=str, nargs="+", help="學習內容 編碼")
    res.add_argument("--learning-performance", type=str, nargs="+", help="學習表現 編碼")
    res.add_argument("--content-type", type=str, help="題目內容類型")
    res.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        default=None,
        help="題組難度",
    )
    res.add_argument("--count", type=int, default=1, help="Number of payloads to resolve")
    res.add_argument("--seed", type=int, help="Random seed for reproducibility")

    return parser.parse_args(argv)


def _ss_partial_payload(args: argparse.Namespace, seed: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"subject": "social_studies"}
    if seed is not None:
        payload["seed"] = seed
    fields = {
        "grade": args.grade,
        "context": args.context,
        "set_type": args.set_type,
        "q_type": args.q_type,
        "subject_filter": args.subject,
        "core_competency": args.core_competency,
        "learning_content": args.learning_content,
        "learning_performance": args.learning_performance,
        "content_type": args.content_type,
        "difficulty": args.difficulty,
    }
    payload.update({key: value for key, value in fields.items() if value is not None})
    return payload


def _ss_params_from_resolved(payload: dict[str, Any]) -> SampledParams:
    subject_filter = payload.get("subject_filter")
    if subject_filter is not None and not isinstance(subject_filter, list):
        subject_filter = [subject_filter]
    raw_configs = payload.get("subquestion_configs") or []
    if isinstance(raw_configs, str):
        raw_configs = json.loads(raw_configs)
    if not isinstance(raw_configs, list):
        raise ValueError("resolved subquestion_configs must be a list")
    configs = [SubQuestionConfig.model_validate(item) for item in raw_configs]

    q_type_values = list(payload.get("q_type") or [])
    if not q_type_values:
        q_type_values = [
            config.question_type.value
            for config in configs
            if config.question_type is not None
        ]
    resolved_q_types: list[QuestionType] = []
    for value in q_type_values:
        question_type = QuestionType(value)
        if question_type not in resolved_q_types:
            resolved_q_types.append(question_type)
    if not resolved_q_types:
        raise ValueError("resolved social-studies payload has no question types")

    return SampledParams(
        grade=payload["grade"],
        seed=payload.get("seed"),
        情境=[QuestionContext(value) for value in payload["context"]],
        題型種類=QuestionSetType(payload["set_type"]),
        題型=resolved_q_types,
        題目內容類型=payload["content_type"],
        科目=QuestionSubject((subject_filter or ["跨科"])[0]),
        內容領域=payload.get("content_domain"),
        target_surface=payload.get("target_surface") or "紙本",
        核心素養=[CoreCompetency(value) for value in payload["core_competency"]],
        學習內容_pool=list(payload["learning_content"]),
        學習表現_pool=list(payload["learning_performance"]),
        認知歷程_pool=[
            config.認知歷程
            for config in configs
            if config.認知歷程 is not None
        ],
        sub_question_count=payload.get("sub_question_count") or len(configs) or None,
        question_word_limit=payload.get("question_word_limit"),
        option_word_limit=payload.get("option_word_limit"),
        text_word_limit=payload.get("text_word_limit"),
        subquestion_configs=configs,
        allow_duplicate_figure_kinds=payload.get("allow_duplicate_figure_kinds", False),
        difficulty=payload.get("difficulty") or DEFAULT_DIFFICULTY,
    )


def _resolve_enum(value: str | None, enum_cls: type) -> object | None:
    if value is None:
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    raise ValueError(f"Invalid value '{value}' for {enum_cls.__name__}")


def _derive_iccs_axes(question: ExamQuestion, params: SampledParams) -> None:
    """Stamp sampled ICCS tags after parsed 小題 have been assembled."""
    if params.內容領域 is not None:
        question.內容領域 = params.內容領域.value

    cognitive_processes: list[str] = []
    for subquestion in question.subquestions:
        process = subquestion.認知歷程
        if process and process not in cognitive_processes:
            cognitive_processes.append(process)
    question.認知歷程 = cognitive_processes


def _parse_subquestion(
    sq_raw: dict,
    question_id: str,
    params: SampledParams,
    i: int,
) -> SubQuestion | None:
    """Parse one raw sub-question dict from 子題產生器 output. Returns None on error."""
    if not isinstance(sq_raw, dict):
        return None
    try:
        cfg = (
            params.subquestion_configs[i - 1]
            if i - 1 < len(params.subquestion_configs) else None
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
        if cfg and cfg.learning_content:
            lc_refs = [
                LearningContentRef(編碼=code, 說明=LC_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_content
            ]
        if cfg and cfg.learning_performance:
            lp_refs = [
                LearningContentRef(編碼=code, 說明=LP_INSTRUCTIONS.get(code, ""))
                for code in cfg.learning_performance
            ]
        cognitive_process = (
            cfg.認知歷程
            if cfg is not None and cfg.認知歷程 is not None
            else (
                params.認知歷程_pool[i - 1]
                if i - 1 < len(params.認知歷程_pool)
                else sq_raw.get("認知歷程")
            )
        )
        rubric = [
            RubricEntry(
                code=str(r.get("code", "")),
                規準說明=r.get("規準說明", ""),
                學生作答實例=r.get("學生作答實例", []),
            )
            for r in (sq_raw.get("評分規準") or sq_raw.get("評分標準") or [])
            if isinstance(r, dict)
        ]
        sq_chart_spec = None
        raw_sq_spec = sq_raw.get("image_spec") or sq_raw.get("chart_spec")
        if isinstance(raw_sq_spec, dict):
            try:
                sq_chart_spec = ImageSpec(**raw_sq_spec)
            except Exception:
                sq_chart_spec = None
        raw_distractor = sq_raw.get("誘答分析", {})
        if isinstance(raw_distractor, dict):
            distractor = {str(k): str(v) for k, v in raw_distractor.items()}
        else:
            distractor = {}
        raw_question_type = sq_raw.get(
            "題型", params.題型[0].value if params.題型 else "選擇題"
        )
        if raw_question_type not in {member.value for member in QuestionType}:
            return None
        result = SubQuestion(
            id=sq_raw.get("id", f"{question_id}-{sq_raw.get('序號', i):02d}"),
            序號=sq_raw.get("序號", i),
            年級=sq_raw.get("年級", params.grade),
            科目=sq_raw.get("科目", [params.科目.value]),
            核心素養=sq_raw.get("核心素養", []),
            學習內容=lc_refs,
            學習表現=lp_refs,
            出題概念=sq_raw.get("出題概念", ""),
            出題指示=(
                cfg.instruction if cfg and cfg.instruction else sq_raw.get("出題指示")
            ),
            認知歷程=cognitive_process,
            題型=raw_question_type,
            題目=sq_raw.get("題目", ""),
            答案=sq_raw.get("答案", ""),
            答案解析=sq_raw.get("答案解析", ""),
            評分規準=rubric,
            誘答分析=distractor,
            題目內容類型=sq_raw.get("題目內容類型"),
            image_generation_mode=sq_raw.get("image_generation_mode"),
            圖片=sq_raw.get("圖片"),
            chart_spec=sq_chart_spec,
            interaction=sq_raw.get("interaction"),
        )
        result.科目 = [params.科目.value]
        # 記錄建構這一小題時所用的 PLAN 索引，供後續圖片修補沿用同一格 各小題配置。
        # 模型自報的 `序號` 可能錯位；修補端必須走這個值，不能拿 `序號` 去查。
        result._plan_index = i
        if cfg is not None:
            _force_subquestion_figure_kind(result, cfg.figure_kind)
        # Issue #290: force 年級 from sampled params, never trust the LLM value.
        # The LLM may copy 年級 from a prompt example that uses a different grade,
        # causing a silent mismatch. Parallel to how 科目 is forced on the line
        # above; 年級 gets the same treatment via the shared helper so that both
        # social studies and natural sciences share one authoritative rule.
        force_grade(result, params.grade)
        return result
    except Exception:
        return None


def _parse_text_shell(
    raw: dict,
    question_id: str,
    params: SampledParams,
    model: str,
) -> ExamQuestion:
    """Parse 文本生成器 output into an ExamQuestion shell with subquestions=[]."""
    chart_spec = None
    raw_spec = raw.get("image_spec") or raw.get("chart_spec")
    if raw_spec:
        try:
            chart_spec = ImageSpec(**raw_spec)
        except Exception:
            if raw_spec.get("chart_type"):
                chart_spec = ImageSpec(
                    render_mode="chart",
                    chart_type=raw_spec.get("chart_type"),
                    figure_kind=raw_spec.get("figure_kind", ""),
                    data=raw_spec.get("data", {}),
                    labels=raw_spec.get("labels", {}),
                    title=raw_spec.get("title", ""),
                    description=raw_spec.get("description", ""),
                )
            else:
                chart_spec = ImageSpec(
                    render_mode="html",
                    figure_kind=raw_spec.get("figure_kind", ""),
                    description=raw_spec.get("description", raw_spec.get("title", "")),
                    title=raw_spec.get("title", ""),
                    data=raw_spec.get("data", {}),
                )

    return ExamQuestion(
        id=question_id,
        核心問題=raw.get("核心問題", ""),
        文本=raw.get("文本", ""),
        取材來源=raw.get("取材來源", []),
        subquestions=[],
        情境=[c.value for c in params.情境],
        題型種類=params.題型種類.value,
        題型=params.題型[0].value if params.題型 else "選擇題",
        題目內容類型=params.題目內容類型,
        題目=raw.get("題目", []),
        正確解題分析=raw.get("正確解題分析", []),
        chart_spec=chart_spec,
        metadata=QuestionMetadata(
            grade=params.grade,
            model=model,
            seed=None,
            difficulty=params.difficulty,
            surface_used=params.target_surface,
        ),
    )


def _parse_image_spec(raw_spec: object) -> ImageSpec | None:
    if not isinstance(raw_spec, dict):
        return None
    try:
        return ImageSpec(**raw_spec)
    except Exception:
        if raw_spec.get("chart_type"):
            try:
                return ImageSpec(
                    render_mode="chart",
                    chart_type=raw_spec.get("chart_type"),
                    figure_kind=raw_spec.get("figure_kind", ""),
                    data=raw_spec.get("data", {}),
                    labels=raw_spec.get("labels", {}),
                    title=raw_spec.get("title", ""),
                    description=raw_spec.get("description", ""),
                )
            except Exception:
                return None
        try:
            return ImageSpec(
                render_mode="html",
                figure_kind=raw_spec.get("figure_kind", ""),
                description=raw_spec.get("description", raw_spec.get("title", "")),
                title=raw_spec.get("title", ""),
                data=raw_spec.get("data", {}),
                html=raw_spec.get("html", ""),
            )
        except Exception:
            return None


def _declared_figure_kind(spec: ImageSpec | None) -> str:
    if spec is None:
        return ""
    value = spec.figure_kind
    return value.strip() if isinstance(value, str) else ""


def _figure_kind_field_was_supplied(spec: ImageSpec) -> bool:
    """Return whether the model explicitly included the declaration field.

    Older subquestion producers treat any non-null ``chart_spec`` as a
    complete visual contract.  Preserve that #320 early-out when the newer
    ``figure_kind`` field is absent entirely; an explicit empty field remains
    eligible for the declaration repair pass.
    """
    return "figure_kind" in spec.model_fields_set


def _canonicalize_repaired_figure_kind(value: str) -> str:
    stripped = value.strip()
    normalized = normalize_figure_kind(stripped)
    return normalized if normalized in CANONICAL_FIGURE_KINDS else stripped


def _figure_kind_repair_key(sub: SubQuestion) -> str:
    """Return a stable per-slot key independent of model-reported 序號."""
    if sub._plan_index is not None:
        return f"小題 plan {sub._plan_index}"
    return f"小題 object {id(sub)}"


def _repair_figure_kind_declaration(
    *,
    question: ExamQuestion,
    label: str,
    spec: ImageSpec,
    params: SampledParams,
    client: Any,
    set_spec: Callable[[ImageSpec], None],
    on_figure_policy_entry: FigurePolicyTrailCallback | None,
    forbidden_kinds: list[str] | None = None,
) -> None:
    """Spend one call to declare a missing visual spec kind."""
    before_kind = effective_figure_kind(spec)
    after_kind = before_kind
    succeeded = False
    repair_error: str | None = None
    try:
        response = client.generate_json(
            _FIGURE_KIND_DECLARATION_REPAIR_SYSTEM_PROMPT,
            _FIGURE_KIND_DECLARATION_REPAIR_USER_TEMPLATE.format(
                label=label,
                figure_kind_instruction=_figure_kind_repair_instruction(
                    params,
                    forbidden_kinds=forbidden_kinds,
                ),
                spec_json=spec.model_dump_json(exclude_none=True),
            ),
            purpose="generate",
        )
        raw_spec = response.get("chart_spec") or response.get("image_spec")
        raw_kind = (
            raw_spec.get("figure_kind")
            if isinstance(raw_spec, dict)
            else response.get("figure_kind")
        )
        if isinstance(raw_kind, str) and raw_kind.strip():
            repaired_spec = spec.model_copy(
                update={"figure_kind": _canonicalize_repaired_figure_kind(raw_kind)}
            )
            set_spec(repaired_spec)
            after_kind = effective_figure_kind(repaired_spec)
            succeeded = bool(_declared_figure_kind(repaired_spec))
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


def _force_subquestion_figure_kind(sub: SubQuestion, figure_kind: str | None) -> None:
    """Apply an explicit per-slot figure-kind pin after model parsing."""
    if not sub.chart_spec or not isinstance(figure_kind, str) or not figure_kind.strip():
        return
    sub.chart_spec = sub.chart_spec.model_copy(update={"figure_kind": figure_kind.strip()})


def _ensure_top_level_visual_spec(
    question: ExamQuestion,
    params: SampledParams,
    client: LLMClient | None,
    *,
    forbidden_kinds: list[str] | None = None,
    force_repair: bool = False,
) -> None:
    """Repair missing shared visual specs for globally visual social-studies 題組."""
    if (
        (question.chart_spec and not force_repair)
        or (params.題目內容類型 not in _VISUAL_CONTENT_TYPES and not force_repair)
        or client is None
    ):
        return

    question_json = question.model_dump_json(
        exclude_none=True,
        exclude={"verification", "圖片"},
    )
    user_prompt = _TOP_LEVEL_IMAGE_REPAIR_USER_TEMPLATE.format(
        content_type=params.題目內容類型,
        question_json=question_json,
        figure_kind_instruction=_figure_kind_repair_instruction(params, forbidden_kinds),
    )

    try:
        repaired = client.generate_json(
            _TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT,
            user_prompt,
            purpose="generate",
        )
    except Exception as exc:
        print(f"  Warning: top-level image spec repair failed: {exc}", file=sys.stderr)
        return

    raw_spec = repaired.get("image_spec") or repaired.get("chart_spec")
    image_spec = _parse_image_spec(raw_spec)
    if image_spec:
        question.chart_spec = image_spec


def _ensure_subquestion_visual_spec(
    sub: SubQuestion,
    question: ExamQuestion,
    content_type: str,
    client: Any,
    *,
    figure_kind: str | None = None,
    forbidden_kinds: list[str] | None = None,
    force_repair: bool = False,
    allow_duplicates: bool = False,
) -> None:
    """Repair a missing chart_spec for a single 小題 whose config requires an image.

    Mirrors :func:`_ensure_top_level_visual_spec` at the 小題 level (#320).
    Repair failure degrades gracefully — the 小題 ships without an image rather
    than aborting the 題組.
    """
    _force_subquestion_figure_kind(sub, figure_kind)
    if (
        (sub.chart_spec and not force_repair)
        or (content_type not in _VISUAL_CONTENT_TYPES and not figure_kind and not force_repair)
        or client is None
    ):
        return

    # 修補只需要素材需求，不需要作答內容。system prompt 已明令「不要加入答案提示」，
    # payload 就不能把答案送過去。
    sq_json = sub.model_dump_json(
        exclude_none=True,
        exclude={"圖片", "答案", "答案解析", "評分規準", "誘答分析"},
    )
    user_prompt = _SQ_IMAGE_REPAIR_USER_TEMPLATE.format(
        content_type=content_type,
        text=question.文本,
        sq_json=sq_json,
        figure_kind_instruction=_figure_kind_repair_instruction(
            params=None,
            forbidden_kinds=forbidden_kinds,
            required_kind=figure_kind,
            allow_duplicates=allow_duplicates,
        ),
    )

    try:
        repaired = client.generate_json(
            _SQ_IMAGE_REPAIR_SYSTEM_PROMPT,
            user_prompt,
            purpose="generate",
        )
    except Exception as exc:
        print(
            f"  Warning: subquestion image spec repair failed for 小題 {sub.序號}: {exc}",
            file=sys.stderr,
        )
        return

    raw_spec = repaired.get("image_spec") or repaired.get("chart_spec")
    image_spec = _parse_image_spec(raw_spec)
    if image_spec:
        if figure_kind and figure_kind.strip():
            image_spec = image_spec.model_copy(update={"figure_kind": figure_kind.strip()})
        sub.chart_spec = image_spec


def _render_subquestion_images(
    question: ExamQuestion,
    config: Config,
    client: LLMClient | None,
    html_renderer: PlaywrightRenderer | None,
    image_generation_mode: str,
    obs,
    subquestion_image_modes: dict[int, str] | None = None,
) -> list[str]:
    """Render PNGs for subquestion-local image specs and return paths."""
    rendered_paths: list[str] = []
    for sub in question.subquestions:
        if not sub.chart_spec:
            continue
        img_path = config.output_dir / f"{question.id}_sq{sub.序號}.png"
        plan_index = sub._plan_index if sub._plan_index is not None else sub.序號
        mode = (subquestion_image_modes or {}).get(plan_index, image_generation_mode)
        sub.image_generation_mode = mode
        question_text = "\n\n".join(
            part for part in (question.文本, sub.題目) if part
        )
        print(f"  Rendering subquestion image: {img_path}", file=sys.stderr)
        _on_render_error, _render_failed = make_render_error_sink(obs)
        emit_stage(obs, "image_agent", "render_image", "start")
        rendered = render_image(
            sub.chart_spec.model_dump(),
            img_path,
            question_text=question_text,
            html_renderer=html_renderer,
            llm_client=client,
            image_generation_mode=mode,
            on_error=_on_render_error,
        )
        if not _render_failed:
            emit_stage(obs, "image_agent", "render_image", "end")
        if rendered:
            sub.圖片 = img_path.name
            rendered_paths.append(rendered)
    return rendered_paths


def _plan_batch_briefs(
    client: LLMClient | None,
    config: Config,
    params_list: list[SampledParams],
) -> list[CreativeBrief | None]:
    """One Opus planning call for the whole batch; length matches params_list.

    Returns `[None] * n` when planning is disabled, the client is unavailable,
    the batch is empty, no shared 情境 remain, the LLM raises, or every
    returned brief is out-of-set. Never raises — planning must never block
    generation.
    """
    n = len(params_list)
    if n == 0:
        return []
    if not config.creative_planning or client is None:
        return [None] * n

    # Union of sampled 情境 across the batch — Opus is free to pick any of them.
    contexts: list[str] = []
    for params in params_list:
        for c in params.情境:
            if c.value not in contexts:
                contexts.append(c.value)
    if not contexts:
        return [None] * n

    # Use the first question's 學習內容_pool as the shared grounding; SS batches
    # typically share stage/subject so this is a reasonable representative pool.
    learning_content_pool = list(params_list[0].學習內容_pool)

    try:
        briefs = plan_context_angles(
            client,
            count=n,
            sampled_contexts=contexts,
            learning_content_pool=learning_content_pool,
            core_question=None,
        )
    except Exception as exc:
        # plan_context_angles (src/common/planner.py) already catches its own
        # LLM/parse failures internally and returns [None] * count instead of
        # raising, so this branch is unreachable in practice today. It is kept
        # as defense-in-depth in case that contract changes upstream.
        logger.warning("Creative planning failed; falling back to briefless prompts: %s", exc)
        return [None] * n

    if not briefs:
        logger.warning(
            "Creative planning returned no valid briefs; falling back to briefless prompts"
        )
        return [None] * n

    # briefs already has length n (padded by plan_context_angles), but guard
    # against future changes by explicitly filling the tail with None.
    result: list[CreativeBrief | None] = list(briefs[:n])
    while len(result) < n:
        result.append(None)
    return result


def _ss_build_text_system(params: SampledParams) -> tuple[str, dict]:
    return build_text_system_prompt(creative_brief=params.creative_brief, params=params), {}


def _ss_build_text_user(
    params, few_shot_dir,
    user_passage, user_options, user_topic, user_core_question,
    image_generation_mode, disable_reference_fewshot, prior_scopes,
    core_question_callback,
    *,
    balanced_batch=False,
):
    return build_text_user_prompt(
        params,
        few_shot_dir,
        rng=random.Random(params.seed),
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        disable_reference_fewshot=disable_reference_fewshot,
        prior_scopes=prior_scopes,
        core_question_callback=core_question_callback,
        balanced_batch=balanced_batch,
    )


def _ss_build_subquestion_system(stage_ctx: dict) -> str:
    return build_subquestion_system_prompt(learning_stage=_LEARNING_STAGE)


def _ss_build_subquestion_user(
    text_raw, params, few_shot_dir, sq_plan, slot_cfg,
    image_generation_mode, disable_reference_fewshot,
    core_question_callback, is_last,
):
    return build_subquestion_user_prompt(
        核心問題=text_raw.get("核心問題", ""),
        # Pass the structured shell so the prompt builder can list a known
        # top-level figure_kind while still rendering only the text content.
        文本=text_raw,
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


def _ss_make_fallback_sq_plans(params: SampledParams, n: int) -> list[dict]:
    return [
        {
            "序號": i,
            "題型": params.題型[0].value if params.題型 else "選擇題",
            "出題概念": "",
        }
        for i in range(1, n + 1)
    ]


def _ss_ensure_visual_spec(
    question: ExamQuestion, params: SampledParams, client: Any,
) -> None:
    _derive_iccs_axes(question, params)
    known_kinds = [
        cfg.figure_kind
        for cfg in params.subquestion_configs
        if cfg.figure_kind
    ]
    known_kinds.extend(
        kind
        for sub in question.subquestions
        if sub.chart_spec is not None
        for kind in [effective_figure_kind(sub.chart_spec)]
        if kind
    )
    if (
        question.chart_spec is None
        and params.題目內容類型 in _VISUAL_CONTENT_TYPES
        and client is not None
    ):
        # The top-level chart-spec repair already has the declaration
        # requirement in its prompt, so it owns this one repair budget.
        question._figure_kind_repair_attempted.add("題幹")
    _ensure_top_level_visual_spec(
        question,
        params,
        client,
        forbidden_kinds=known_kinds,
    )


def _ss_prepare_visual_policy(
    question: ExamQuestion,
    params: SampledParams,
    client: Any,
    *,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
) -> None:
    """Declare every existing visual spec before the shared renderer runs."""
    if client is None:
        return

    attempted = question._figure_kind_repair_attempted
    if question.chart_spec is not None and not _declared_figure_kind(question.chart_spec):
        label = "題幹"
        if label not in attempted:
            attempted.add(label)
            _repair_figure_kind_declaration(
                question=question,
                label=label,
                spec=question.chart_spec,
                params=params,
                client=client,
                set_spec=lambda repaired: setattr(question, "chart_spec", repaired),
                on_figure_policy_entry=on_figure_policy_entry,
            )

    for sub in question.subquestions:
        if sub.chart_spec is None or _declared_figure_kind(sub.chart_spec):
            continue
        label = f"小題 {sub.序號}"
        attempt_key = _figure_kind_repair_key(sub)
        if attempt_key in attempted:
            continue
        if not _figure_kind_field_was_supplied(sub.chart_spec):
            # Keep the pre-existing #320 contract for a model-supplied
            # non-null spec that predates the figure-kind field.  Record the
            # slot as settled so the renderer cannot spend another call on it.
            attempted.add(attempt_key)
            continue
        attempted.add(attempt_key)
        _repair_figure_kind_declaration(
            question=question,
            label=label,
            spec=sub.chart_spec,
            params=params,
            client=client,
            set_spec=lambda repaired, sub=sub: setattr(sub, "chart_spec", repaired),
            on_figure_policy_entry=on_figure_policy_entry,
            forbidden_kinds=_known_figure_kinds_for_subquestion_repair(
                question, params, sub,
            ),
        )


def _subquestion_config_for(params: SampledParams, sub: SubQuestion) -> SubQuestionConfig | None:
    """Resolve a subquestion's config by PLAN index, never by model 序號."""
    plan_index = sub._plan_index if sub._plan_index is not None else sub.序號
    if plan_index < 1 or plan_index > len(params.subquestion_configs):
        return None
    return params.subquestion_configs[plan_index - 1]


def _figure_spec_entries(
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
                "pinned": False,
            }
        )
    for sub in question.subquestions:
        if sub.chart_spec is None:
            continue
        cfg = _subquestion_config_for(params, sub)
        entries.append(
            {
                "spec": sub.chart_spec,
                "sub": sub,
                "config": cfg,
                "label": f"小題 {sub.序號}",
                "序號": sub.序號,
                "pinned": bool(cfg and cfg.figure_kind and cfg.figure_kind.strip()),
            }
        )
    return entries


def _figure_data_consistency_entries(
    question: ExamQuestion,
) -> list:
    return build_figure_consistency_entries(
        question,
        _parse_image_spec,
        _figure_kind_repair_key,
    )


def _enforce_figure_data_consistency(
    question: ExamQuestion,
    client: Any,
    obs: Any,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
) -> None:
    """Repair or warn for contradictory values shared by a 題組's figures."""
    def on_unresolved(conflict: Any, entries: Sequence[Any]) -> None:
        entry = make_data_inconsistency_entry(
            question.id,
            entries[conflict.left_index].label,
            entries[conflict.right_index].label,
            conflict,
        )
        print(f"  {entry.message}", file=sys.stderr)
        emit_stage(obs, "image_agent", "render_image", "warning", message=entry.message)
        if on_figure_policy_entry is not None:
            on_figure_policy_entry(entry)

    enforce_figure_data_consistency(
        lambda: _figure_data_consistency_entries(question),
        attempted=question._figure_kind_repair_attempted,
        client=client,
        on_unresolved=on_unresolved,
    )


def _collision_repair_target(
    entries: list[dict[str, Any]],
    left: int,
    right: int,
) -> int | None:
    candidates = [
        index for index in (left, right)
        if not entries[index]["pinned"]
    ]
    if not candidates:
        return None

    sub_candidates = [index for index in candidates if entries[index]["sub"] is not None]
    top_candidates = [index for index in candidates if entries[index]["sub"] is None]
    if sub_candidates:
        # Later 序號 wins when both colliders are unpinned 小題; this keeps the
        # already-established earlier figure stable whenever possible.
        return max(sub_candidates, key=lambda index: (entries[index]["序號"], index))
    return top_candidates[0] if top_candidates else candidates[0]


def _rerender_top_level_image(
    question: ExamQuestion,
    config: Config,
    client: Any,
    html_renderer: Any,
    image_generation_mode: str,
    obs: Any,
) -> None:
    """Re-render the already-created 題幹 PNG after its spec is repaired."""
    if question.chart_spec is None:
        return
    img_path = config.output_dir / f"{question.id}.png"
    print(f"  Re-rendering image after figure-kind repair: {img_path}", file=sys.stderr)
    _on_render_error, _render_failed = make_render_error_sink(obs)
    emit_stage(obs, "image_agent", "render_image", "start")
    rendered = render_image(
        question.chart_spec.model_dump(),
        img_path,
        question_text="\n".join(question.題目) or question.文本,
        html_renderer=html_renderer,
        llm_client=client,
        image_generation_mode=image_generation_mode,
        on_error=_on_render_error,
    )
    if not _render_failed:
        emit_stage(obs, "image_agent", "render_image", "end")
    if rendered:
        question.圖片 = img_path.name


def _known_figure_kinds_for_subquestion_repair(
    question: ExamQuestion,
    params: SampledParams,
    sub: SubQuestion,
) -> list[str]:
    """List figure kinds already known when repairing one 小題 spec."""
    known: list[str] = []
    if question.chart_spec is not None:
        top_kind = effective_figure_kind(question.chart_spec)
        if top_kind:
            known.append(top_kind)
    current_plan_index = sub._plan_index
    for other in question.subquestions:
        if other is sub or other.chart_spec is None:
            continue
        kind = effective_figure_kind(other.chart_spec)
        if kind:
            known.append(kind)
    for index, cfg in enumerate(params.subquestion_configs, start=1):
        if index != current_plan_index and cfg.figure_kind:
            known.append(cfg.figure_kind)
    return list(dict.fromkeys(known))


def _enforce_figure_kind_diversity(
    question: ExamQuestion,
    config: Config,
    client: Any,
    html_renderer: Any,
    image_generation_mode: str,
    obs: Any,
    params: SampledParams,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
) -> None:
    """Repair each detected SS figure-kind collision once, then warn if needed."""
    entries = _figure_spec_entries(question, params)
    if not entries:
        return

    def emit_spec_entries() -> None:
        if on_figure_policy_entry is None:
            return
        for entry in _figure_spec_entries(question, params):
            on_figure_policy_entry(
                make_spec_entry(question.id, entry["label"], entry["spec"])
            )

    emit_spec_entries()
    _enforce_figure_data_consistency(
        question,
        client,
        obs,
        on_figure_policy_entry,
    )
    entries = _figure_spec_entries(question, params)
    if params.allow_duplicate_figure_kinds:
        return

    specs = [entry["spec"] for entry in entries]
    pinned = {index for index, entry in enumerate(entries) if entry["pinned"]}
    collisions = find_figure_kind_collisions(specs, pinned, allow_duplicates=False)

    for left, right, _kind in collisions:
        entries = _figure_spec_entries(question, params)
        if left >= len(entries) or right >= len(entries):
            continue
        target = _collision_repair_target(entries, left, right)
        if target is None:
            continue
        left_label = entries[left]["label"]
        right_label = entries[right]["label"]
        if on_figure_policy_entry is not None:
            on_figure_policy_entry(
                make_collision_entry(question.id, left_label, right_label, _kind)
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
                _ensure_top_level_visual_spec(
                    question,
                    params,
                    client,
                    forbidden_kinds=forbidden,
                    force_repair=True,
                )
                if question.chart_spec != before_spec:
                    _rerender_top_level_image(
                        question,
                        config,
                        client,
                        html_renderer,
                        image_generation_mode,
                        obs,
                    )
                after_kind = effective_figure_kind(question.chart_spec)
                succeeded = question.chart_spec != before_spec
            else:
                sub = target_entry["sub"]
                cfg = target_entry["config"]
                _ensure_subquestion_visual_spec(
                    sub,
                    question,
                    cfg.content_type if cfg and cfg.content_type else "",
                    client,
                    forbidden_kinds=forbidden,
                    force_repair=True,
                    allow_duplicates=params.allow_duplicate_figure_kinds,
                )
                after_kind = effective_figure_kind(sub.chart_spec)
                succeeded = sub.chart_spec != before_spec
        except Exception as exc:
            repair_error = str(exc)
            message = (
                f"Warning: 圖像種類 targeted repair failed for "
                f"{target_entry['label']}: {exc}; duplicate image shipped"
            )
            print(f"  {message}", file=sys.stderr)
            emit_stage(obs, "image_agent", "render_image", "warning", message=message)
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

    entries = _figure_spec_entries(question, params)
    final_collisions = find_figure_kind_collisions(
        [entry["spec"] for entry in entries],
        {index for index, entry in enumerate(entries) if entry["pinned"]},
        allow_duplicates=False,
    )
    for left, right, kind in final_collisions:
        left_label = entries[left]["label"]
        right_label = entries[right]["label"]
        message = (
            f"Warning: 圖像種類 diversity violation remains between "
            f"{left_label} and {right_label} ({kind}); duplicate image shipped"
        )
        print(f"  {message}", file=sys.stderr)
        emit_stage(obs, "image_agent", "render_image", "warning", message=message)
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


def _warn_about_undeclared_figure_kinds(
    question: ExamQuestion,
    params: SampledParams,
    obs: Any,
    on_figure_policy_entry: FigurePolicyTrailCallback | None,
) -> None:
    """Record unresolved declaration omissions without blocking image output."""
    for entry in _figure_spec_entries(question, params):
        if _declared_figure_kind(entry["spec"]):
            continue
        effective_kind = effective_figure_kind(entry["spec"])
        message = (
            f"Warning: {entry['label']} 未宣告圖像種類；"
            "視覺素材仍繼續渲染"
        )
        print(f"  {message}", file=sys.stderr)
        emit_stage(obs, "image_agent", "render_image", "warning", message=message)
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


def _ss_render_subquestion_images(
    question: ExamQuestion,
    config: Config,
    client: Any,
    html_renderer: Any,
    image_generation_mode: str,
    obs: Any,
    params: SampledParams,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
) -> list[str]:
    # Repair missing chart_specs for 小題 slots configured as visual (#320).
    # Mirrors the 題組頂層 repair in _ensure_top_level_visual_spec.
    # image_generation_mode alone does NOT trigger a repair — only an explicit
    # visual content_type (含圖片 / graphs/charts/tables) does.
    sq_visual_content_types = {
        i: cfg.content_type
        for i, cfg in enumerate(params.subquestion_configs, start=1)
        if cfg.content_type in _VISUAL_CONTENT_TYPES or cfg.figure_kind
    }
    if sq_visual_content_types:
        for sub in question.subquestions:
            # 各小題配置 是建構小題時依 PLAN 索引套用的；模型自報的 序號 可能錯位，
            # 拿它查配置會把甲格的題型／學習內容 配上乙格的圖片決定。
            # 優先用 _plan_index（在 _parse_subquestion 中設定），無則退回 序號。
            plan_idx = sub._plan_index if sub._plan_index is not None else sub.序號
            cfg = _subquestion_config_for(params, sub)
            ct = sq_visual_content_types.get(plan_idx)
            if ct is not None and cfg is not None:
                if sub.chart_spec is None and client is not None:
                    # The existing chart-spec repair and the declaration
                    # repair share one per-slot budget.  Reserve it before
                    # requesting the missing spec; the repair prompt already
                    # asks for its figure_kind.
                    question._figure_kind_repair_attempted.add(
                        _figure_kind_repair_key(sub)
                    )
                _ensure_subquestion_visual_spec(
                    sub,
                    question,
                    ct or "",
                    client,
                    figure_kind=cfg.figure_kind,
                    forbidden_kinds=_known_figure_kinds_for_subquestion_repair(
                        question, params, sub,
                    ),
                    allow_duplicates=params.allow_duplicate_figure_kinds,
                )

    for sub in question.subquestions:
        label = f"小題 {sub.序號}"
        attempt_key = _figure_kind_repair_key(sub)
        if (
            sub.chart_spec is None
            or _declared_figure_kind(sub.chart_spec)
            or client is None
            or attempt_key in question._figure_kind_repair_attempted
        ):
            continue
        question._figure_kind_repair_attempted.add(attempt_key)
        _repair_figure_kind_declaration(
            question=question,
            label=label,
            spec=sub.chart_spec,
            params=params,
            client=client,
            set_spec=lambda repaired, sub=sub: setattr(sub, "chart_spec", repaired),
            on_figure_policy_entry=on_figure_policy_entry,
            forbidden_kinds=_known_figure_kinds_for_subquestion_repair(
                question, params, sub,
            ),
        )

    _enforce_figure_kind_diversity(
        question,
        config,
        client,
        html_renderer,
        image_generation_mode,
        obs,
        params,
        on_figure_policy_entry,
    )
    _warn_about_undeclared_figure_kinds(
        question,
        params,
        obs,
        on_figure_policy_entry,
    )

    return _render_subquestion_images(
        question,
        config,
        client,
        html_renderer,
        image_generation_mode,
        obs,
        {
            i: cfg.image_generation_mode
            for i, cfg in enumerate(params.subquestion_configs, start=1)
            if cfg.image_generation_mode
        },
    )


_SS_SPEC = SubjectGenerationSpec(
    few_shot_subdir="social_studies",
    build_text_system_fn=_ss_build_text_system,
    build_text_user_fn=_ss_build_text_user,
    build_subquestion_system_fn=_ss_build_subquestion_system,
    build_subquestion_user_fn=_ss_build_subquestion_user,
    parse_text_shell_fn=_parse_text_shell,
    parse_subquestion_fn=_parse_subquestion,
    make_fallback_sq_plans_fn=_ss_make_fallback_sq_plans,
    ensure_visual_spec_fn=_ss_ensure_visual_spec,
    render_subquestion_images_fn=_ss_render_subquestion_images,
    prepare_visual_policy_fn=_ss_prepare_visual_policy,
    image_question_text_fn=lambda q: "\n".join(q.題目) or q.文本,
    verify_fn=verify_question,
    correct_fn=correct_question,
)


def _ss_spec_for_batch(balanced_batch: bool) -> SubjectGenerationSpec:
    if not balanced_batch:
        return _SS_SPEC

    def build_text_user(*args: Any) -> tuple[str, list[Path]]:
        return _ss_build_text_user(*args, balanced_batch=True)

    return dataclasses.replace(_SS_SPEC, build_text_user_fn=build_text_user)


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
    on_question_update: QuestionUpdateCallback | None = None,
    on_trail_entry: VerificationTrailCallback | None = None,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
    sub_client_factory: Callable[[], Any] | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
    curriculum_context: CurriculumContext | None = None,
    balanced_batch: bool = False,
    core_question_callback: bool = True,
) -> ExamQuestion | str:
    """Generate a single social-studies question set."""
    params = _with_text_word_limit(params, text_word_limit)
    result = generate_one_core(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        spec=_ss_spec_for_batch(balanced_batch),
        dry_run=dry_run,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        core_question_callback=core_question_callback,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        on_question_update=on_question_update,
        on_trail_entry=on_trail_entry,
        on_figure_policy_entry=on_figure_policy_entry,
        sub_client_factory=sub_client_factory,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
    )
    if isinstance(result, ExamQuestion):
        _derive_iccs_axes(result, params)
    return result


def build_generation_prompts(
    config: Config,
    params: SampledParams,
    **kwargs: Any,
) -> tuple[str, str, list]:
    """Build the exact prompts used by the 社會領域文本生成器."""
    from src.common.generation_core import build_text_generation_prompts

    params = _with_text_word_limit(params, kwargs.pop("text_word_limit", None))
    spec = _ss_spec_for_batch(kwargs.pop("balanced_batch", False))
    kwargs.setdefault("core_question_callback", True)
    system, user, images, _stage_ctx = build_text_generation_prompts(
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
        _SS_SPEC,
        disable_reference_fewshot=kwargs.get("disable_reference_fewshot", False),
        image_generation_mode=kwargs.get("image_generation_mode", "html"),
        user_passage=kwargs.get("user_passage"),
        user_options=kwargs.get("user_options"),
        user_topic=kwargs.get("user_topic"),
        user_core_question=kwargs.get("user_core_question"),
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
    on_question_update: QuestionUpdateCallback | None = None,
    on_trail_entry: VerificationTrailCallback | None = None,
    on_figure_policy_entry: FigurePolicyTrailCallback | None = None,
    prior_scopes: Sequence[PriorScope] | None = None,
    curriculum_context: CurriculumContext | None = None,
    balanced_batch: bool = False,
    core_question_callback: bool = True,
) -> ExamQuestion | str:
    """generate_one followed by up to max_retries correction passes."""
    result = generate_with_corrections_core(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        spec=_ss_spec_for_batch(balanced_batch),
        max_retries=max_retries,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        core_question_callback=core_question_callback,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        dry_run=dry_run,
        user_passage=user_passage,
        text_word_limit=text_word_limit,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        on_question_update=on_question_update,
        on_trail_entry=on_trail_entry,
        on_figure_policy_entry=on_figure_policy_entry,
        prior_scopes=prior_scopes,
        curriculum_context=curriculum_context,
    )
    if isinstance(result, ExamQuestion):
        _derive_iccs_axes(result, params)
    return result


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.command == "resolve":
        for index in range(args.count):
            seed = args.seed + index if args.seed is not None else None
            resolve_and_print(_ss_partial_payload(args, seed))
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

    # Build the canonical SS curriculum context once per run; all pipeline stages share it.
    ss_curriculum_context = load_curriculum_context(SOCIAL_STUDIES.data_dir)

    results = []
    prior_scopes: list[PriorScope] = []
    base_seed = args.seed
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    balanced_batch = args.coverage_mode == "balanced" and args.count > 1

    try:
        params_list: list[SampledParams] = []
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
            resolved = resolve_and_print(
                _ss_partial_payload(args, seed),
                delimited=args.dry_run,
            )
            params = _ss_params_from_resolved(resolved.payload)
            params_list.append(params)

        briefs = _plan_batch_briefs(client, config, params_list)
        for i, brief in enumerate(briefs):
            if brief is not None:
                params_list[i] = params_list[i].model_copy(update={"creative_brief": brief})

        for i, params in enumerate(params_list):
            question_id = f"ss_{timestamp}_{i+1:03d}"

            print(f"\n[{i+1}/{args.count}] Sampled: grade={params.grade}, "
                  f"科目={params.科目.value}, "
                  f"情境={'、'.join(c.value for c in params.情境)}, "
                  f"題型={'、'.join(t.value for t in params.題型)}, "
                  f"題目內容類型={params.題目內容類型}, "
                  f"核心素養={'、'.join(c.value for c in params.核心素養)}, "
                  f"creative_brief={'yes' if params.creative_brief else 'no'}", file=sys.stderr)

            result = generate_with_corrections(
                config=config,
                client=client,
                params=params,
                question_id=question_id,
                max_retries=max_retries,
                skip_verify=args.no_verify,
                core_question_callback=args.core_question_callback,
                html_renderer=html_renderer,
                image_generation_mode=args.image_generation_mode,
                dry_run=args.dry_run,
                prior_scopes=list(prior_scopes),
                curriculum_context=ss_curriculum_context,
                balanced_batch=balanced_batch,
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)

            if question.metadata is None:
                question.metadata = QuestionMetadata(
                    grade=params.grade,
                    model="",
                    coverage_mode_used=args.coverage_mode,
                    surface_used=params.target_surface,
                )
            else:
                question.metadata = question.metadata.model_copy(
                    update={
                        "coverage_mode_used": args.coverage_mode,
                        "surface_used": params.target_surface,
                    }
                )

            results.append(question)

            scope = extract_ss_prior_scope(question)
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
