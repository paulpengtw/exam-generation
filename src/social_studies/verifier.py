"""Verification pass for social studies questions."""

from __future__ import annotations

import inspect
from pathlib import Path

from src.common.generation_events import OperationScope, new_operation_scope
from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.common.verifier import PostVerifyHook, verify_question_common
from src.curriculum_context import CurriculumContext, build_curriculum_section
from src.llm_client import LLMClient, emit_stage
from src.social_studies.domain_mapping import load_domain_mapping
from src.social_studies.fact_check import fact_check_question, is_current_events
from src.social_studies.schema_loader import build_instructions, load_schemas
from src.social_studies.schemas import (
    ChartVerificationResult,
    DragDropSpec,
    ExamQuestion,
    FactCheckResult,
    SliderSpec,
    VerificationResult,
)

# Curriculum-free core — exported for tests that check subject-specific strings
# (寬鬆通過、只攔重大問題, 示意圖, IMAGE_DISCLAIMER, 數值, 標籤).
# The full system prompt used at call time prepends the curriculum section when
# a CurriculumContext is supplied.
VERIFICATION_SYSTEM_PROMPT = f"""\
你是一位108課綱社會領域素養導向命題審核教師，負責審核考試題組的可用性與明顯錯誤。你會收到一道題組，請你：

1. 完全獨立地閱讀文本素材並回答每一道小題（不要看提供的解答）。
2. 將你的解答與提供的解答進行比較。
3. 採取「寬鬆通過、只攔重大問題」的標準：
   - 如果提供的答案或解題分析能被文本合理支持，即使你的答案措辭不同，也應視為通過。
   - 開放式題目可有多種合理回答；只要評分規準（rubric）清楚、公平、能涵蓋合理答案，就應視為通過。
   - 選擇題採 0/1 計分（答對 1 分、答錯 0 分），並應以認知偏誤角度說明誘答分析。
   - 開放式建構反應題採每題專屬評分指引，分數使用 0..N 並允許部分給分；
   - 每一分數級距應有 1-2 個學生作答實例，包含正確與錯誤示例。
   - 小幅措辭、格式、詳略、誘答力不足但不影響作答的問題，請在 details 提醒，但不要因此判定 failed。
   - 只有在答案明顯無文本支持、與文本矛盾、選項正解不存在、題目嚴重歧義、
     評分規準缺失或不公平時，才判定 failed。
4. 如果提供了圖表圖片，請一併檢查圖表是否正確呈現素材。
   - 圖表或非連續文本有輕微標籤/排版問題但仍可理解時，請提醒但不要 failed。
   - 圖表資料明顯錯誤、缺少作答必要資訊，或與題目描述矛盾時，才 failed。

## 示意圖判讀原則

附上的圖表、地圖、圖解或版面素材為示意圖（{IMAGE_DISCLAIMER}）。
不得僅因比例、路線曲度、地標位置或版面留白不完全符合實際尺寸而判定 failed；
但若素材中的數值、標籤、單位、分類、圖例或關鍵標示錯誤，或與題目描述矛盾，仍應判定 failed。

answer_match 的判斷也請寬鬆：
- 若你的答案與提供答案語意相同、可由相同文本依據支持，或符合開放式題目的評分規準，請回傳 true。
- 只有當提供答案與你的獨立判讀有實質衝突，且無法被文本合理支持時，才回傳 false。

請以 JSON 格式回覆：

```json
{{
  "my_answer": "你獨立解題後各題的答案（逐題說明）",
  "provided_answer": "題目提供的答案摘要",
  "answer_match": true/false,
  "passed": true/false,
  "details": "詳細說明；若只是小幅改善建議，請明確寫出仍可通過",
  "chart_verification": {{
    "chart_data_match": true/false,
    "chart_labels_correct": true/false,
    "chart_details": "素材檢查說明"
  }}
}}
```

若題目未附圖表圖片，請省略 chart_verification 欄位。只輸出 JSON，不要輸出其他文字。
"""

