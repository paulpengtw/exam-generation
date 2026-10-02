"""Regression coverage for visual slot identity across accepted corrections."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from src.common.correction_decision import CorrectionDecision
from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE
from src.config import Config
from src.natural_sciences.cli import generate_with_corrections
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schemas import ExamQuestion, ImageSpec

_TEXT_SHELL = {
    "核心問題": "測試核心問題",
    "文本": "測試文本素材",
    "取材來源": ["測試來源"],
    "subquestions": [
        {"序號": 1, "題型": "Simple multiple-choice", "出題概念": "概念一"},
        {"序號": 2, "題型": "Simple multiple-choice", "出題概念": "概念二"},
        {"序號": 3, "題型": "Simple multiple-choice", "出題概念": "概念三"},
    ],
    "chart_spec": {
        "render_mode": "html",
        "figure_kind": "原始題幹",
        "description": "原始題幹圖片",
    },
}


class _ControlledMainClient:
    """Return one draft, one accepted correction, and two verifier verdicts."""

    def __init__(self, learning_content: list[str], learning_performance: list[str]) -> None:
        self.learning_content = learning_content
        self.learning_performance = learning_performance
        self.generate_calls: list[str] = []
        self.image_paths: list[str] = []
        self.html_calls = 0
        self.verify_calls = 0

    def get_observer(self) -> None:
        return None

    def generate_json(self, _system: str, _user: str, **kwargs: Any) -> dict[str, Any]:
        purpose = kwargs.get("purpose", "generate")
        self.generate_calls.append(purpose)
        if purpose == "generate":
            return _TEXT_SHELL
        assert purpose == "correct"
        return {
            "chart_spec": {
                "render_mode": "html",
                "figure_kind": "修正後題幹",
                "description": "修正後題幹圖片",
            },
            "subquestions": [
                {
                    "id": "visual-pin-slot-1",
                    "序號": 2,
                    "題目": "修正後槽位一題目",
                    "答案": "A",
                    "答案解析": "修正後槽位一解析",
                    "評分規準": [],
                    "誘答分析": {},
                },
                {
                    "id": "visual-pin-slot-2",
                    "序號": 1,
                    "題目": "修正後槽位二題目",
                    "答案": "A",
                    "答案解析": "修正後槽位二解析",
                    "評分規準": [],
                    "誘答分析": {},
                },
                {
                    "id": "visual-pin-slot-3",
                    "序號": 3,
                    "題目": "修正後槽位三題目",
                    "答案": "A",
                    "答案解析": "修正後槽位三解析",
                    "評分規準": [],
                    "誘答分析": {},
                },
            ],
        }

    def generate_with_image(
        self,
        _system: str,
        _user: str,
        *,
        image_path: str | Path | None = None,
        purpose: str = "generate",
    ) -> str:
        assert purpose == "verify"
        assert image_path is not None
        self.verify_calls += 1
        return json.dumps(
            {
                "passed": self.verify_calls > 1,
                "answer_match": self.verify_calls > 1,
                "details": "controlled verdict",
            }
        )

    def generate(self, _system: str, _user: str, *, purpose: str = "generate") -> str:
        assert purpose == "html_image"
        self.html_calls += 1
        return "<!DOCTYPE html><html><body>controlled image</body></html>"

    def generate_image(self, _prompt: str, output_path: str | Path) -> str:
        path = Path(output_path)
        self.image_paths.append(path.name)
        path.write_bytes(b"controlled-png")
        return str(path)


class _ControlledHtmlRenderer:
    """Browser boundary adapter that writes deterministic PNGs."""

    def __init__(self) -> None:
        self.output_paths: list[str] = []

    def render(self, _html: str, output_path: str | Path) -> str:
        path = Path(output_path)
        self.output_paths.append(path.name)
        path.write_bytes(b"controlled-png")
        return str(path)


class _ControlledSubClient:
    """Return chart specs for the first two slots with swapped model ordinals."""

    def __init__(self, learning_content: list[str], learning_performance: list[str]) -> None:
        self.learning_content = learning_content
        self.learning_performance = learning_performance

    def set_observer(self, _observer: Any) -> None:
        pass

    def generate_json(
        self,
        _system: str,
        _user: str,
        *,
        agent_override: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        plan_slot = int(agent_override.split("#")[1])
        reported_ordinal = {1: 2, 2: 1, 3: 3}[plan_slot]
        response: dict[str, Any] = {
            "id": f"visual-pin-slot-{plan_slot}",
            "序號": reported_ordinal,
            "年級": 8,
            "科目": ["自然科學"],
            "科學能力": ["能力一：以科學的角度解釋現象"],
            "學習內容": [
                {"編碼": code, "說明": "測試學習內容"}
                for code in self.learning_content
            ],
            "學習表現": [
                {"編碼": code, "說明": "測試學習表現"}
                for code in self.learning_performance
            ],
            "出題概念": f"計畫槽位{plan_slot}的概念",
            "題型": "Simple multiple-choice",
            "題目": f"原始槽位{plan_slot}題目",
            "答案": "A",
            "答案解析": "原始解析",
            "評分規準": [],
        }
        if plan_slot in (1, 2):
            response["chart_spec"] = {
                "render_mode": "html",
                "figure_kind": f"槽位{plan_slot}圖片",
                "description": f"槽位{plan_slot}圖片",
            }
        return response


def test_accepted_top_spec_correction_preserves_visual_slot_pins(
    tmp_path: Path,
) -> None:
    """A top-spec correction keeps each swapped-ordinal item's visual slot identity."""
    params = sample_params(
        grade=8,
        content_type="含圖片",
        sub_question_count=3,
        subquestion_configs=[
            {
                "question_type": "Simple multiple-choice",
                "content_type": "含圖片",
                "image_generation_mode": "html",
                "figure_kind": "槽位1圖片",
            },
            {
                "question_type": "Simple multiple-choice",
                "content_type": "含圖片",
                "image_generation_mode": "gpt_image",
                "figure_kind": "槽位2圖片",
            },
            {
                "question_type": "Simple multiple-choice",
                "content_type": "純文字",
            },
        ],
    )
    main_client = _ControlledMainClient(
        params.學習內容_pool,
        params.學習表現_pool,
    )
    html_renderer = _ControlledHtmlRenderer()
    question = generate_with_corrections(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=main_client,
        params=params,
        question_id="visual_pin_correction",
        max_retries=1,
        disable_reference_fewshot=True,
        html_renderer=html_renderer,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _ControlledSubClient(
            params.學習內容_pool,
            params.學習表現_pool,
        ),
    )

    assert isinstance(question, ExamQuestion)
    assert question.chart_spec is not None
    assert question.chart_spec.figure_kind == "修正後題幹"
    assert question.圖片 == "visual_pin_correction.png"
    assert question.verification is not None and question.verification.passed is True
    assert main_client.generate_calls == ["generate", "correct"]
    assert main_client.verify_calls == 2

    by_id = {sub.id: sub for sub in question.subquestions}
    assert {
        sub_id: (sub.圖片, sub.image_generation_mode)
        for sub_id, sub in by_id.items()
    } == {
        "visual_pin_correction-sq001": ("visual_pin_correction_sq1.png", "html"),
        "visual_pin_correction-sq002": ("visual_pin_correction_sq2.png", "gpt_image"),
        "visual_pin_correction-sq003": (None, None),
    }
    assert main_client.image_paths.count("visual_pin_correction.png") == 2
    assert main_client.image_paths.count("visual_pin_correction_sq2.png") == 2
    assert html_renderer.output_paths.count("visual_pin_correction_sq1.png") == 2


