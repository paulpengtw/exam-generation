"""Correction pass: apply verifier feedback to minimally fix a failed question."""

from __future__ import annotations

import json

from src.llm_client import LLMClient, extract_json
from src.schemas import ExamQuestion, ImageSpec, VerificationResult

CORRECTION_SYSTEM_PROMPT = """\
你是一位數學教師，剛剛收到審核老師對一道考試題目的意見回饋。
請根據審核意見「最小幅度」修正題目，保留所有正確的部分。

修正原則：
- **不要重寫整題**。只更正審核老師明確指出有問題的部分。
- 若問題在「正確解題分析」（計算或推理錯誤）→ 只修改 正確解題分析。
- 若問題在「選項設計」或「答案不在選項中」→ 修正對應選項，必要時同步修正 正確解題分析。
- 若問題在「題目敘述歧義」→ 最小幅度澄清 題目，並同步調整 正確解題分析。
- 若 chart_verification 指出圖表錯誤 → 只修正 image_spec/chart_spec 的 data/labels，
  保留 description、title、render_mode、chart_type 不變（除非審核明確要求）。
- 絕對不可修改：情境、題型種類、題型、數學思考、學習內容、id、metadata。

請輸出修正後完整的題目 JSON，格式與原題目相同（含所有原欄位）。只輸出 JSON，不要輸出其他文字。
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
    """Apply verification feedback to produce a minimally corrected question.

    Only 題目, 正確解題分析, and chart_spec may be updated; all classification
    and metadata fields are restored from the original regardless of LLM output.
    Returns the original question unchanged if the LLM output cannot be parsed.
    """
    # Serialize without ephemeral fields so the corrector sees clean source
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
            f"\n## 圖表審核意見\n"
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
        # Use multimodal when chart has issues and PNG exists
        if verification.chart_verification and chart_image_path:
            raw_text = client.generate_with_image(
                CORRECTION_SYSTEM_PROMPT, user_prompt, image_path=chart_image_path, purpose="correct"
            )
            corrected_data = extract_json(raw_text)
        else:
            corrected_data = client.generate_json(CORRECTION_SYSTEM_PROMPT, user_prompt, purpose="correct")
    except Exception:
        return question  # fall back to original on any LLM/parse error

    # Safely merge: only update fields the corrector is allowed to change
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
            pass  # keep original chart_spec on parse failure

    # Restore all frozen fields from original and clear stale verification
    update["verification"] = None

    return question.model_copy(update=update)