VERIFICATION_USER_TEMPLATE = """\
請審核以下社會領域素養導向題組：

## 核心問題

{core_question}

## 文本素材

{passage_text}

## 各小題

{subquestions_text}

## 提供的解題分析（舊版格式備用）

{solution_text}
{difficulty_line}"""


def _build_question_text(question: ExamQuestion) -> tuple[str, str, str]:
    """Return (core_question, passage_text, subquestions_text)."""
    if question.subquestions:
        core_q = question.核心問題
        passage = question.文本
        sqs = []
        for sq in question.subquestions:
            lc = "、".join(f"{r.編碼}" for r in sq.學習內容)
            process_line = f"認知歷程：{sq.認知歷程}\n" if sq.認知歷程 else ""
            sqs.append(
                f"### 問題{sq.序號}（{sq.年級}年級 | {'/'.join(sq.科目)}）\n"
                f"學習內容：{lc}\n"
                f"{process_line}"
                f"{sq.題目}\n"
                f"答案：{sq.答案}\n"
                f"答案解析：{sq.答案解析}"
            )
        return core_q, passage, "\n\n".join(sqs)
    # Fallback for legacy flat format
    parts = question.題目
    return (
        "",
        parts[0] if parts else "",
        "\n".join(parts[1:]) if len(parts) > 1 else "\n".join(parts),
    )


def _has_civic_or_cross_subject(question: ExamQuestion) -> bool:
    return any(
        subject in {"公民與社會", "跨科"}
        for subquestion in question.subquestions
        for subject in subquestion.科目
    )


def _has_history_or_geography_subject(question: ExamQuestion) -> bool:
    return any(
        subject in {"歷史", "地理"}
        for subquestion in question.subquestions
        for subject in subquestion.科目
    )


def _build_iccs_verification_prompt(question: ExamQuestion) -> str:
    """Build ICCS-only criteria, leaving legacy records on the old prompt."""
    sections: list[str] = []
    instructions = build_instructions(load_schemas())
    assignments = [
        (subquestion.序號, subquestion.認知歷程)
        for subquestion in question.subquestions
        if subquestion.認知歷程
    ]
    if assignments:
        assignment_lines = "\n".join(
            f"- 第{number}題：指定 bucket「{process}」"
            for number, process in assignments
        )
        process_definitions = instructions.get("認知歷程", {})
        definition_lines = "\n".join(
            f"- {process}：{instruction}"
            for process, instruction in process_definitions.items()
        )
        declared_domain = question.內容領域
        domain_clause = (
            f"以及題組宣告的內容領域「{declared_domain}」"
            if declared_domain
            else "；題組未宣告內容領域，因此只檢查認知歷程"
        )
        sections.append(
            "## ICCS 認知歷程檢核（硬性）\n"
            f"以下小題帶有已指定的認知歷程。對每一題，請判斷題目實際要求是否展現該 bucket"
            f"{domain_clause}。\n"
            f"{assignment_lines}\n"
            "若不符合，必須回傳 `passed=false`，並在 `details` 明確寫出小題序號、"
            "原樣的指定 bucket，"
            "以及題目為何沒有展現該歷程的理由。沒有認知歷程指定的小題不納入此檢核；舊紀錄不得重新判定。\n"
            "四個 bucket 的定義（以課綱 CSV 指引為準）：\n"
            f"{definition_lines}"
        )

    declared_domain = question.內容領域
    if declared_domain:
        domain_instruction = instructions.get("內容領域", {}).get(declared_domain, "")
        if _has_civic_or_cross_subject(question):
            sections.append(
                "## ICCS 內容領域檢核（公民與社會／跨科，硬性）\n"
                f"宣告內容領域：{declared_domain}\n"
                f"領域 CSV 設計指引：{domain_instruction}\n"
                "請確認題組的核心問題、素材與公民內容不得與宣告內容領域矛盾。"
                "若內容實質上屬於另一內容領域，必須回傳 `passed=false`，並在 `details` "
                "說明矛盾之處。"
                "公民學習內容代碼是否屬於宣告領域的碼池另有 deterministic hard check；"
                "不可忽略該檢核。"
            )
        elif _has_history_or_geography_subject(question):
            sections.append(
                "## ICCS 內容領域主題檢視（僅供參考）\n"
                f"宣告內容領域：{declared_domain}\n"
                f"領域 CSV 設計指引：{domain_instruction}\n"
                "請評論素材與核心問題是否連結此宣告內容領域，並在 `details` 以"
                "「[內容領域主題檢視（僅供參考）]」開頭寫出評估。"
                "這是 advisory only，不得影響 pass/fail，且不得僅因主題連結不足而"
                "回傳 passed=false。"
            )

    return "\n\n".join(sections)