def test_accepted_correction_reapplies_pins_and_scrubs_pure_text_visual(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.natural_sciences.cli as natural_sciences_cli

    params = sample_params(
        grade=8,
        content_type="含圖片",
        sub_question_count=3,
        subquestion_configs=[
            {
                "question_type": "Simple multiple-choice",
                "content_type": "含圖片",
                "image_generation_mode": "html",
                "figure_kind": "槽位1圖片",
            },
            {
                "question_type": "Simple multiple-choice",
                "content_type": "含圖片",
                "image_generation_mode": "gpt_image",
                "figure_kind": "槽位2圖片",
            },
            {
                "question_type": "Simple multiple-choice",
                "content_type": "純文字",
                "image_generation_mode": "gpt_image",
            },
        ],
    )

    def adversarial_accepted_correction(
        _client: Any,
        question: ExamQuestion,
        _verification: Any,
        *,
        on_decision: Any,
        **_kwargs: Any,
    ) -> ExamQuestion:
        candidate = question.model_copy(deep=True)
        for position, subquestion in enumerate(candidate.subquestions, start=1):
            subquestion.id = f"model-owned-{position}"
            subquestion.序號 = 99
            subquestion.題型 = "Constructed response"
            subquestion.題目內容類型 = "含圖片"
            subquestion.image_generation_mode = "gpt_image"
            subquestion.圖片 = f"model-owned-{position}.png"
            subquestion.chart_spec = ImageSpec(
                render_mode="gpt_image" if position != 1 else "html",
                figure_kind=f"槽位{position}圖片",
                description=f"修正後槽位{position}圖片",
                data={},
            )
        candidate.verification = None
        on_decision(CorrectionDecision(outcome="accepted"))
        return candidate

    monkeypatch.setattr(
        natural_sciences_cli,
        "_NS_SPEC",
        dataclasses.replace(
            natural_sciences_cli._NS_SPEC,
            correct_fn=adversarial_accepted_correction,
        ),
    )
    main_client = _ControlledMainClient(
        params.學習內容_pool,
        params.學習表現_pool,
    )
    html_renderer = _ControlledHtmlRenderer()

    question = generate_with_corrections(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=main_client,
        params=params,
        question_id="visual_pin_adversarial_correction",
        max_retries=1,
        disable_reference_fewshot=True,
        html_renderer=html_renderer,
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _ControlledSubClient(
            params.學習內容_pool,
            params.學習表現_pool,
        ),
    )

    assert isinstance(question, ExamQuestion)
    assert [sub.id for sub in question.subquestions] == [
        "visual_pin_adversarial_correction-sq001",
        "visual_pin_adversarial_correction-sq002",
        "visual_pin_adversarial_correction-sq003",
    ]
    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3]
    assert [sub._plan_index for sub in question.subquestions] == [1, 2, 3]
    assert [sub.題型.value for sub in question.subquestions] == [
        "Simple multiple-choice",
        "Simple multiple-choice",
        "Simple multiple-choice",
    ]
    pure_text = question.subquestions[2]
    assert pure_text.題目內容類型 == "純文字"
    assert pure_text.chart_spec is None
    assert pure_text.圖片 is None
    assert pure_text.image_generation_mode == "gpt_image"
    assert "visual_pin_adversarial_correction_sq3.png" not in main_client.image_paths
    assert "visual_pin_adversarial_correction_sq3.png" not in html_renderer.output_paths
    assert main_client.image_paths.count(
        "visual_pin_adversarial_correction_sq2.png"
    ) == 2
    assert html_renderer.output_paths.count(
        "visual_pin_adversarial_correction_sq1.png"
    ) == 2


