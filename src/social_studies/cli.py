"""CLI entry point for social studies (PISA reading literacy) exam question generation."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import Config
from src.html_renderer import PlaywrightRenderer
from src.llm_client import LLMClient, emit_stage, make_stderr_observer
from src.renderer import render_image
from src.social_studies.context_builder import (
    LC_INSTRUCTIONS,
    LP_INSTRUCTIONS,
    _LEARNING_STAGE,
    build_subquestion_system_prompt,
    build_subquestion_user_prompt,
    build_text_system_prompt,
    build_text_user_prompt,
)
from src.social_studies.corrector import correct_question
from src.social_studies.planner import plan_context_angles
from src.social_studies.sampler import sample_params
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

    slot_count = params.sub_question_count or len(params.subquestion_configs) or 3
    configs = list(params.subquestion_configs)
    if len(configs) < slot_count:
        configs.extend(SubQuestionConfig() for _ in range(slot_count - len(configs)))

    return params.model_copy(
        update={
            "text_word_limit": text_word_limit,
            "subquestion_configs": [
                cfg
                if cfg.text_word_limit is not None
                else cfg.model_copy(update={"text_word_limit": text_word_limit})
                for cfg in configs
            ],
        },
    )

_TOP_LEVEL_IMAGE_REPAIR_SYSTEM_PROMPT = """\
你是一位108課綱社會領域素養導向題組的視覺素材設計教師。
請只根據既有題組內容，補上一個整個題組共用的主要素材圖片規格。

規則：
- 只輸出合法 JSON 物件，不要輸出其他文字。
- JSON 必須包含 `chart_spec` 欄位。
- `chart_spec` 必須是整個題組共用的視覺素材，不是單一小題專用圖片。
- 若是圖片式素材、地圖、海報、表單、網頁畫面、流程圖或圖解，使用 `render_mode: "html"`。
- 若是統計圖，使用 `render_mode: "chart"` 並提供 `chart_type`、`data`、`labels`。
- 不要加入答案提示。
"""

_TOP_LEVEL_IMAGE_REPAIR_USER_TEMPLATE = """\
以下題組的全域文本素材類型是「{content_type}」，但缺少題組頂層 chart_spec。
請為整個題組共用的主要素材補上 `chart_spec`。

```json
{question_json}
```
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="social-studies-exam-generation",
        description="Generate PISA-style reading literacy exam questions using LLMs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate exam questions")
    gen.add_argument("--grade", type=int, choices=_GRADES, help="Target grade level")
    gen.add_argument("--context", type=str, nargs="+", help="情境 (e.g. 個人 公共)")
    gen.add_argument("--set-type", type=str, help="題型種類 (always 題組題 for PISA)")
    gen.add_argument("--q-type", type=str, nargs="+", help="題型 (one or more values)")
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
    gen.add_argument("--count", type=int, default=1, help="Number of question sets to generate")
    gen.add_argument("--batch", action="store_true", help="Output as single JSON array")
    gen.add_argument("--seed", type=int, help="Random seed for reproducibility")
    gen.add_argument("--no-verify", action="store_true", help="Skip verification pass")
    gen.add_argument("--max-retries", type=int, default=None,
                     help="Max retries when verification fails (default: LLM_MAX_RETRIES env, fallback 3)")
    gen.add_argument(
        "--image-generation-mode",
        choices=["html", "gpt_image"],
        default="html",
        help="Image creation mode for HTML image specs",
    )
    gen.add_argument("--output", type=str, help="Output directory")
    gen.add_argument("--dry-run", action="store_true", help="Show prompt without calling LLM")
    gen.add_argument("--env-file", type=str, help="Path to .env file")

    return parser.parse_args(argv)


def _resolve_enum(value: str | None, enum_cls: type) -> object | None:
    if value is None:
        return None
    for member in enum_cls:
        if member.value == value:
            return member
    raise ValueError(f"Invalid value '{value}' for {enum_cls.__name__}")