def _ss_content_domain_code_check_hook(
    question: ExamQuestion,
    result: VerificationResult,
    client: LLMClient,
) -> VerificationResult:
    """Hard-check mapped 公 codes against a declared civic content domain."""
    del client
    declared_domain = question.內容領域
    if not declared_domain or not _has_civic_or_cross_subject(question):
        return result

    mapping = load_domain_mapping()
    domain_codes = mapping.domain_to_codes.get(declared_domain, set())
    issues: list[str] = []
    for subquestion in question.subquestions:
        offending_codes = []
        for ref in subquestion.學習內容:
            code = ref.編碼
            if (
                code.startswith("公")
                and code in mapping.code_to_domains
                and code not in domain_codes
                and code not in offending_codes
            ):
                offending_codes.append(code)
        if offending_codes:
            issues.append(
                f"第{subquestion.序號}題：{', '.join(offending_codes)} "
                f"不屬於宣告內容領域「{declared_domain}」的公民碼池"
            )

    if issues:
        result.details = result.details.rstrip()
        result.details += "\n\n[內容領域檢核] " + "；".join(issues)
        result.passed = False
    return result


def _ss_rubric_scale_check_hook(
    question: ExamQuestion,
    result: VerificationResult,
    client: LLMClient,
) -> VerificationResult:
    """Reject the unambiguous legacy 0X code on new ICCS-tagged records."""
    del client
    issues = [
        f"第{subquestion.序號}題使用舊版評分代號 0X；有認知歷程的新紀錄必須使用每題專屬 "
        "0..N 評分指引"
        for subquestion in question.subquestions
        if subquestion.認知歷程
        and any(entry.code == "0X" for entry in subquestion.評分規準)
    ]
    if issues:
        result.details = result.details.rstrip()
        result.details += "\n\n[評分規準檢核] " + "；".join(issues)
        result.passed = False
    return result


