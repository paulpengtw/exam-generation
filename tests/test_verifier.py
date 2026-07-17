"""Tests for the math verifier's multimodal payload wiring."""

from __future__ import annotations

import json

from src.schemas import ExamQuestion, LearningContentItem
from src.verifier import verify_question


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.system_prompt = ""
        self.user_prompt = ""
        self.image_path: str | None = None

    def generate_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: str | None = None,
        purpose: str = "generate",
    ) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.image_path = image_path
        return json.dumps(self.payload, ensure_ascii=False)


def _math_question() -> ExamQuestion:
    return ExamQuestion(
        id="math-test",
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數的加減乘除")],
        題目=["下列哪一個數字最大？(A) 1 (B) 2 (C) 3 (D) 4"],
        正確解題分析=["最大的是 4，故選 D。"],
    )


def test_math_verifier_threads_chart_image_path_and_prompts_附圖(tmp_path) -> None:
    """When chart_image_path is given, the math verifier must pass it to the
    client and inject the 「## 附圖」 section into the user prompt."""
    png_path = tmp_path / "chart.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    client = FakeClient(
        {
            "my_answer": "D",
            "provided_answer": "D",
            "answer_match": True,
            "passed": True,
            "details": "答案一致，圖表無誤。",
            "chart_verification": {
                "chart_data_match": True,
                "chart_labels_correct": True,
                "chart_details": "圖表資料與題目一致。",
            },
        }
    )

    result = verify_question(client, _math_question(), chart_image_path=str(png_path))

    assert client.image_path == str(png_path)
    assert "## 附圖" in client.user_prompt
    assert result.passed is True
    assert result.chart_verification is not None
    assert result.chart_verification.chart_data_match is True


def test_math_verifier_omits_附圖_when_no_image(tmp_path) -> None:
    """Without a chart_image_path, the client must be called with image_path=None
    and 「## 附圖」 must not appear in the user prompt."""
    client = FakeClient(
        {
            "my_answer": "D",
            "provided_answer": "D",
            "answer_match": True,
            "passed": True,
            "details": "無圖題，答案正確。",
        }
    )

    result = verify_question(client, _math_question())

    assert client.image_path is None
    assert "## 附圖" not in client.user_prompt
    assert result.passed is True