def _parse_question(
    raw: dict,
    question_id: str,
    params: SampledParams,
    model: str,
) -> ExamQuestion:
    """Parse raw LLM JSON output into a social-studies ExamQuestion."""
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
                    data=raw_spec.get("data", {}),
                    labels=raw_spec.get("labels", {}),
                    title=raw_spec.get("title", ""),
                    description=raw_spec.get("description", ""),
                )
            else:
                chart_spec = ImageSpec(
                    render_mode="html",
                    description=raw_spec.get("description", raw_spec.get("title", "")),
                    title=raw_spec.get("title", ""),
                    data=raw_spec.get("data", {}),
                )

    subquestions: list[SubQuestion] = []
    for i, sq_raw in enumerate(raw.get("subquestions", []), start=1):
        if not isinstance(sq_raw, dict):
            continue
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
            subquestions.append(SubQuestion(
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
                題型=sq_raw.get("題型", params.題型[0].value if params.題型 else "選擇題"),
                題目=sq_raw.get("題目", ""),
                答案=sq_raw.get("答案", ""),
                答案解析=sq_raw.get("答案解析", ""),
                評分規準=rubric,
                題目內容類型=sq_raw.get("題目內容類型"),
                image_generation_mode=sq_raw.get("image_generation_mode"),
                圖片=sq_raw.get("圖片"),
                chart_spec=sq_chart_spec,
            ))
        except Exception:
            pass

    return ExamQuestion(
        id=question_id,
        核心問題=raw.get("核心問題", ""),
        文本=raw.get("文本", ""),
        取材來源=raw.get("取材來源", []),
        subquestions=subquestions,
        情境=[c.value for c in params.情境],
        題型種類=params.題型種類.value,
        題型=params.題型[0].value if params.題型 else "選擇題",
        閱讀歷程=[p.value for p in params.閱讀歷程],
        文本形式=params.文本形式.value,
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
        return SubQuestion(
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
            題型=sq_raw.get("題型", params.題型[0].value if params.題型 else "選擇題"),
            題目=sq_raw.get("題目", ""),
            答案=sq_raw.get("答案", ""),
            答案解析=sq_raw.get("答案解析", ""),
            評分規準=rubric,
            題目內容類型=sq_raw.get("題目內容類型"),
            image_generation_mode=sq_raw.get("image_generation_mode"),
            圖片=sq_raw.get("圖片"),
            chart_spec=sq_chart_spec,
        )
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
                    data=raw_spec.get("data", {}),
                    labels=raw_spec.get("labels", {}),
                    title=raw_spec.get("title", ""),
                    description=raw_spec.get("description", ""),
                )
            else:
                chart_spec = ImageSpec(
                    render_mode="html",
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
        閱讀歷程=[p.value for p in params.閱讀歷程],
        文本形式=params.文本形式.value,
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
                description=raw_spec.get("description", raw_spec.get("title", "")),
                title=raw_spec.get("title", ""),
                data=raw_spec.get("data", {}),
                html=raw_spec.get("html", ""),
            )
        except Exception:
            return None


