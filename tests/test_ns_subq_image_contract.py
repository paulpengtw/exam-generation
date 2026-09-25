"""Issue #530: NS 子題 image configuration must reach rendering end-to-end.

These tests exercise the real ``generate_one`` + ``sub_client_factory`` seam,
mirroring the social-studies contract tests from issue #319.
"""

from __future__ import annotations

from pathlib import Path

from server.config import ServerConfig
from server.generate.marshalling import question_to_event
from src.config import Config
from src.natural_sciences.cli import build_subquestion_prompt_previews, generate_one
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schemas import ExamQuestion

_TEXT_SHELL_THREE_SLOTS = {
    "核心問題": "測試核心問題",
    "文本": "測試文本素材",
    "取材來源": ["測試來源"],
    "subquestions": [
        {"序號": 1, "題型": "Simple multiple-choice", "出題概念": "概念一"},
        {"序號": 2, "題型": "Simple multiple-choice", "出題概念": "概念二"},
        {"序號": 3, "題型": "Simple multiple-choice", "出題概念": "概念三"},
    ],
}


class _FakeTextClient:
    def __init__(self) -> None:
        self.image_calls: list[tuple[str, Path]] = []

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        del system, user, images, kwargs
        return _TEXT_SHELL_THREE_SLOTS

    def generate_image(self, prompt: str, output_path) -> str:
        path = Path(output_path)
        self.image_calls.append((prompt, path))
        path.write_bytes(b"fake-png-data")
        return str(path)


class _CapturingSubClient:
    def __init__(self) -> None:
        self.captured_system = ""
        self.captured_user = ""

    def set_observer(self, obs) -> None:
        del obs

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        del images, kwargs
        idx = int(agent_override.split("#")[1]) if agent_override else 1
        if idx == 1:
            self.captured_system = system
            self.captured_user = user
        return {
            "序號": idx,
            "年級": 8,
            "科目": ["自然科學"],
            "科學能力": ["能力一：以科學的角度解釋現象"],
            "出題概念": "科學概念",
            "題型": "Simple multiple-choice",
            "題目": "題目（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "解析",
            "評分規準": [],
        }


class _SchemaFaithfulSubClient:
    """Emit a visual spec only when the prompt asks for one."""

    def set_observer(self, obs) -> None:
        del obs

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        del images, kwargs
        idx = int(agent_override.split("#")[1]) if agent_override else 1
        response: dict = {
            "序號": idx,
            "年級": 8,
            "科目": ["自然科學"],
            "科學能力": ["能力一：以科學的角度解釋現象"],
            "出題概念": "科學概念",
            "題型": "Simple multiple-choice",
            "題目": "根據圖1，以下何者正確？（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "解析",
            "評分規準": [],
        }
        if "chart_spec" in system and "題目內容類型=含圖片" in user:
            response.update(
                {
                    "題目內容類型": "含圖片",
                    "image_generation_mode": "gpt_image",
                    "chart_spec": {
                        "render_mode": "gpt_image",
                        "title": "測試用圖",
                        "description": "一張測試用圖片，請在下緣加上 caption。",
                        "data": {},
                    },
                }
            )
        return response


class _ReversedSchemaFaithfulSubClient(_SchemaFaithfulSubClient):
    """Return valid visual specs with model 序號 reversed from plan order."""

    _REPORTED_SEQUENCE = {1: 3, 2: 2, 3: 1}

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        response = super().generate_json(
            system,
            user,
            images=images,
            agent_override=agent_override,
            **kwargs,
        )
        plan_index = int(agent_override.split("#")[1]) if agent_override else 1
        response["序號"] = self._REPORTED_SEQUENCE[plan_index]
        return response


def _params(content_type: str, image_generation_mode: str = "gpt_image"):
    return sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {
                "content_type": content_type,
                "image_generation_mode": image_generation_mode,
            },
            {},
            {},
        ],
    )