def test_correction_contract_rejects_invalid_open_response_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.natural_sciences.cli as natural_sciences_cli

    params = sample_params(
        grade=8,
        content_type="含圖片",
        sub_question_count=3,
        subquestion_configs=[
            {"question_type": "Simple multiple-choice", "content_type": "純文字"},
            {"question_type": "Simple multiple-choice", "content_type": "純文字"},
            {"question_type": "Constructed response", "content_type": "純文字"},
        ],
    )

    class _OpenResponseThirdSubClient(_ControlledSubClient):
        def generate_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            response = super().generate_json(*args, **kwargs)
            plan_slot = int(kwargs["agent_override"].split("#")[1])
            if plan_slot == 3:
                response["題型"] = "Constructed response"
                response["評分規準"] = [
                    {
                        "code": "2",
                        "規準說明": f"完整推理。{EXTRA_ITEMS_FIXED_SENTENCE}",
                        "學生作答實例": ["完整回答"],
                    },
                    {
                        "code": "1",
                        "規準說明": "推理有兩種缺口。",
                        "學生作答實例": ["缺少證據", "連結錯誤"],
                    },
                    {
                        "code": "0",
                        "規準說明": "方向錯誤。",
                        "學生作答實例": ["錯誤觀念"],
                    },
                ]
            return response

    def invalid_accepted_correction(
        _client: Any,
        question: ExamQuestion,
        _verification: Any,
        *,
        on_decision: Any,
        **_kwargs: Any,
    ) -> ExamQuestion:
        candidate = question.model_copy(deep=True)
        candidate.subquestions[0].題目 = "this rejected edit must not ship"
        candidate.subquestions[2].評分規準 = []
        candidate.verification = None
        on_decision(CorrectionDecision(outcome="accepted"))
        return candidate

    monkeypatch.setattr(
        natural_sciences_cli,
        "_NS_SPEC",
        dataclasses.replace(
            natural_sciences_cli._NS_SPEC,
            correct_fn=invalid_accepted_correction,
        ),
    )
    main_client = _ControlledMainClient(
        params.學習內容_pool,
        params.學習表現_pool,
    )
    trail: list[Any] = []

    question = generate_with_corrections(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=main_client,
        params=params,
        question_id="visual_pin_rejected_contract",
        max_retries=1,
        disable_reference_fewshot=True,
        html_renderer=_ControlledHtmlRenderer(),
        image_generation_mode="gpt_image",
        sub_client_factory=lambda: _OpenResponseThirdSubClient(
            params.學習內容_pool,
            params.學習表現_pool,
        ),
        on_trail_entry=trail.append,
    )

    assert isinstance(question, ExamQuestion)
    assert question.subquestions[0].題目 == "原始槽位1題目"
    correction = next(entry for entry in trail if entry.kind == "correction")
    assert correction.outcome == "rejected"
    assert correction.reason is not None
    assert correction.reason.code == "fixed_slot_contract"
    assert correction.reason.path == "subquestions[2]"
    assert "評分規準" in correction.reason.message
