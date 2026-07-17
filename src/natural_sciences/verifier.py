# ruff: noqa: E501
"""Verification pass for natural-sciences questions."""

from __future__ import annotations

import json

from src.common.distractor import validate_distractor_keys
from src.llm_client import LLMClient, extract_json
from src.natural_sciences.context_builder import (
    _CONTENT_TEXT,
    _PERFORMANCE_TEXT,
    _build_curriculum_section,
)
from src.natural_sciences.schemas import ChartVerificationResult, ExamQuestion, VerificationResult

_CURRICULUM_PREFIX: str = _build_curriculum_section(_CONTENT_TEXT, _PERFORMANCE_TEXT)

_VERIFICATION_SYSTEM_PROMPT_CORE = """\
你是一位 PISA Science 與108課綱自然科學領域命題審核教師，負責審核考試題組的可用性與明顯錯誤。你會收到一道題組，請你：

1. 完全獨立地閱讀科學情境素材並回答每一道小題（不要先看提供的解答）。
2. 將你的解答與提供的解答進行比較。
3. 檢查小題是否合理對應指定的 PISA Science 題型、科學能力、學習內容與學習表現。
4. 採取「寬鬆通過、只攔重大問題」的標準：
   - 如果提供的答案或解題分析能被素材與科學知識合理支持，即使措辭不同，也應視為通過。
   - 建構反應題可有多種合理回答；只要評分規準清楚、公平、能涵蓋合理答案，就應視為通過。
   - 小幅措辭、格式、誘答力不足但不影響作答的問題，請在 details 提醒，但不要因此判定 failed。
   - 只有在答案明顯無素材或科學依據、與素材矛盾、選項正解不存在、題目嚴重歧義、評分規準缺失或不公平時，才判定 failed。
5. 如果提供了圖表圖片，請檢查圖表是否正確呈現素材。

answer_match 的判斷也請寬鬆：
- 若你的答案與提供答案語意相同、可由相同素材與科學依據支持，或符合建構反應題評分規準，請回傳 true。
- 只有當提供答案與你的獨立判讀有實質衝突，且無法被素材合理支持時，才回傳 false。

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
請審核以下 PISA Science + 108課綱自然科學題組：

## 核心問題

{core_question}

## 文本素材

{passage_text}

## 各小題

{subquestions_text}

## 提供的解題分析（舊版格式備用）

{solution_text}
"""


def _build_question_text(question: ExamQuestion) -> tuple[str, str, str]:
    """Return (core_question, passage_text, subquestions_text)."""
    if question.subquestions:
        core_q = question.核心問題
        passage = question.文本
        sqs = []
        for sq in question.subquestions:
            lc = "、".join(f"{r.編碼}" for r in sq.學習內容)
            lp = "、".join(f"{r.編碼}" for r in sq.學習表現)
            competencies = "、".join(sq.科學能力)
            sqs.append(
                f"### 問題{sq.序號}（{sq.年級}年級 | {'/'.join(sq.科目)}）\n"
                f"科學能力：{competencies}\n"
                f"學習內容：{lc}\n"
                f"學習表現：{lp}\n"
                f"{sq.題目}\n"
                f"答案：{sq.答案}\n"
                f"答案解析：{sq.答案解析}"
            )
        return core_q, passage, "\n\n".join(sqs)
    parts = question.題目
    subquestions_text = "\n".join(parts[1:]) if len(parts) > 1 else "\n".join(parts)
    return "", parts[0] if parts else "", subquestions_text


def verify_question(
    client: LLMClient,
    question: ExamQuestion,
    chart_image_path: str | None = None,
) -> VerificationResult:
    core_q, passage_text, subquestions_text = _build_question_text(question)
    if not subquestions_text:
        subquestions_text = "\n".join(question.題目)
    solution_text = "\n".join(question.正確解題分析)

    user_prompt = VERIFICATION_USER_TEMPLATE.format(
        core_question=core_q,
        passage_text=passage_text,
        subquestions_text=subquestions_text,
        solution_text=solution_text,
    )

    if chart_image_path is not None:
        user_prompt += (
            "\n\n## 附圖\n\n"
            "以下附上題目引用的素材圖片，請檢查素材內容與題目描述是否一致。"
        )

    try:
        raw = client.generate_with_image(
            VERIFICATION_SYSTEM_PROMPT,
            user_prompt,
            image_path=chart_image_path,
            purpose="verify",
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

        all_warnings: list[str] = []
        for sq in question.subquestions:
            warnings = validate_distractor_keys(sq.題目, sq.誘答分析)
            for w in warnings:
                all_warnings.append(f"第{sq.序號}題：{w}")
        details = result.get("details", "")
        if all_warnings:
            details = details.rstrip()
            details += "\n\n[誘答分析提醒] " + "；".join(all_warnings)

        return VerificationResult(
            passed=result.get("passed", False),
            answer_match=result.get("answer_match", False),
            details=details,
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