def _ss_interaction_spec_check_hook(
    question: ExamQuestion,
    result: VerificationResult,
    client: LLMClient,
) -> VerificationResult:
    """Deterministically validate authoritative digital interaction specs."""
    del client
    issues: list[str] = []
    for subquestion in question.subquestions:
        interaction = subquestion.interaction
        if isinstance(interaction, DragDropSpec):
            draggable_ids = {item.id for item in interaction.draggables}
            target_ids = {target.id for target in interaction.targets}
            mapping = interaction.correct_mapping
            missing_draggables = sorted(draggable_ids - mapping.keys())
            if missing_draggables:
                issues.append(
                    f"第{subquestion.序號}題 draggable id 未出現在 correct_mapping："
                    + ", ".join(missing_draggables)
                )
            unknown_mapping_draggables = sorted(mapping.keys() - draggable_ids)
            if unknown_mapping_draggables:
                issues.append(
                    f"第{subquestion.序號}題 correct_mapping 含不存在的 draggable id："
                    + ", ".join(unknown_mapping_draggables)
                )
            unknown_targets = sorted(set(mapping.values()) - target_ids)
            if unknown_targets:
                issues.append(
                    f"第{subquestion.序號}題 correct_mapping 含不存在的 target id："
                    + ", ".join(unknown_targets)
                )

            total_capacity = sum(target.capacity for target in interaction.targets)
            mapped_count = len(mapping)
            if total_capacity < mapped_count:
                issues.append(
                    f"第{subquestion.序號}題 targets capacity 總和 {total_capacity} "
                    f"小於 correct_mapping 筆數 {mapped_count}"
                )

            mapped_per_target: dict[str, int] = {}
            for target_id in mapping.values():
                mapped_per_target[target_id] = mapped_per_target.get(target_id, 0) + 1
            capacities = {target.id: target.capacity for target in interaction.targets}
            for target_id, count in sorted(mapped_per_target.items()):
                capacity = capacities.get(target_id)
                if capacity is not None and count > capacity:
                    issues.append(
                        f"第{subquestion.序號}題 target id {target_id!r} mapped {count} "
                        f"筆，超過 capacity {capacity}"
                    )

        elif isinstance(interaction, SliderSpec):
            span = interaction.max - interaction.min
            if not interaction.min < interaction.max:
                issues.append(
                    f"第{subquestion.序號}題 slider min {interaction.min} 必須小於 max "
                    f"{interaction.max}"
                )
            if not interaction.step > 0:
                issues.append(
                    f"第{subquestion.序號}題 slider step {interaction.step} 必須大於 0"
                )
            if not interaction.min <= interaction.correct_value <= interaction.max:
                issues.append(
                    f"第{subquestion.序號}題 slider correct_value "
                    f"{interaction.correct_value} 不在 [{interaction.min}, {interaction.max}]"
                )
            if not interaction.tolerance >= 0:
                issues.append(
                    f"第{subquestion.序號}題 slider tolerance {interaction.tolerance} "
                    "不能小於 0"
                )
            if not interaction.tolerance < span:
                issues.append(
                    f"第{subquestion.序號}題 slider tolerance {interaction.tolerance} "
                    f"必須小於 max-min {span}"
                )

    if issues:
        result.details = result.details.rstrip()
        result.details += "\n\n[互動規格檢核] " + "；".join(issues)
        result.passed = False
    return result


_ICCS_THEME_ADVISORY_MARKER = "[內容領域主題檢視（僅供參考）]"


def _ss_content_domain_theme_advisory_hook(
    question: ExamQuestion,
    result: VerificationResult,
    client: LLMClient,
) -> VerificationResult:
    """Annotate history/geography theme feedback without changing the verdict."""
    del client
    if (
        not question.內容領域
        or not _has_history_or_geography_subject(question)
        or _ICCS_THEME_ADVISORY_MARKER in result.details
    ):
        return result

    assessment = result.details.strip() or "LLM 未提供主題檢視評語。"
    result.details = (
        f"{result.details.rstrip()}\n\n{_ICCS_THEME_ADVISORY_MARKER} {assessment}"
        if result.details.strip()
        else f"{_ICCS_THEME_ADVISORY_MARKER} {assessment}"
    )
    return result


