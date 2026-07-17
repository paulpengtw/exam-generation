"""Verification pass for social studies questions."""

from __future__ import annotations

import json

from src.llm_client import LLMClient, extract_json
from src.social_studies.context_builder import _build_curriculum_section, _CONTENT_TEXT, _PERFORMANCE_TEXT, _PERFORMANCE_INTRO
from src.social_studies.schemas import ChartVerificationResult, ExamQuestion, VerificationResult

_CURRICULUM_PREFIX: str = _build_curriculum_section(_CONTENT_TEXT, _PERFORMANCE_TEXT, _PERFORMANCE_INTRO)

_VERIFICATION_SYSTEM_PROMPT_CORE = """\
你是一位108課綱社會領域素養導向命題審核教師，負責審核考試題組的可用性與明顯錯誤。你會收到一道題組，請你：

1. 完全獨立地閱讀文本素材並回答每一道小題（不要看提供的解答）。
2. 將你的解答與提供的解答進行比較。
3. 採取「寬鬆通過、只攔重大問題」的標準：
   - 如果提供的答案或解題分析能被文本合理支持，即使你的答案措辭不同，也應視為通過。
   - 開放式題目可有多種合理回答；只要評分規準（rubric）清楚、公平、能涵蓋合理答案，就應視為通過。
   - 小幅措辭、格式、詳略、誘答力不足但不影響作答的問題，請在 details 提醒，但不要因此判定 failed。
   - 只有在答案明顯無文本支持、與文本矛盾、選項正解不存在、題目嚴重歧義、評分規準缺失或不公平時，才判定 failed。
4. 如果提供了圖表圖片，請一併檢查圖表是否正確呈現素材。
   - 圖表或非連續文本有輕微標籤/排版問題但仍可理解時，請提醒但不要 failed。
   - 圖表資料明顯錯誤、缺少作答必要資訊，或與題目描述矛盾時，才 failed。

answer_match 的判斷也請寬鬆：
- 若你的答案與提供答案語意相同、可由相同文本依據支持，或符合開放式題目的評分規準，請回傳 true。
- 只有當提供答案與你的獨立判讀有實質衝突，且無法被文本合理支持時，才回傳 false。

請以 JSON 格式回覆：

```json
{
  "my_answer": "你獨立解題後各題的答案（逐題說明）",
  "provided_answer": "題目提供的答案摘要",
  "answer_match": true/false,
  "passed": true/false,
  "details": "詳細說明；若只是小幅改善建議，請明確寫出仍可通過",
  "chart_verification": {
    "chart_data_match": true/false,
    "chart_labels_correct": true/false,
    "chart_details": "素材檢查說明"
  }
}
```

若題目未附圖表圖片，請省略 chart_verification 欄位。只輸出 JSON，不要輸出其他文字。
"""

VERIFICATION_SYSTEM_PROMPT = (
    f"{_CURRICULUM_PREFIX}\n\n---\n\n{_VERIFICATION_SYSTEM_PROMPT_CORE}"
    if _CURRICULUM_PREFIX
    else _VERIFICATION_SYSTEM_PROMPT_CORE
)

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
            sqs.append(
                f"### 問題{sq.序號}（{sq.年級}年級 | {'/'.join(sq.科目)}）\n"
                f"學習內容：{lc}\n"
                f"{sq.題目}\n"
                f"答案：{sq.答案}\n"
                f"答案解析：{sq.答案解析}"
            )
        return core_q, passage, "\n\n".join(sqs)
    # Fallback for legacy flat format
    parts = question.題目
    return "", parts[0] if parts else "", "\n".join(parts[1:]) if len(parts) > 1 else "\n".join(parts)


def verify_question(
    client: LLMClient,
    question: ExamQuestion,
    chart_image_path: str | None = None,
) -> VerificationResult:
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

    try:
        raw = client.generate_with_image(
            VERIFICATION_SYSTEM_PROMPT, user_prompt, image_path=chart_image_path, purpose="verify"
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
