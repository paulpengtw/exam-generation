"""Tests for the social-studies verifier contract."""

from __future__ import annotations

import json
import types

from src.common.image_disclaimer import IMAGE_DISCLAIMER
from src.social_studies.schemas import (
    ExamQuestion,
    FactCheckResult,
    LearningContentRef,
    QuestionMetadata,
    SubQuestion,
)
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


def test_verify_question_threads_chart_image_path_and_prompts_附圖(tmp_path) -> None:
    """When a chart image path is provided, verify_question must:
       (a) pass it through as `image_path` to the client, and
       (b) inject the 「## 附圖」 section into the user prompt."""
    png_path = tmp_path / "chart.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n")  # bytes irrelevant; FakeClient does not read

    client = FakeClient(
        {
            "my_answer": "作者支持擴大公共運輸。",
            "provided_answer": "作者支持擴大公共運輸。",
            "answer_match": True,
            "passed": True,
            "details": "素材圖片與文本一致。",
            "chart_verification": {
                "chart_data_match": True,
                "chart_labels_correct": True,
                "chart_details": "圖表標籤與題目描述一致。",
            },
        }
    )

    result = verify_question(client, _question(), chart_image_path=str(png_path))

    assert client.image_path == str(png_path)
    assert "## 附圖" in client.user_prompt
    assert result.chart_verification is not None
    assert result.chart_verification.chart_data_match is True


def _question_with_公民_subquestion() -> "ExamQuestion":  # noqa: F821 — re-uses import
    return ExamQuestion(
        id="ss-fact-test",
        核心問題="說明近年地方治理趨勢。",
        文本="根據2024年公開資料…",
        subquestions=[
            SubQuestion(
                id="ss-fact-test-01",
                序號=1,
                年級=9,
                科目=["公民與社會"],
                核心素養=[],
                學習內容=[LearningContentRef(編碼="公Ba-Ⅳ-3", 說明="")],
                學習表現=[],
                題型="選擇題",
                題目="題幹",
                答案="A",
            )
        ],
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—說明文",
        題目=["文本", "題幹"],
        正確解題分析=["A"],
        metadata=QuestionMetadata(grade=9, model="fake-model"),
    )


class FactCheckClient(FakeClient):
    """FakeClient with a configurable Config and fact_check hook."""

    def __init__(self, payload: dict, provider: str = "anthropic", max_uses: int = 5) -> None:
        super().__init__(payload)
        self.config = types.SimpleNamespace(
            web_search_provider=provider,
            web_search_max_uses=max_uses,
        )


def test_verify_skips_fact_check_when_provider_disabled(monkeypatch) -> None:
    called = {"n": 0}

    def _spy(*args, **kwargs):
        called["n"] += 1
        return FactCheckResult(verified=False, issues=["should not run"])

    monkeypatch.setattr("src.social_studies.verifier.fact_check_question", _spy)

    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "通過。",
        },
        provider="none",
    )
    result = verify_question(client, _question_with_公民_subquestion())
    assert result.passed is True
    assert result.fact_check is None
    assert called["n"] == 0


def test_verify_skips_fact_check_when_question_is_not_current_events(monkeypatch) -> None:
    called = {"n": 0}

    def _spy(*args, **kwargs):
        called["n"] += 1
        return None

    monkeypatch.setattr("src.social_studies.verifier.fact_check_question", _spy)

    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "通過。",
        },
        provider="anthropic",
    )
    result = verify_question(client, _question())  # non-時事 question from top of file
    assert result.fact_check is None
    assert called["n"] == 0


def test_verify_runs_fact_check_and_forces_fail_on_contradiction(monkeypatch) -> None:
    fake_result = FactCheckResult(
        verified=False,
        citations=["https://gov.tw/report"],
        issues=["文本聲稱2024年台北市長為某某，實際為另一人。"],
    )

    def _spy(client, question, *, provider, max_uses):
        assert provider == "anthropic"
        assert max_uses == 5
        return fake_result

    monkeypatch.setattr("src.social_studies.verifier.fact_check_question", _spy)

    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "教師端通過。",
        },
        provider="anthropic",
    )
    result = verify_question(client, _question_with_公民_subquestion())
    assert result.passed is False
    assert result.fact_check == fake_result
    assert "事實查證未通過" in result.details
    assert "文本聲稱2024年台北市長為某某" in result.details


def test_verify_keeps_pass_when_fact_check_verifies(monkeypatch) -> None:
    fake_result = FactCheckResult(verified=True, citations=["https://gov.tw/x"], issues=[])
    monkeypatch.setattr(
        "src.social_studies.verifier.fact_check_question",
        lambda *a, **kw: fake_result,
    )
    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "教師端通過。",
        },
        provider="anthropic",
    )
    result = verify_question(client, _question_with_公民_subquestion())
    assert result.passed is True
    assert result.fact_check == fake_result
    assert result.details == "教師端通過。"


def test_verify_leaves_details_untouched_when_fact_check_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.social_studies.verifier.fact_check_question",
        lambda *a, **kw: None,
    )
    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "教師端通過。",
        },
        provider="anthropic",
    )
    result = verify_question(client, _question_with_公民_subquestion())
    assert result.passed is True
    assert result.fact_check is None
    assert result.details == "教師端通過。"


def test_verify_question_tolerates_null_chart_verification() -> None:
    """LLM may emit an explicit null for chart_verification on text-only (純文字) questions
    despite the prompt asking to omit the field entirely; the verifier must not crash."""
    client = FakeClient(
        {
            "my_answer": "作者支持擴大公共運輸。",
            "provided_answer": "作者支持擴大公共運輸。",
            "answer_match": True,
            "passed": True,
            "details": "通過。",
            "chart_verification": None,
        }
    )

    result = verify_question(client, _question())

    assert result.passed is True
    assert result.chart_verification is None


def test_social_studies_verifier_prompt_contains_illustrative_figure_leniency_line() -> None:
    assert "示意圖" in VERIFICATION_SYSTEM_PROMPT
    assert IMAGE_DISCLAIMER in VERIFICATION_SYSTEM_PROMPT
    assert "不得僅因" in VERIFICATION_SYSTEM_PROMPT
    assert "數值" in VERIFICATION_SYSTEM_PROMPT
    assert "標籤" in VERIFICATION_SYSTEM_PROMPT