def _ss_fact_check_hook(
    question: ExamQuestion,
    result: VerificationResult,
    client: LLMClient,
    *,
    scope: OperationScope | None = None,
) -> VerificationResult:
    """Post-verify hook: optional web-search fact-check for 時事 questions.

    Runs when the provider is ``"anthropic"`` or ``"gemini"`` and the question
    is classified as 時事 by ``is_current_events``. Any failure fails open —
    ``result`` is returned unchanged.
    """
    provider = getattr(getattr(client, "config", None), "web_search_provider", "none")
    max_uses = int(getattr(getattr(client, "config", None), "web_search_max_uses", 5))
    if provider in {"anthropic", "gemini"} and is_current_events(question):
        obs = client.get_observer() if hasattr(client, "get_observer") else None
        fact_scope = (
            new_operation_scope(scope, kind="fact_check")
            if scope is not None
            else None
        )

        def _on_fact_check_error(msg: str) -> None:
            emit_stage(
                obs,
                "fact_checker",
                "fact_check",
                "error",
                scope=fact_scope,
                message=msg,
            )

        emit_stage(
            obs,
            "fact_checker",
            "fact_check",
            "start",
            scope=fact_scope,
        )
        fact_kwargs = {
            "provider": provider,
            "max_uses": max_uses,
            "on_error": _on_fact_check_error,
        }
        try:
            fact_parameters = inspect.signature(fact_check_question).parameters
            accepts_scope = "scope" in fact_parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in fact_parameters.values()
            )
        except (TypeError, ValueError):
            accepts_scope = False
        if accepts_scope:
            fact_kwargs["scope"] = fact_scope
        fc: FactCheckResult | None = fact_check_question(
            client,
            question,
            **fact_kwargs,
        )
        emit_stage(
            obs,
            "fact_checker",
            "fact_check",
            "end",
            scope=fact_scope,
        )
        result.fact_check = fc
        if fc is not None and fc.verified is False:
            joined_issues = "；".join(fc.issues) if fc.issues else "（未提供具體事項）"
            appended = f"事實查證未通過：{joined_issues}"
            result.details = (
                f"{result.details}\n\n{appended}" if result.details else appended
            )
            result.passed = False
    return result


# Declared on the subject spec: hooks run in this order after the LLM verdict.
_SS_POST_VERIFY_HOOKS: list[PostVerifyHook] = [
    _ss_interaction_spec_check_hook,
    _ss_rubric_scale_check_hook,
    _ss_content_domain_code_check_hook,
    _ss_content_domain_theme_advisory_hook,
    _ss_fact_check_hook,
]


def verify_question(
    client: LLMClient,
    question: ExamQuestion,
    chart_image_path: str | None = None,
    curriculum_context: CurriculumContext | None = None,
    *,
    scope: OperationScope | None = None,
    content_revision: int | None = None,
) -> VerificationResult:
    # Fall back to text-only when the image file is absent or unreadable.
    if chart_image_path is not None and not Path(chart_image_path).exists():
        chart_image_path = None

    core_q, passage_text, subquestions_text = _build_question_text(question)
    if not subquestions_text:
        subquestions_text = "\n".join(question.題目)
    solution_text = "\n".join(question.正確解題分析)

    difficulty_value = (
        question.metadata.difficulty.value if question.metadata is not None else "medium"
    )
    difficulty_line = (
        f"\n## 難度（僅供參考，不得作為 pass/fail 判準）\n\n"
        f"命題者要求的難度：{difficulty_value}\n"
    )

    user_prompt = VERIFICATION_USER_TEMPLATE.format(
        core_question=core_q,
        passage_text=passage_text,
        subquestions_text=subquestions_text,
        solution_text=solution_text,
        difficulty_line=difficulty_line,
    )

    if chart_image_path is not None:
        user_prompt += (
            "\n\n## 附圖\n\n"
            "以下附上題目引用的素材圖片，請檢查素材內容與題目描述是否一致。"
        )

    if curriculum_context is not None:
        curriculum_prefix = build_curriculum_section(curriculum_context)
        system_prompt = (
            f"{curriculum_prefix}\n\n---\n\n{VERIFICATION_SYSTEM_PROMPT}"
            if curriculum_prefix
            else VERIFICATION_SYSTEM_PROMPT
        )
    else:
        system_prompt = VERIFICATION_SYSTEM_PROMPT

    iccs_prompt = _build_iccs_verification_prompt(question)
    if iccs_prompt:
        system_prompt = f"{system_prompt}\n\n{iccs_prompt}"

    return verify_question_common(
        client=client,
        question=question,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        verification_result_cls=VerificationResult,
        chart_verif_cls=ChartVerificationResult,
        chart_image_path=chart_image_path,
        post_verify_hooks=_SS_POST_VERIFY_HOOKS,
        scope=scope,
        content_revision=content_revision,
    )
