"""Verification pass for social studies questions.

NOTE: This verifier is copied from math and uses answer-match logic, which is
incorrect for rubric-graded 開放式建構反應題 (codes 2/1/0/9). A rubric_grade
scoring strategy will replace this once live examples demonstrate the gap.
See IMPLEMENTATION_PLAN.md "Known design risks" section.
"""

from __future__ import annotations

import json

from src.llm_client import LLMClient, extract_json
from src.social_studies.schemas import ChartVerificationResult, ExamQuestion, VerificationResult

VERIFICATION_SYSTEM_PROMPT = """\
你是一位PISA閱讀素養命題審核教師，負責審核考試題目的正確性。你會收到一道題組，請你：

1. 完全獨立地閱讀文本素材並回答每一道小題（不要看提供的解答）。
2. 將你的解答與提供的解答進行比較。
3. 檢查是否有以下問題：
   - 題目敘述有歧義或矛盾
   - 答案不一致或無法從文本中找到支持
   - 選項設計不合理（如正確答案不在選項中、誘答不具誘答力）
   - 開放式題目的評分規準不清楚或不公平
   - 非連續文本素材（如提供）與題目描述不符
4. 如果提供了圖表圖片，請一併檢查圖表是否正確呈現素材。

請以 JSON 格式回覆：

```json
{
  "my_answer": "你獨立解題後各題的答案（逐題說明）",
  "provided_answer": "題目提供的答案摘要",
  "answer_match": true/false,
  "passed": true/false,
  "details": "詳細說明（如有問題，指出具體位置）",
  "chart_verification": {
    "chart_data_match": true/false,
    "chart_labels_correct": true/false,
    "chart_details": "素材檢查說明"
  }
}
```

若題目未附圖表圖片，請省略 chart_verification 欄位。只輸出 JSON，不要輸出其他文字。
"""

VERIFICATION_USER_TEMPLATE = """\
請審核以下閱讀素養題組：

## 題組

{question_text}

## 提供的解題分析

{solution_text}
"""


def verify_question(
    client: LLMClient,
    question: ExamQuestion,
    chart_image_path: str | None = None,
) -> VerificationResult:
    question_text = "\n".join(question.題目)
    solution_text = "\n".join(question.正確解題分析)

    user_prompt = VERIFICATION_USER_TEMPLATE.format(
        question_text=question_text,
        solution_text=solution_text,
    )

    if chart_image_path is not None:
        user_prompt += (
            "\n\n## 附圖\n\n"
            "以下附上題目引用的素材圖片，請檢查素材內容與題目描述是否一致。"
        )

    try:
        raw = client.generate_with_image(
            VERIFICATION_SYSTEM_PROMPT, user_prompt, image_path=chart_image_path
        )
        result = extract_json(raw)

        chart_verif = None
        if "chart_verification" in result:
            cv = result["chart_verification"]
            chart_verif = ChartVerificationResult(
                chart_data_match=cv.get("chart_data_match", False),
                chart_labels_correct=cv.get("chart_labels_correct", False),
                chart_details=cv.get("chart_details", ""),
            )

        return VerificationResult(
            passed=result.get("passed", False),
            answer_match=result.get("answer_match", False),
            details=result.get("details", ""),
            my_answer=result.get("my_answer", ""),
            provided_answer=result.get("provided_answer", ""),
            chart_verification=chart_verif,
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        return VerificationResult(
            passed=False,
            answer_match=False,
            details=f"Verification failed to parse LLM response: {e}",
        )
