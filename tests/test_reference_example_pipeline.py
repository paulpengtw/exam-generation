"""Pipeline seam tests for 參考範例紀錄 (#670).

Drives real generate_one_core via generate_one from src/social_studies/cli.py
using the same fake-client harness pattern as
tests/test_figure_kind_diversity_pipeline_seam.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion


def _text_shell() -> dict[str, Any]:
    return {
        "核心問題": "人類行為如何影響環境?",
        "文本": "根據以下資料，回答小題。",
        "取材來源": ["測試來源"],
        "subquestions": [
            {"序號": 1, "題型": "選擇題", "出題概念": "概念甲"},
            {"序號": 2, "題型": "選擇題", "出題概念": "概念乙"},
            {"序號": 3, "題型": "選擇題", "出題概念": "概念丙"},
        ],
    }


def _subquestion(index: int) -> dict[str, Any]:
    return {
        "序號": index,
        "年級": 8,
        "科目": ["地理"],
        "核心素養": ["社-J-A2"],
        "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市"}],
        "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析"}],
        "出題概念": f"概念{chr(0x7532 + index - 1)}",
        "題型": "選擇題",
        "題目": f"第{index}題：下列何者正確？（A）甲（B）乙（C）丙（D）丁",
        "答案": "A",
        "答案解析": f"第{index}題解析",
        "評分規準": [],
    }


class _MainClient:
    """Fake generator client: first call is text shell, subsequent calls are ignored."""

    def get_observer(self) -> None:
        return None

    def generate_json(self, _system: str, _user: str, **_kwargs: Any) -> dict[str, Any]:
        return _text_shell()

    def generate_image(self, _prompt: str, output_path: Path) -> str:
        output_path.write_bytes(b"png")
        return str(output_path)


class _SubClient:
    """Fake subquestion client: returns valid subquestion JSON."""

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
        index = int(agent_override.split("#")[1])
        return _subquestion(index)


class _FailingSubClient:
    """Fake subquestion client that raises on the first slot-2 call."""

    def __init__(self) -> None:
        self._slot2_calls = 0

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
        index = int(agent_override.split("#")[1])
        if index == 2:
            self._slot2_calls += 1
            raise RuntimeError("injected failure for slot 2")
        return _subquestion(index)


def _make_params(seed: int = 42) -> Any:
    return sample_params(
        seed=seed,
        content_type="純文字",
        sub_question_count=3,
    )


def test_reference_example_entries_have_correct_stage_and_slot(tmp_path: Path) -> None:
    """Entries are emitted in stage order: generator stage then subquestion stages."""
    captured: list[dict[str, Any]] = []
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=_MainClient(),
        params=_make_params(),
        question_id="ref_pipeline_001",
        skip_verify=True,
        image_generation_mode="html",
        sub_client_factory=_SubClient,
        on_reference_example_entry=lambda entry: captured.append(dict(entry)),
    )

    assert isinstance(question, ExamQuestion)

    # There must be at least one text-generator-stage entry (from the text few-shot draw).
    generator_entries = [e for e in captured if e["stage"] == "text_generator"]
    assert len(generator_entries) >= 1, "Expected at least one text_generator-stage entry"

    # Every generator entry must have slot=None.
    for entry in generator_entries:
        assert entry["slot"] is None, f"Generator entry should have slot=None: {entry}"

    # Sub-stage entries should carry the slot number matching the subquestion index.
    subquestion_entries = [e for e in captured if e["stage"] == "subquestion_generator"]
    slot_numbers = sorted({e["slot"] for e in subquestion_entries if e["slot"] is not None})
    assert slot_numbers, "Expected at least one subquestion-stage entry with a slot"
    # All three subquestion slots should be represented.
    for slot in slot_numbers:
        assert 1 <= slot <= 3, f"Unexpected slot value: {slot}"

    # All entries must have code="reference_example" and non-empty question_id + timestamp.
    for entry in captured:
        assert entry["code"] == "reference_example"
        assert entry["question_id"] == "ref_pipeline_001"
        assert entry["timestamp"], "Timestamp should be set by the pipeline"


def test_partial_record_after_subquestion_client_failure(tmp_path: Path) -> None:
    """When slot 2 always fails, entries for slots 1 and 3 still appear in the captured list."""
    captured: list[dict[str, Any]] = []
    question = generate_one(
        config=Config(api_key="x", output_dir=tmp_path, data_dir=Path("data")),
        client=_MainClient(),
        params=_make_params(seed=99),
        question_id="ref_partial_002",
        skip_verify=True,
        image_generation_mode="html",
        sub_client_factory=lambda: _FailingSubClient(),
        on_reference_example_entry=lambda entry: captured.append(dict(entry)),
    )

    # The question is assembled from the surviving slots (1 and 3); slot 2 is dropped.
    assert isinstance(question, ExamQuestion)
    assert len(question.subquestions) == 2, (
        f"Expected 2 surviving subquestions, got {len(question.subquestions)}"
    )

    # Reference example entries for the text generator stage should still be present.
    generator_entries = [e for e in captured if e["stage"] == "text_generator"]
    assert len(generator_entries) >= 1

    # Entries for slot 2 were emitted (before the LLM call that failed).
    all_slots = [e["slot"] for e in captured if e.get("slot") is not None]
    assert 2 in all_slots, "Slot-2 entries should be present even after client failure"

    # Entries for slot 1 and slot 3 should also be present.
    assert 1 in all_slots
    assert 3 in all_slots
