"""Teacher configuration stays with the planned slot through generation."""
from __future__ import annotations

import re
from importlib import import_module
from pathlib import Path

import pytest

from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE
from src.config import Config
from tests.test_figure_obligations_pipeline import FigureProvider, SubquestionProvider

CONTENT_PINS = {
    "social_studies": ["地Ac-Ⅳ-1", "地Ac-Ⅳ-2", "地Ad-Ⅳ-1"],
    "natural_sciences": ["Ab-Ⅳ-1", "Ab-Ⅳ-2", "Ab-Ⅳ-3"],
}

FIXED_IDS = [
    "slot-binding-sq001",
    "slot-binding-sq002",
    "slot-binding-sq003",
]


class PlanProvider(FigureProvider):
    def __init__(self, ordinals, subject):
        super().__init__()
        self.ordinals = ordinals
        self.question_type = "Simple multiple-choice" if subject == "natural_sciences" else "選擇題"

    def generate_json(self, *args, **kwargs):
        payload = super().generate_json(*args, **kwargs)
        if self.calls == 1:
            for row, ordinal in zip(payload["subquestions"], self.ordinals):
                row["序號"] = ordinal
                row["題型"] = self.question_type
        return payload


class SlotProvider(SubquestionProvider):
    def __init__(self, subject, ordinals, prompts, visual_slots):
        super().__init__(subject, visual_slots)
        self.ordinals = ordinals
        self.prompts = prompts

    def generate_json(self, system, user, **kwargs):
        match = re.search(r"\*\*出題概念\*\*：slot-(\d+)", user)
        assert match
        position = int(match.group(1))
        self.prompts[position] = user
        payload = super().generate_json(
            system, user, agent_override=f"sub_generator#{position}",
        )
        payload["序號"] = self.ordinals[position - 1]
        payload["出題指示"] = "model-default"
        if self.subject == "social_studies":
            payload["評分規準"] = [
                {
                    "code": "2",
                    "規準說明": EXTRA_ITEMS_FIXED_SENTENCE,
                    "學生作答實例": [f"slot-{position} 完整作答"],
                },
                {
                    "code": "1",
                    "規準說明": f"slot-{position} 部分作答",
                    "學生作答實例": [
                        f"slot-{position} 作答缺少一項",
                        f"slot-{position} 作答理由不足",
                    ],
                },
                {
                    "code": "0",
                    "規準說明": f"slot-{position} 未能作答",
                    "學生作答實例": [f"slot-{position} 錯誤作答"],
                },
            ]
        return payload


def run_slots(tmp_path, subject, *, plan_ordinals=(1, 2, 3), row_ordinals=(1, 2, 3),
              config_count=3, visual_slots=()):
    sampler = import_module(f"src.{subject}.sampler")
    cli = import_module(f"src.{subject}.cli")
    params = sampler.sample_params(
        grade=8, seed=554, content_type="純文字", sub_question_count=3,
        subquestion_configs=[
            {
                "instruction": f"teacher-slot-{i}", "learning_content": [code],
                **({"content_type": "含圖片", "image_generation_mode": "gpt_image"}
                   if i in visual_slots else {}),
            }
            for i, code in enumerate(CONTENT_PINS[subject], start=1)
        ],
    )
    params.subquestion_configs = params.subquestion_configs[:config_count]
    prompts = {}
    question = cli.generate_one(
        config=Config(api_key="test", output_dir=tmp_path, data_dir=Path("data")),
        client=PlanProvider(plan_ordinals, subject), params=params, question_id="slot-binding",
        skip_verify=True, disable_reference_fewshot=True,
        sub_client_factory=lambda: SlotProvider(subject, row_ordinals, prompts, visual_slots),
    )
    return question, prompts


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
def test_model_plan_ordinal_cannot_wrap_to_another_slots_configuration(tmp_path, subject):
    question, prompts = run_slots(tmp_path, subject, plan_ordinals=(0, 2, 3))

    assert [row.id for row in question.subquestions] == FIXED_IDS
    assert [row.學習內容[0].編碼 for row in question.subquestions] == CONTENT_PINS[subject]
    assert "teacher-slot-1" in prompts[1]
    assert "teacher-slot-3" not in prompts[1]


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
def test_duplicate_model_plan_ordinals_cannot_merge_two_planned_slots(tmp_path, subject):
    question, _ = run_slots(tmp_path, subject, plan_ordinals=(2, 2, 3))

    assert [row.id for row in question.subquestions] == FIXED_IDS
    assert [row.學習內容[0].編碼 for row in question.subquestions] == CONTENT_PINS[subject]


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
def test_duplicate_generated_ordinals_cannot_overwrite_another_slots_figure(tmp_path, subject):
    question, _ = run_slots(
        tmp_path, subject, row_ordinals=(2, 2, 3), visual_slots=(1, 2, 3),
    )

    assert [row.序號 for row in question.subquestions] == [1, 2, 3]
    assert [row.圖片 for row in question.subquestions] == [
        "slot-binding_sq1.png", "slot-binding_sq2.png", "slot-binding_sq3.png",
    ]
    assert [row.chart_spec.description for row in question.subquestions] == [
        "figure-for-slot-1", "figure-for-slot-2", "figure-for-slot-3",
    ]
    assert all((tmp_path / row.圖片).is_file() for row in question.subquestions)


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
@pytest.mark.parametrize("ordinals", [(0, 99, 99), (-1, 0, 1)])
def test_wrong_and_duplicate_generated_ordinals_keep_each_slots_pins(tmp_path, subject, ordinals):
    question, prompts = run_slots(tmp_path, subject, row_ordinals=ordinals)

    assert [row.id for row in question.subquestions] == FIXED_IDS
    assert [row.序號 for row in question.subquestions] == [1, 2, 3]
    assert [row.學習內容[0].編碼 for row in question.subquestions] == CONTENT_PINS[subject]
    for position in (1, 2, 3):
        assert f"teacher-slot-{position}" in prompts[position]


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
@pytest.mark.parametrize("config_count", [0, 1])
def test_slots_beyond_submitted_configuration_have_no_configuration(
    tmp_path, subject, config_count,
):
    question, prompts = run_slots(
        tmp_path, subject, plan_ordinals=(-1, 0, 99), config_count=config_count,
    )

    assert [row.id for row in question.subquestions] == FIXED_IDS
    if config_count:
        assert question.subquestions[0].學習內容[0].編碼 == CONTENT_PINS[subject][0]
        assert "teacher-slot-1" in prompts[1]
    for position in range(config_count + 1, 4):
        assert "teacher-slot-" not in prompts[position]
