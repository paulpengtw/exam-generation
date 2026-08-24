"""Issue #531: NS 小題-level chart_spec repair pass.

These tests exercise the real ``generate_one`` + ``sub_client_factory`` seam.
A subquestion generator that omits a required visual spec must be repaired once
by the main client before the existing image renderer runs.
"""

from __future__ import annotations

from pathlib import Path

from src.config import Config
from src.natural_sciences.cli import generate_one
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


class _IgnoringSubClient:
    """Return valid NS subquestions but deliberately omit chart_spec."""

    def set_observer(self, obs) -> None:
        del obs

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        del system, user, images, kwargs
        idx = int(agent_override.split("#")[1]) if agent_override else 1
        return {
            "序號": idx,
            "年級": 8,
            "科目": ["自然科學"],
            "科學能力": ["能力一：以科學的角度解釋現象"],
            "核心素養": [],
            "學習內容": [],
            "學習表現": [],
            "出題概念": "科學概念",
            "題型": "Simple multiple-choice",
            "題目": "題目（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "解析",
            "評分規準": [],
        }


class _MainClientWithRepair:
    """Return the text shell first, then a repair spec and a sentinel PNG."""

    def __init__(self) -> None:
        self._call_count = 0
        self.repair_calls: list[tuple[str, str]] = []
        self.image_calls: list[tuple[str, Path]] = []

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        del images
        self._call_count += 1
        if self._call_count == 1:
            return _TEXT_SHELL_THREE_SLOTS
        self.repair_calls.append((system, user))
        return {
            "chart_spec": {
                "render_mode": "gpt_image",
                "title": "修復圖",
                "description": "修復後的小題示意圖。",
                "data": {},
            }
        }

    def generate_image(self, prompt: str, output_path) -> str:
        path = Path(output_path)
        self.image_calls.append((prompt, path))
        path.write_bytes(b"repair-png-data")
        return str(path)


def _params(*, content_type: str, first_slot: dict):
    return sample_params(
        seed=1,
        content_type=content_type,
        sub_question_count=3,
        subquestion_configs=[first_slot, {}, {}],
    )


def test_ns_missing_visual_subquestion_spec_is_repaired_and_rendered(
    tmp_path: Path,
) -> None:
    """A required NS visual slot gets one repair call and reaches image rendering (#531)."""
    main_client = _MainClientWithRepair()
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=main_client,
        params=_params(
            content_type="純文字",
            first_slot={"content_type": "含圖片", "image_generation_mode": "gpt_image"},
        ),
        question_id="ns_repair_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _IgnoringSubClient(),
        image_generation_mode="gpt_image",
    )

    assert isinstance(question, ExamQuestion)
    assert len(main_client.repair_calls) == 1
    assert question.subquestions[0].chart_spec is not None
    assert question.subquestions[0].圖片 == "ns_repair_test_sq1.png"
    assert len(main_client.image_calls) == 1
    assert main_client.image_calls[0][0]
    assert main_client.image_calls[0][1] == tmp_path / "ns_repair_test_sq1.png"
    assert (tmp_path / "ns_repair_test_sq1.png").exists()


def test_ns_plain_text_subquestion_does_not_trigger_repair(tmp_path: Path) -> None:
    """A 純文字 NS slot does not trigger a chart_spec repair (#531)."""
    main_client = _MainClientWithRepair()
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=main_client,
        params=_params(content_type="純文字", first_slot={"content_type": "純文字"}),
        question_id="ns_plain_text_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _IgnoringSubClient(),
    )

    assert isinstance(question, ExamQuestion)
    assert main_client.repair_calls == []
    assert main_client.image_calls == []


def test_ns_image_mode_alone_does_not_trigger_repair(tmp_path: Path) -> None:
    """An image_generation_mode without a visual content type is not a repair trigger (#531)."""
    main_client = _MainClientWithRepair()
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=main_client,
        params=_params(
            content_type="純文字",
            first_slot={"image_generation_mode": "gpt_image"},
        ),
        question_id="ns_mode_only_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _IgnoringSubClient(),
    )

    assert isinstance(question, ExamQuestion)
    assert main_client.repair_calls == []
    assert main_client.image_calls == []


def test_ns_repair_failure_does_not_abort_question(tmp_path: Path) -> None:
    """A failed NS repair leaves the 題組 alive without an image (#531)."""

    class _FailingRepairClient(_MainClientWithRepair):
        def generate_json(self, system, user, images=None, **kwargs):
            del images
            self._call_count += 1
            if self._call_count == 1:
                return _TEXT_SHELL_THREE_SLOTS
            self.repair_calls.append((system, user))
            raise RuntimeError("simulated NS repair failure")

    main_client = _FailingRepairClient()
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=main_client,
        params=_params(
            content_type="純文字",
            first_slot={"content_type": "含圖片", "image_generation_mode": "gpt_image"},
        ),
        question_id="ns_repair_failure_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _IgnoringSubClient(),
        image_generation_mode="gpt_image",
    )

    assert isinstance(question, ExamQuestion)
    assert len(main_client.repair_calls) == 1
    assert question.subquestions[0].chart_spec is None
    assert main_client.image_calls == []
    assert not (tmp_path / "ns_repair_failure_test_sq1.png").exists()
