"""Two-pass verification: independently solve and compare answers."""

from __future__ import annotations

import json

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.context_builder import (
    _CONTENT_TEXT,
    _PERFORMANCE_INTRO,
    _PERFORMANCE_TEXT,
    _build_curriculum_section,
)
from src.llm_client import LLMClient, extract_json
from src.schemas import ChartVerificationResult, ExamQuestion, VerificationResult

_CURRICULUM_PREFIX: str = _build_curriculum_section(
    _CONTENT_TEXT, _PERFORMANCE_TEXT, _PERFORMANCE_INTRO
)

_VERIFICATION_SYSTEM_PROMPT_CORE = f"""\
你是一位數學教師，負責審核考試題目的正確性。你會收到一道數學題目，請你：

1. 完全獨立地解這道題目（不要看提供的解答）。
2. 將你的解答與提供的解答進行比較。
3. 檢查是否有以下問題：
   - 數學計算錯誤
   - 邏輯推理錯誤
   - 答案不一致
   - 選項設計不合理（例如正確答案不在選項中）
   - 題目敘述有歧義或矛盾
4. 如果提供了圖表圖片，請一併檢查圖表是否正確呈現題目所描述的數據。

## 示意圖判讀原則

附上的圖表為示意圖（{IMAGE_DISCLAIMER}）。
不得僅因圖形比例、線段長度、角度、軸距或版面留白不完全符合實際尺寸而判定 failed；
但若圖表中的數值、標籤、單位、分類、資料點或關鍵標示錯誤，或與題目描述矛盾，仍應判定 failed。

請以 JSON 格式回覆：

```json
{{
  "my_answer": "你獨立解題的答案",
  "provided_answer": "題目提供的答案",
  "answer_match": true/false,
  "passed": true/false,
  "details": "詳細說明（如有錯誤，指出具體問題）",
  "chart_verification": {{
    "chart_data_match": true/false,
    "chart_labels_correct": true/false,
    "chart_details": "圖表檢查說明"
  }}
}}
```

若題目未附圖表圖片，請省略 chart_verification 欄位。只輸出 JSON，不要輸出其他文字。
"""

VERIFICATION_SYSTEM_PROMPT = (
    f"{_CURRICULUM_PREFIX}\n\n---\n\n{_VERIFICATION_SYSTEM_PROMPT_CORE}"
    if _CURRICULUM_PREFIX
    else _VERIFICATION_SYSTEM_PROMPT_CORE
)

VERIFICATION_USER_TEMPLATE = """\
請審核以下考試題目：

## 題目

{question_text}

## 提供的解題分析

{solution_text}
"""


def verify_question(
    client: LLMClient,
    question: ExamQuestion,
    chart_image_path: str | None = None,
    curriculum_context: str | None = None,
) -> VerificationResult:
    """Run a second LLM pass to independently verify the question and answer."""
    question_text = "\n".join(question.題目)
    solution_text = "\n".join(question.正確解題分析)

    user_prompt = VERIFICATION_USER_TEMPLATE.format(
        question_text=question_text,
        solution_text=solution_text,
    )

    if chart_image_path is not None:
        user_prompt += (
            "\n\n## 附圖\n\n"
            "以下附上題目引用的圖表圖片，請檢查圖表數據與題目描述是否一致。"
        )

    system = (
        f"{curriculum_context}\n\n---\n\n{VERIFICATION_SYSTEM_PROMPT}"
        if curriculum_context
        else VERIFICATION_SYSTEM_PROMPT
    )

    try:
        raw = client.generate_with_image(
            system, user_prompt, image_path=chart_image_path, purpose="verify"
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