def test_ns_subq_prompt_states_image_contract(tmp_path: Path) -> None:
    capture = _CapturingSubClient()
    params = _params("含圖片")

    generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=_FakeTextClient(),
        params=params,
        question_id="ns_contract_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: capture,
    )

    assert "chart_spec" in capture.captured_system
    assert "image_generation_mode" in capture.captured_system
    assert "小題圖片規則" in capture.captured_system
    assert "題目內容類型=含圖片" in capture.captured_user
    assert "圖片生成模式=gpt_image" in capture.captured_user
    assert "必須在本小題 JSON 中輸出非 null 的 `chart_spec`" in capture.captured_user


def test_ns_含圖片_slot_produces_png_when_model_follows_schema(tmp_path: Path) -> None:
    text_client = _FakeTextClient()
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=text_client,
        params=_params("含圖片"),
        question_id="ns_symptom_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SchemaFaithfulSubClient(),
        image_generation_mode="gpt_image",
    )

    assert isinstance(question, ExamQuestion)
    sq = question.subquestions[0]
    assert sq.chart_spec is not None
    assert sq.image_generation_mode == "gpt_image"
    assert sq.圖片 is not None
    assert len(text_client.image_calls) == 1
    assert text_client.image_calls[0][1] == tmp_path / "ns_symptom_test_sq1.png"
    assert (tmp_path / "ns_symptom_test_sq1.png").exists()
    payload = question_to_event(
        question,
        ServerConfig(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
    )
    assert payload["subquestions"][0]["image_base64"] == "ZmFrZS1wbmctZGF0YQ=="


def test_ns_image_generation_mode_alone_does_not_render_for_pure_text(
    tmp_path: Path,
) -> None:
    text_client = _FakeTextClient()
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=text_client,
        params=_params("純文字"),
        question_id="ns_mode_only_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _SchemaFaithfulSubClient(),
        image_generation_mode="gpt_image",
    )

    assert isinstance(question, ExamQuestion)
    assert question.subquestions[0].chart_spec is None
    assert text_client.image_calls == []
    assert not (tmp_path / "ns_mode_only_test_sq1.png").exists()


def test_ns_visual_subq_prompt_uses_inherited_image_generation_mode(
    tmp_path: Path,
) -> None:
    capture = _CapturingSubClient()
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[{"content_type": "含圖片"}, {}, {}],
    )

    generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=_FakeTextClient(),
        params=params,
        question_id="ns_inherited_mode_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: capture,
        image_generation_mode="gpt_image",
    )

    assert "題目內容類型=含圖片" in capture.captured_user
    assert "圖片生成模式=gpt_image" in capture.captured_user


def test_ns_subq_rendering_uses_plan_slot_for_misnumbered_model_output(
    tmp_path: Path,
) -> None:
    text_client = _FakeTextClient()
    params = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {"content_type": "含圖片", "image_generation_mode": "html"},
            {"content_type": "含圖片", "image_generation_mode": "html"},
        ],
    )

    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=text_client,
        params=params,
        question_id="ns_plan_index_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _ReversedSchemaFaithfulSubClient(),
        image_generation_mode="html",
    )

    assert isinstance(question, ExamQuestion)
    by_sequence = {sub.序號: sub for sub in question.subquestions}
    # The program-owned 序號 is fixed to the plan slot even when the model
    # reports the reverse order; image placement still follows _plan_index.
    assert by_sequence[1].image_generation_mode == "gpt_image"
    assert by_sequence[1].圖片 == "ns_plan_index_test_sq1.png"
    assert by_sequence[3].image_generation_mode == "html"
    assert by_sequence[3].圖片 == "ns_plan_index_test_sq3.png"


def test_ns_subq_prompt_preview_shows_configured_image_requirement(tmp_path: Path) -> None:
    previews = build_subquestion_prompt_previews(
        Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        _params("含圖片"),
        disable_reference_fewshot=True,
    )

    _, system, user, _ = previews[0]
    assert "chart_spec" in system
    assert "小題圖片規則" in system
    assert "題目內容類型=含圖片" in user
    assert "圖片生成模式=gpt_image" in user
    assert "必須在本小題 JSON 中輸出非 null 的 `chart_spec`" in user
