"""Two-pass verification: independently solve and compare answers."""

from __future__ import annotations

import json

from src.llm_client import LLMClient, extract_json
from src.schemas import ExamQuestion, VerificationResult

VERIFICATION_SYSTEM_PROMPT = """\
你是一位數學教師，負責審核考試題目的正確性。你會收到一道數學題目，請你：

1. 完全獨立地解這道題目（不要看提供的解答）。
2. 將你的解答與提供的解答進行比較。
3. 檢查是否有以下問題：
   - 數學計算錯誤
   - 邏輯推理錯誤
   - 答案不一致
   - 選項設計不合理（例如正確答案不在選項中）
   - 題目敘述有歧義或矛盾

請以 JSON 格式回覆：

```json
{
  "my_answer": "你獨立解題的答案",
  "provided_answer": "題目提供的答案",
  "answer_match": true/false,
  "passed": true/false,
  "details": "詳細說明（如有錯誤，指出具體問題）"
}
```

只輸出 JSON，不要輸出其他文字。
"""

VERIFICATION_USER_TEMPLATE = """\
請審核以下考試題目：

## 題目

{question_text}

## 提供的解題分析

{solution_text}
"""


def verify_question(client: LLMClient, question: ExamQuestion) -> VerificationResult:
    """Run a second LLM pass to independently verify the question and answer."""
    # Format the question for verification
    question_text = "\n".join(question.題目)
    solution_text = "\n".join(question.正確解題分析)

    user_prompt = VERIFICATION_USER_TEMPLATE.format(
        question_text=question_text,
        solution_text=solution_text,
    )

    try:
        raw = client.generate(VERIFICATION_SYSTEM_PROMPT, user_prompt)
        result = extract_json(raw)
        return VerificationResult(
            passed=result.get("passed", False),
            answer_match=result.get("answer_match", False),
            details=result.get("details", ""),
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        return VerificationResult(
            passed=False,
            answer_match=False,
            details=f"Verification failed to parse LLM response: {e}",
        )
