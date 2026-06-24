"""Correction pass for social studies questions."""

from __future__ import annotations

import json

from src.llm_client import LLMClient, extract_json
from src.social_studies.context_builder import _build_curriculum_section, _CONTENT_TEXT, _PERFORMANCE_TEXT, _PERFORMANCE_INTRO
from src.social_studies.schemas import ExamQuestion, ImageSpec, VerificationResult

_CURRICULUM_PREFIX: str = _build_curriculum_section(_CONTENT_TEXT, _PERFORMANCE_TEXT, _PERFORMANCE_INTRO)

_CORRECTION_SYSTEM_PROMPT_CORE = """\
你是一位108課綱社會領域素養導向命題教師，剛收到審核老師對一道題組的意見回饋。
請根據審核意見「最小幅度」修正題目，保留所有正確的部分。

修正原則：
- **不要重寫整題**。只更正審核老師明確指出有問題的部分。
- 若問題在小題答案或評分規準 → 只修改 subquestions 中對應小題的 答案/答案解析/評分規準。
- 若問題在選項設計（答案不在選項中）→ 修正對應小題的題目文字與答案，同步修正 正確解題分析。
- 若問題在文本素材或小題敘述歧義 → 最小幅度澄清文本或小題題目，同步調整答案解析。
- 若 chart_verification 指出非連續文本素材錯誤 → 只修正 chart_spec 的 data/labels/description，
  保留 render_mode、chart_type 不變。
- 絕對不可修改：核心問題、情境、題型種類、題型、閱讀歷程、文本形式、id、metadata、
  各小題的 學習內容/學習表現/核心素養/出題概念/出題指示/科目/年級。

請輸出修正後完整的題目 JSON，格式與原題目相同。只輸出 JSON，不要輸出其他文字。
"""

CORRECTION_SYSTEM_PROMPT = (
    f"{_CURRICULUM_PREFIX}\n\n---\n\n{_CORRECTION_SYSTEM_PROMPT_CORE}"
    if _CURRICULUM_PREFIX
    else _CORRECTION_SYSTEM_PROMPT_CORE
)

CORRECTION_USER_TEMPLATE = """\
## 原始題目（JSON）

```json
{question_json}
```

## 審核意見

{verification_details}
{answer_block}{chart_details_block}
請輸出修正後的題目 JSON。
"""


def correct_question(
    client: LLMClient,
    question: ExamQuestion,
    verification: VerificationResult,
    chart_image_path: str | None = None,
) -> ExamQuestion:
    question_data = json.loads(
        question.model_dump_json(exclude_none=True, exclude={"verification", "圖片"})
    )
    question_json = json.dumps(question_data, ensure_ascii=False, indent=2)

    answer_block = ""
    if verification.my_answer or verification.provided_answer:
        answer_block = (
            f"\n## 審核老師獨立解題答案\n{verification.my_answer}\n\n"
            f"## 題目目前提供的答案\n{verification.provided_answer}\n"
        )

    chart_details_block = ""
    if verification.chart_verification:
        cv = verification.chart_verification
        chart_details_block = (
            f"\n## 素材審核意見\n"
            f"數據正確：{'是' if cv.chart_data_match else '否'}\n"
            f"標籤正確：{'是' if cv.chart_labels_correct else '否'}\n"
            f"說明：{cv.chart_details}\n"
        )

    user_prompt = CORRECTION_USER_TEMPLATE.format(
        question_json=question_json,
        verification_details=verification.details,
        answer_block=answer_block,
        chart_details_block=chart_details_block,
    )

    try:
        if verification.chart_verification and chart_image_path:
            raw_text = client.generate_with_image(
                CORRECTION_SYSTEM_PROMPT, user_prompt, image_path=chart_image_path, purpose="correct"
            )
            corrected_data = extract_json(raw_text)
        else:
            corrected_data = client.generate_json(CORRECTION_SYSTEM_PROMPT, user_prompt, purpose="correct")
    except Exception:
        return question

    update: dict = {}

    if "題目" in corrected_data and isinstance(corrected_data["題目"], list):
        update["題目"] = corrected_data["題目"]

    if "正確解題分析" in corrected_data and isinstance(corrected_data["正確解題分析"], list):
        update["正確解題分析"] = corrected_data["正確解題分析"]

    if "文本" in corrected_data and isinstance(corrected_data["文本"], str):
        update["文本"] = corrected_data["文本"]

    # Allow correcting subquestion answers/rubrics, but preserve curriculum metadata
    if "subquestions" in corrected_data and isinstance(corrected_data["subquestions"], list):
        from src.social_studies.schemas import RubricEntry, SubQuestion
        new_sqs = []
        for i, sq_raw in enumerate(corrected_data["subquestions"]):
            if not isinstance(sq_raw, dict):
                continue
            original = question.subquestions[i] if i < len(question.subquestions) else None
            try:
                rubric = [
                    RubricEntry(
                        code=str(r.get("code", "")),
                        規準說明=r.get("規準說明", ""),
                        學生作答實例=r.get("學生作答實例", []),
                    )
                    for r in (sq_raw.get("評分規準") or sq_raw.get("評分標準") or [])
                    if isinstance(r, dict)
                ]
                sq = SubQuestion(
                    id=original.id if original else sq_raw.get("id", ""),
                    序號=original.序號 if original else sq_raw.get("序號", i + 1),
                    年級=original.年級 if original else sq_raw.get("年級", 0),
                    科目=original.科目 if original else sq_raw.get("科目", []),
                    核心素養=original.核心素養 if original else sq_raw.get("核心素養", []),
                    學習內容=original.學習內容 if original else [],
                    學習表現=original.學習表現 if original else [],
                    出題概念=original.出題概念 if original else sq_raw.get("出題概念", ""),
                    出題指示=original.出題指示 if original else sq_raw.get("出題指示"),
                    題型=original.題型 if original else sq_raw.get("題型", ""),
                    題目=sq_raw.get("題目", original.題目 if original else ""),
                    答案=sq_raw.get("答案", original.答案 if original else ""),
                    答案解析=sq_raw.get("答案解析", original.答案解析 if original else ""),
                    評分規準=rubric if rubric else (original.評分規準 if original else []),
                    題目內容類型=(
                        original.題目內容類型 if original else sq_raw.get("題目內容類型")
                    ),
                    image_generation_mode=(
                        original.image_generation_mode
                        if original else sq_raw.get("image_generation_mode")
                    ),
                    圖片=original.圖片 if original else sq_raw.get("圖片"),
                    chart_spec=original.chart_spec if original else None,
                )
                new_sqs.append(sq)
            except Exception:
                if original:
                    new_sqs.append(original)
        if new_sqs:
            update["subquestions"] = new_sqs

    raw_spec = corrected_data.get("image_spec") or corrected_data.get("chart_spec")
    if raw_spec and isinstance(raw_spec, dict):
        try:
            update["chart_spec"] = ImageSpec(**raw_spec)
        except Exception:
            pass

    update["verification"] = None

    return question.model_copy(update=update)
