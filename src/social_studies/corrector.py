"""Correction pass for social studies questions.

NOTE: Like the verifier, this reuses math-style answer-match correction logic.
For rubric-graded items the correction target should be rubric conformance, not
a single answer match. Flagged as known gap in IMPLEMENTATION_PLAN.md.
"""

from __future__ import annotations

import json

from src.llm_client import LLMClient, extract_json
from src.social_studies.schemas import ExamQuestion, ImageSpec, VerificationResult

CORRECTION_SYSTEM_PROMPT = """\
你是一位PISA閱讀素養命題教師，剛收到審核老師對一道題組的意見回饋。
請根據審核意見「最小幅度」修正題目，保留所有正確的部分。

修正原則：
- **不要重寫整題**。只更正審核老師明確指出有問題的部分。
- 若問題在解題分析（答案錯誤或評分規準不清）→ 只修改 正確解題分析。
- 若問題在選項設計（答案不在選項中）→ 修正對應選項，必要時同步修正 正確解題分析。
- 若問題在文本素材或題目敘述歧義 → 最小幅度澄清，同步調整 正確解題分析。
- 若 chart_verification 指出非連續文本素材錯誤 → 只修正 chart_spec 的 data/labels/description，
  保留 render_mode、chart_type 不變。
- 絕對不可修改：情境、題型種類、題型、閱讀歷程、文本形式、id、metadata。

請輸出修正後完整的題目 JSON，格式與原題目相同。只輸出 JSON，不要輸出其他文字。
"""

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
                CORRECTION_SYSTEM_PROMPT, user_prompt, image_path=chart_image_path
            )
            corrected_data = extract_json(raw_text)
        else:
            corrected_data = client.generate_json(CORRECTION_SYSTEM_PROMPT, user_prompt)
    except Exception:
        return question

    update: dict = {}

    if "題目" in corrected_data and isinstance(corrected_data["題目"], list):
        update["題目"] = corrected_data["題目"]

    if "正確解題分析" in corrected_data and isinstance(corrected_data["正確解題分析"], list):
        update["正確解題分析"] = corrected_data["正確解題分析"]

    raw_spec = corrected_data.get("image_spec") or corrected_data.get("chart_spec")
    if raw_spec and isinstance(raw_spec, dict):
        try:
            update["chart_spec"] = ImageSpec(**raw_spec)
        except Exception:
            pass

    update["verification"] = None

    return question.model_copy(update=update)
