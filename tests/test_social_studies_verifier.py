"""Tests for the social-studies verifier contract."""

from __future__ import annotations

import json

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.social_studies.schemas import ExamQuestion, QuestionMetadata
from src.social_studies.verifier import VERIFICATION_SYSTEM_PROMPT, verify_question


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.system_prompt = ""
        self.user_prompt = ""
        self.image_path: str | None = None

    def generate_with_image(self, system_prompt: str, user_prompt: str, image_path: str | None, purpose: str = "generate"):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.image_path = image_path
        return json.dumps(self.payload, ensure_ascii=False)


def _question() -> ExamQuestion:
    return ExamQuestion(
        id="ss-test",
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—說明文",
        題目=["閱讀文本後回答：作者支持哪一項政策？"],
        正確解題分析=["作者在第二段明確支持擴大公共運輸。"],
        metadata=QuestionMetadata(
            grade=8,
            model="fake-model",
        ),
    )


def test_social_studies_prompt_uses_lenient_pass_criteria() -> None:
    assert "寬鬆通過、只攔重大問題" in VERIFICATION_SYSTEM_PROMPT
    assert "小幅措辭、格式、詳略" in VERIFICATION_SYSTEM_PROMPT
    assert "仍可通過" in VERIFICATION_SYSTEM_PROMPT


def test_verify_question_accepts_semantically_equivalent_answer() -> None:
    client = FakeClient(
        {
            "my_answer": "作者支持增加大眾運輸。",
            "provided_answer": "作者支持擴大公共運輸。",
            "answer_match": True,
            "passed": True,
            "details": "語意一致，仍可通過。",
        }
    )

    result = verify_question(client, _question())

    assert result.passed is True
    assert result.answer_match is True
    assert "閱讀文本後回答" in client.user_prompt


def test_verify_question_preserves_clear_failure() -> None:
    client = FakeClient(
        {
            "my_answer": "文本支持擴大公共運輸。",
            "provided_answer": "文本支持取消所有公共運輸。",
            "answer_match": False,
            "passed": False,
            "details": "提供答案與文本明顯矛盾。",
        }
    )

    result = verify_question(client, _question())

    assert result.passed is False
    assert result.answer_match is False
    assert "明顯矛盾" in result.details


def test_social_studies_verifier_prompt_contains_illustrative_figure_leniency_line() -> None:
    assert "示意圖" in VERIFICATION_SYSTEM_PROMPT
    assert IMAGE_DISCLAIMER in VERIFICATION_SYSTEM_PROMPT
    assert "不得僅因" in VERIFICATION_SYSTEM_PROMPT
    assert "數值" in VERIFICATION_SYSTEM_PROMPT
    assert "標籤" in VERIFICATION_SYSTEM_PROMPT
