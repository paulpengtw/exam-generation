"""Issue #320: 小題-level chart_spec repair pass.

TDD red → green: tests at the sub_client_factory + generate_one seam.

A stage-2 sub_client that ignores the image instruction and returns no chart_spec
should trigger exactly one repair call (on the main client) per 含圖片 slot.
The repaired chart_spec must be adopted and the image endpoint must receive a payload.
No repair for 純文字 小題; no repair when only image_generation_mode is set;
repair failure must NOT abort the 題組.
"""

from __future__ import annotations

from pathlib import Path

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion

# ---------------------------------------------------------------------------
# Shared fake text-shell (returned by the main client on its first call)
# ---------------------------------------------------------------------------

_TEXT_SHELL_THREE_SLOTS = {
    "核心問題": "測試核心問題",
    "文本": "測試文本素材",
    "取材來源": ["測試來源"],
    "subquestions": [
        {"序號": 1, "題型": "選擇題", "出題概念": "概念一"},
        {"序號": 2, "題型": "選擇題", "出題概念": "概念二"},
        {"序號": 3, "題型": "選擇題", "出題概念": "概念三"},
    ],
}

# ---------------------------------------------------------------------------
# Stage-2 fake: ignores image instruction, never returns chart_spec
# ---------------------------------------------------------------------------


class _IgnoringSubClient:
    """Stage-2 fake — always returns a valid 小題 but never emits chart_spec."""

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#")[1]) if agent_override else 1
        return {
            "序號": idx,
            "年級": 8,
            "科目": ["地理"],
            "核心素養": ["社-J-A2"],
            "學習內容": [{"編碼": "地Af-Ⅳ-3", "說明": "都市發展"}],
            "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "解析"}],
            "出題概念": "概念",
            "題型": "選擇題",
            "題目": "題目（A）甲（B）乙（C）丙（D）丁",
            "答案": "A",
            "答案解析": "解析",
            "評分規準": [],
            # Deliberately no chart_spec — the "ignoring" behaviour
        }


# ---------------------------------------------------------------------------
# Main client: call 1 = text shell; call 2+ = repaired chart_spec
# ---------------------------------------------------------------------------


class _MainClientWithRepair:
    """Main client: first generate_json returns the text shell; subsequent
    calls are repair requests and return a synthetic chart_spec.
    generate_image writes a sentinel PNG.
    """

    def __init__(self) -> None:
        self._call_count = 0
        self.repair_calls: list[tuple[str, str]] = []

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        self._call_count += 1
        if self._call_count == 1:
            return _TEXT_SHELL_THREE_SLOTS
        # Any subsequent call is a repair call
        self.repair_calls.append((system, user))
        return {
            "chart_spec": {
                "render_mode": "html",
                "title": "修復圖",
                "description": "修復後的小題示意圖。",
                "data": {},
            }
        }

    def generate_image(self, prompt: str, output_path) -> str:
        Path(output_path).write_bytes(b"repair-png-data")
        return str(output_path)


# ---------------------------------------------------------------------------
# Test 1 — repair is triggered exactly once and its chart_spec is adopted
# ---------------------------------------------------------------------------


def test_missing_sq_chart_spec_triggers_repair_once(tmp_path: Path) -> None:
    """A 含圖片 小題 without chart_spec triggers exactly one repair call (#320).

    RED before fix:
      _ss_render_subquestion_images does not call _ensure_subquestion_visual_spec
      → no repair call → main_client.repair_calls == 0 → assertion fails.
    """
    params = sample_params(
        seed=1,
        content_type="純文字",  # top-level stays plain text → no top-level repair
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {},
            {},
        ],
    )
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    main_client = _MainClientWithRepair()

    question = generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="repair_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _IgnoringSubClient(),
        image_generation_mode="gpt_image",
    )

    assert isinstance(question, ExamQuestion)
    assert len(main_client.repair_calls) == 1, (
        f"Expected exactly 1 repair call, got {len(main_client.repair_calls)}"
    )
    sq = question.subquestions[0]
    assert sq.chart_spec is not None, "Repaired chart_spec must be adopted onto the 小題"
    assert sq.圖片 is not None, "PNG filename must be set after rendering"
    assert (tmp_path / "repair_test_sq1.png").exists(), (
        "PNG file must be written to disk for the 含圖片 小題"
    )


# ---------------------------------------------------------------------------
# Test 2 — no repair for 純文字 小題
# ---------------------------------------------------------------------------


def test_no_repair_for_plain_text_subquestion(tmp_path: Path) -> None:
    """No repair call when 小題 content_type is 純文字 (#320)."""
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "純文字"},
            {},
            {},
        ],
    )
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    main_client = _MainClientWithRepair()

    generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="no_repair_text_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _IgnoringSubClient(),
    )

    assert main_client.repair_calls == [], (
        "No repair should be triggered for 純文字 小題"
    )


# ---------------------------------------------------------------------------
# Test 3 — no repair when only image_generation_mode is set (not content_type)
# ---------------------------------------------------------------------------


def test_no_repair_when_only_image_generation_mode_set(tmp_path: Path) -> None:
    """No repair when only image_generation_mode is set without a visual content_type (#320)."""
    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {"image_generation_mode": "gpt_image"},  # mode only — no content_type
            {},
            {},
        ],
    )
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    main_client = _MainClientWithRepair()

    generate_one(
        config=config,
        client=main_client,
        params=params,
        question_id="mode_only_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _IgnoringSubClient(),
    )

    assert main_client.repair_calls == [], (
        "No repair should be triggered when only image_generation_mode is set"
    )


# ---------------------------------------------------------------------------
# Test 4 — repair failure degrades gracefully; 題組 is not aborted
# ---------------------------------------------------------------------------


def test_repair_failure_does_not_abort_question(tmp_path: Path) -> None:
    """Repair failure must degrade gracefully — 小題 ships without image, no abort (#320)."""

    class _FailingRepairClient:
        def __init__(self) -> None:
            self._call_count = 0

        def get_observer(self):
            return None

        def generate_json(self, system, user, images=None, **kwargs):
            self._call_count += 1
            if self._call_count == 1:
                return _TEXT_SHELL_THREE_SLOTS
            raise RuntimeError("Simulated repair failure")

    params = sample_params(
        seed=1,
        content_type="純文字",
        sub_question_count=3,
        subquestion_configs=[
            {"content_type": "含圖片", "image_generation_mode": "gpt_image"},
            {},
            {},
        ],
    )
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))

    # Must not raise
    question = generate_one(
        config=config,
        client=_FailingRepairClient(),
        params=params,
        question_id="fail_repair_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _IgnoringSubClient(),
        image_generation_mode="gpt_image",
    )

    assert isinstance(question, ExamQuestion), (
        "題組 must be returned even when repair fails"
    )
    sq = question.subquestions[0]
    assert sq.chart_spec is None, "chart_spec must remain None when repair fails"
    assert not (tmp_path / "fail_repair_test_sq1.png").exists(), (
        "No PNG should be written when repair fails"
    )