def _ensure_top_level_visual_spec(
    question: ExamQuestion,
    params: SampledParams,
    client: LLMClient | None,
) -> None:
    """Repair missing shared visual specs for globally visual social-studies 題組."""
    if question.chart_spec or params.題目內容類型 not in _VISUAL_CONTENT_TYPES or client is None:
        return

    question_json = question.model_dump_json(
        exclude_none=True,
        exclude={"verification", "圖片"},
    )
    user_prompt = _TOP_LEVEL_IMAGE_REPAIR_USER_TEMPLATE.format(
        content_type=params.題目內容類型,
        question_json=question_json,
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
        mode = (subquestion_image_modes or {}).get(sub.序號, image_generation_mode)
        sub.image_generation_mode = mode
        question_text = "\n\n".join(
            part for part in (question.文本, sub.題目) if part
        )
        print(f"  Rendering subquestion image: {img_path}", file=sys.stderr)
        emit_stage(obs, "image_agent", "render_image", "start")
        rendered = render_image(
            sub.chart_spec.model_dump(),
            img_path,
            question_text=question_text,
            html_renderer=html_renderer,
            llm_client=client,
            image_generation_mode=mode,
        )
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
    sub_client_factory: Callable[[], Any] | None = None,
) -> ExamQuestion | str:
    """Generate a single PISA reading question set."""
    few_shot_dir = config.data_dir / "social_studies" / "few_shot"
    params = _with_text_word_limit(params, text_word_limit)
    if dry_run:
        text_system = build_text_system_prompt(creative_brief=params.creative_brief)
        text_user, text_images = build_text_user_prompt(
            params,
            few_shot_dir,
            image_generation_mode=image_generation_mode,
            user_passage=user_passage,
            user_options=user_options,
            user_topic=user_topic,
            user_core_question=user_core_question,
            disable_reference_fewshot=disable_reference_fewshot,
        )
        img_note = f" ({len(text_images)} few-shot images)" if text_images else ""
        return (
            f"=== TEXT SYSTEM PROMPT ({len(text_system)} chars) ===\n{text_system[:2000]}...\n\n"
            f"=== TEXT USER PROMPT ({len(text_user)} chars{img_note}) ===\n{text_user}"
        )

    obs = client.get_observer() if client else None

    print(f"  Generating question {question_id}...", file=sys.stderr)

    text_system = build_text_system_prompt(creative_brief=params.creative_brief)
    text_user, text_images = build_text_user_prompt(
        params,
        few_shot_dir,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        disable_reference_fewshot=disable_reference_fewshot,
    )
    emit_stage(obs, "generator", "llm_generate", "start")
    text_raw = client.generate_json(text_system, text_user, images=text_images or None)
    emit_stage(obs, "generator", "llm_generate", "end")

    question = _parse_text_shell(text_raw, question_id, params, config.model_execute)

    sq_plans: list[dict] = text_raw.get("subquestions", [])
    if not sq_plans:
        n = params.sub_question_count or 3
        sq_plans = [
            {
                "序號": i,
                "題型": params.題型[0].value if params.題型 else "選擇題",
                "出題概念": "",
            }
            for i in range(1, n + 1)
        ]

    sub_system = build_subquestion_system_prompt(learning_stage=_LEARNING_STAGE)
    max_workers = min(len(sq_plans), config.subgen_max_concurrency)
    use_embedded_subquestions = (
        sub_client_factory is None and client is not None and not isinstance(client, LLMClient)
    )

    def _generate_subquestion(sq_plan: dict) -> SubQuestion | None:
        idx = sq_plan.get("序號", sq_plans.index(sq_plan) + 1)
        agent_id = f"sub_generator#{idx}"
        if use_embedded_subquestions:
            return _parse_subquestion(sq_plan, question_id, params, idx)

        sub_client = sub_client_factory() if sub_client_factory is not None else LLMClient(config)
        if hasattr(sub_client, "set_observer"):
            sub_client.set_observer(obs)
        slot_cfg = (
            params.subquestion_configs[idx - 1]
            if idx - 1 < len(params.subquestion_configs) else None
        )
        sub_user, sub_images = build_subquestion_user_prompt(
            核心問題=text_raw.get("核心問題", ""),
            文本=text_raw.get("文本", ""),
            取材來源=text_raw.get("取材來源", []),
            sq_plan=sq_plan,
            params=params,
            few_shot_dir=few_shot_dir,
            image_generation_mode=image_generation_mode,
            cfg=slot_cfg,
            disable_reference_fewshot=disable_reference_fewshot,
        )
        emit_stage(obs, agent_id, "llm_generate", "start")
        try:
            sq_raw = sub_client.generate_json(
                sub_system,
                sub_user,
                images=sub_images or None,
                agent_override=agent_id,
            )
            result = _parse_subquestion(sq_raw, question_id, params, idx)
        except Exception as e:
            print(f"  Sub-generator {agent_id} failed: {e}", file=sys.stderr)
            result = None
        emit_stage(obs, agent_id, "llm_generate", "end")
        return result

    sq_results: dict[int, SubQuestion] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_generate_subquestion, plan): plan for plan in sq_plans}
        for fut in concurrent.futures.as_completed(futures):
            plan = futures[fut]
            idx = plan.get("序號", sq_plans.index(plan) + 1)
            sq = fut.result()
            if sq is not None:
                sq_results[idx] = sq

    question.subquestions = [sq_results[k] for k in sorted(sq_results)]
    _emit_question_update(on_question_update, question, "draft")
    prior_chart_spec = question.chart_spec.model_copy() if question.chart_spec else None
    _ensure_top_level_visual_spec(question, params, client)
    if question.chart_spec != prior_chart_spec:
        _emit_question_update(on_question_update, question, "corrected")

    chart_image_path: str | None = None
    if question.chart_spec:
        img_path = config.output_dir / f"{question_id}.png"
        print(f"  Rendering image: {img_path}", file=sys.stderr)
        emit_stage(obs, "image_agent", "render_image", "start")
        rendered = render_image(
            question.chart_spec.model_dump(),
            img_path,
            question_text="\n".join(question.題目) or question.文本,
            html_renderer=html_renderer,
            llm_client=client,
            image_generation_mode=image_generation_mode,
        )
        emit_stage(obs, "image_agent", "render_image", "end")
        if rendered:
            question.圖片 = f"{question_id}.png"
            chart_image_path = rendered
            _emit_question_update(on_question_update, question, "image")

    subquestion_image_paths = _render_subquestion_images(
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
    if chart_image_path is None and subquestion_image_paths:
        chart_image_path = subquestion_image_paths[0]
    if subquestion_image_paths:
        _emit_question_update(on_question_update, question, "image")

    if not skip_verify:
        print(f"  Verifying question {question_id}...", file=sys.stderr)
        emit_stage(obs, "verifier", "verify", "start")
        result = verify_question(client, question, chart_image_path=chart_image_path)
        emit_stage(obs, "verifier", "verify", "end")
        question.verification = result
        _emit_question_update(on_question_update, question, "verified")
        status = "PASSED" if result.passed else "FAILED"
        print(f"  Verification {status}: {result.details[:100]}", file=sys.stderr)

    return question


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
) -> ExamQuestion | str:
    """generate_one followed by up to max_retries correction passes."""
    question = generate_one(
        config=config,
        client=client,
        params=params,
        question_id=question_id,
        dry_run=dry_run,
        skip_verify=skip_verify,
        disable_reference_fewshot=disable_reference_fewshot,
        html_renderer=html_renderer,
        image_generation_mode=image_generation_mode,
        user_passage=user_passage,
        text_word_limit=text_word_limit,
        user_options=user_options,
        user_topic=user_topic,
        user_core_question=user_core_question,
        on_question_update=on_question_update,
    )

    if dry_run or not isinstance(question, ExamQuestion):
        return question

    obs = client.get_observer() if client else None

    for attempt in range(max_retries):
        if skip_verify or question.verification is None or question.verification.passed:
            break

        print(
            f"  Verification failed; applying correction "
            f"(attempt {attempt + 1}/{max_retries})...",
            file=sys.stderr,
        )

        prior_chart_spec = question.chart_spec.model_copy() if question.chart_spec else None

        chart_image_path: str | None = None
        if question.圖片:
            p = config.output_dir / question.圖片
            if p.exists():
                chart_image_path = str(p)

        emit_stage(obs, "corrector", "correct", "start", retry=attempt + 1)
        question = correct_question(client, question, question.verification,
                                    chart_image_path=chart_image_path)
        emit_stage(obs, "corrector", "correct", "end", retry=attempt + 1)
        _emit_question_update(on_question_update, question, "corrected")

        new_chart_image_path: str | None = None
        if question.chart_spec and question.chart_spec != prior_chart_spec:
            img_path = config.output_dir / f"{question_id}.png"
            print(f"  Chart spec changed; re-rendering image: {img_path}", file=sys.stderr)
            emit_stage(obs, "image_agent", "render_image", "start")
            rendered = render_image(
                question.chart_spec.model_dump(),
                img_path,
                question_text="\n".join(question.題目) or question.文本,
                html_renderer=html_renderer,
                llm_client=client,
                image_generation_mode=image_generation_mode,
            )
            emit_stage(obs, "image_agent", "render_image", "end")
            if rendered:
                question.圖片 = f"{question_id}.png"
                new_chart_image_path = rendered
                _emit_question_update(on_question_update, question, "image")
        elif question.圖片:
            p = config.output_dir / question.圖片
            new_chart_image_path = str(p) if p.exists() else None

        if not skip_verify:
            emit_stage(obs, "verifier", "verify", "start", retry=attempt + 1)
            result = verify_question(client, question, chart_image_path=new_chart_image_path)
            emit_stage(obs, "verifier", "verify", "end", retry=attempt + 1)
            question.verification = result
            _emit_question_update(on_question_update, question, "verified")
            status = "PASSED" if result.passed else "FAILED"
            print(f"  Re-verification {status}: {result.details[:100]}", file=sys.stderr)

    return question


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

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
            print(f"  Warning: Playwright unavailable ({e}). HTML images will be skipped.", file=sys.stderr)

    context_override = (
        [_resolve_enum(v, QuestionContext) for v in args.context]
        if args.context else None
    )
    set_type_override = _resolve_enum(args.set_type, QuestionSetType)
    q_type_override = [_resolve_enum(v, QuestionType) for v in args.q_type] if args.q_type else None
    subject_override = [QuestionSubject(v) for v in args.subject] if args.subject else None
    core_competency_override = [CoreCompetency(v) for v in args.core_competency] if args.core_competency else None
    learning_content_override = args.learning_content if args.learning_content else None
    learning_performance_override = args.learning_performance if args.learning_performance else None
    content_type_override = args.content_type if args.content_type else None

    results = []
    base_seed = args.seed
    max_retries = args.max_retries if args.max_retries is not None else config.max_retries
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        params_list: list[SampledParams] = []
        for i in range(args.count):
            seed = (base_seed + i) if base_seed is not None else None
            params = sample_params(
                grade=args.grade,
                context=context_override,
                set_type=set_type_override,
                q_type=q_type_override,
                subject=subject_override,
                core_competency=core_competency_override,
                learning_content=learning_content_override,
                learning_performance=learning_performance_override,
                content_type=content_type_override,
                seed=seed,
            )
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
                  f"題型={'、'.join(t.value for t in params.題型)}, 閱讀歷程={'、'.join(p.value for p in params.閱讀歷程)}, "
                  f"文本形式={params.文本形式.value}, "
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
                html_renderer=html_renderer,
                image_generation_mode=args.image_generation_mode,
                dry_run=args.dry_run,
            )

            if args.dry_run:
                print(result)
                return

            question = result
            assert isinstance(question, ExamQuestion)
            results.append(question)

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
