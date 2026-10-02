"""Figure obligations observed through the real public subject pipelines."""
from __future__ import annotations

import base64
from importlib import import_module
from pathlib import Path

import pytest

from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE
from src.config import Config

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a"
    "4e8AAAAASUVORK5CYII="
)


def _valid_open_response_rubric(index: int) -> list[dict[str, object]]:
    label = f"slot-{index}"
    return [
        {
            "code": "2",
            "規準說明": f"{label}完整推理。{EXTRA_ITEMS_FIXED_SENTENCE}",
            "學生作答實例": [f"{label}完整作答"],
        },
        {
            "code": "1",
            "規準說明": f"{label}推理鏈有缺口。",
            "學生作答實例": [f"{label}缺少證據", f"{label}理由未連結"],
        },
        {
            "code": "0",
            "規準說明": f"{label}方向錯誤。",
            "學生作答實例": [f"{label}錯誤作答"],
        },
    ]


class FigureProvider:
    def __init__(self):
        self.calls = 0
        self.images: dict[str, str] = {}
        self.events = []

    def get_observer(self):
        return self.events.append

    def generate_json(self, _system, _user, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "核心問題": "比較三個地點的觀察資料",
                "文本": "各地點的觀察資料已整理。",
                "subquestions": [{"序號": i, "出題概念": f"slot-{i}"} for i in (1, 2, 3)],
            }
        return {
            "chart_spec": {
                "render_mode": "gpt_image", "figure_kind": "流程圖",
                "description": "shared-figure",
            },
        }

    def generate_image(self, prompt, output_path):
        self.images[output_path.name] = prompt
        output_path.write_bytes(PNG)
        return str(output_path)


class SubquestionProvider:
    def __init__(self, subject, visual_slots=(), drop_first=False):
        self.subject = subject
        self.visual_slots = visual_slots
        self.drop_first = drop_first

    def set_observer(self, _observer):
        pass

    def generate_json(self, _system, _user, *, agent_override, **_kwargs):
        index = int(agent_override.split("#")[1])
        if self.drop_first and index == 1:
            return {"題目": ["unusable row"]}
        question_type = "Simple multiple-choice" if self.subject == "natural_sciences" else "選擇題"
        payload = {
            "id": f"slot-{index}", "序號": index, "題型": question_type,
            "題目": f"slot-{index} 的觀察結果為何？", "答案": "A", "答案解析": "依據資料。",
            "評分規準": _valid_open_response_rubric(index),
        }
        if index in self.visual_slots:
            payload["chart_spec"] = {
                "render_mode": "gpt_image", "figure_kind": f"slot-{index}-diagram",
                "description": f"figure-for-slot-{index}",
            }
        return payload


def run_pipeline(tmp_path, *, subject="natural_sciences", content_type="含圖片",
                 visual_slots=(), drop_first=False):
    sampler = import_module(f"src.{subject}.sampler")
    cli = import_module(f"src.{subject}.cli")
    params = sampler.sample_params(
        grade=8, seed=554, content_type=content_type, sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"}
            if index in visual_slots else {"image_generation_mode": "gpt_image"}
            for index in (1, 2, 3)
        ],
    )
    provider = FigureProvider()
    question = cli.generate_one(
        config=Config(api_key="test", output_dir=tmp_path, data_dir=Path("data")),
        client=provider, params=params, question_id="figure-obligations",
        skip_verify=True, disable_reference_fewshot=True, image_generation_mode="gpt_image",
        sub_client_factory=lambda: SubquestionProvider(subject, visual_slots, drop_first),
    )
    return question, provider


@pytest.mark.parametrize("subject", ["natural_sciences", "social_studies"])
@pytest.mark.parametrize("content_type", ["含圖片", "graphs/charts/tables"])
def test_group_visual_request_renders_one_shared_figure(tmp_path, subject, content_type):
    question, provider = run_pipeline(tmp_path, subject=subject, content_type=content_type)

    assert question.chart_spec is not None
    assert question.chart_spec.description == "shared-figure"
    assert question.圖片 == "figure-obligations.png"
    assert (tmp_path / question.圖片).read_bytes() == PNG
    assert list(provider.images) == ["figure-obligations.png"]
    assert all(sub.chart_spec is None and sub.圖片 is None for sub in question.subquestions)
    assert len(question.subquestions) == 3


@pytest.mark.parametrize("subject", ["natural_sciences", "social_studies"])
@pytest.mark.parametrize("content_type", ["純文字", "customized"])
def test_rendering_mode_without_visual_content_does_not_request_figures(
    tmp_path, subject, content_type,
):
    question, provider = run_pipeline(tmp_path, subject=subject, content_type=content_type)

    assert question.chart_spec is None
    assert question.圖片 is None
    assert all(sub.chart_spec is None and sub.圖片 is None for sub in question.subquestions)
    assert provider.images == {}
    assert provider.calls == 1


@pytest.mark.parametrize("subject", ["natural_sciences", "social_studies"])
@pytest.mark.parametrize("visual_slots", [(1, 2, 3), (1, 3)])
def test_dropping_first_slot_preserves_survivor_figure_obligations(
    tmp_path, subject, visual_slots,
):
    question, provider = run_pipeline(
        tmp_path, subject=subject, content_type="純文字",
        visual_slots=visual_slots, drop_first=True,
    )

    assert [sub.id for sub in question.subquestions] == [
        "figure-obligations-sq002",
        "figure-obligations-sq003",
    ]
    assert question.chart_spec is None
    assert question.圖片 is None
    assert "figure-obligations_sq1.png" not in provider.images
    for sub in question.subquestions:
        if sub.序號 in visual_slots:
            assert sub.圖片 == f"figure-obligations_sq{sub.序號}.png"
            assert (tmp_path / sub.圖片).read_bytes() == PNG
            assert f"figure-for-slot-{sub.序號}" in provider.images[sub.圖片]
        else:
            assert sub.chart_spec is None
            assert sub.圖片 is None
    assert len(provider.images) == (2 if visual_slots == (1, 2, 3) else 1)
