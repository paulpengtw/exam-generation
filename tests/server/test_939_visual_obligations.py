"""Regression tests for issue #939 — visual obligation contract.

Six-slot NS scenario:
  slots 1, 2, 4, 6  – chart_spec set, 圖片 set, valid PNG on disk → delivered
  slot 3             – chart_spec set, render failed (圖片=None, no file)
                       → missing reason="render_failed"
  slot 5             – chart_spec set, render returned path but file is 0 bytes
                       → missing reason="empty_image"

Acceptance criteria verified:
  A1. Every requested visual slot is represented in expected.
  A2. Empty (0-byte) image is NOT counted as delivered.
  A3. Missing visual has structured per-slot reason and delivery_status="partial".
  A4. Sibling subquestions survive an unrelated slot failure.
  A5. delivery_status is "partial" (not "complete") when any image slot is missing.
  A6. reason field distinguishes render_failed from empty_image.
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace
from typing import Any

import pytest

from server.generate.question_terminal import (
    _compute_delivery_status,
    _compute_expected_delivered_missing,
    _QuestionPositionResolution,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chart_spec() -> SimpleNamespace:
    return SimpleNamespace(render_mode="chart")


def _subquestion(
    sq_id: str,
    *,
    chart_spec: Any = None,
    圖片: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=sq_id,
        chart_spec=chart_spec,
        image_spec=None,
        圖片=圖片,
    )


def _flat_params(
    sub_question_count: int | None = None,
    subquestion_configs: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        skip_verify=False,
        sub_question_count=sub_question_count,
        subquestion_configs=subquestion_configs,
    )


def _config_with_visual(content_type: str = "含圖片") -> SimpleNamespace:
    return SimpleNamespace(content_type=content_type, figure_kind=None)


def _config_text_only() -> SimpleNamespace:
    return SimpleNamespace(content_type="純文字", figure_kind=None)


def _announced_slot(index: int, question_id: str) -> dict[str, Any]:
    return {
        "subquestion_index": index,
        "id": f"{question_id}-sq{index + 1:03d}",
        "序號": index + 1,
    }


# ---------------------------------------------------------------------------
# Main scenario: 6-slot NS visual question
# ---------------------------------------------------------------------------

QUESTION_ID = "q_NS_RUN_001"
SLOT_COUNT = 6


@pytest.fixture()
def output_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Scratch directory with real PNG files for slots 1, 2, 4, 6."""
    # Slots that succeed: 1 (index 0), 2 (index 1), 4 (index 3), 6 (index 5)
    for sq_no in (1, 2, 4, 6):
        p = tmp_path / f"{QUESTION_ID}_sq{sq_no}.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # fake non-empty PNG
    # Slot 5 (index 4): 0-byte file exists on disk
    p5 = tmp_path / f"{QUESTION_ID}_sq5.png"
    p5.write_bytes(b"")  # empty file
    # Slot 3 (index 2): no file (render failed, 圖片 stays None)
    return tmp_path


@pytest.fixture()
def six_slot_question(output_dir: pathlib.Path) -> SimpleNamespace:
    """Build a question with 6 subquestions matching the scenario."""
    sqs = []
    for idx in range(SLOT_COUNT):
        sq_no = idx + 1
        sq_id = f"{QUESTION_ID}-sq{sq_no:03d}"
        spec = _chart_spec()
        if sq_no == 3:
            # render failed – chart_spec set but 圖片 not set
            sq = _subquestion(sq_id, chart_spec=spec, 圖片=None)
        elif sq_no == 5:
            # render returned a path but file is 0-bytes
            sq = _subquestion(sq_id, chart_spec=spec, 圖片=f"{QUESTION_ID}_sq5.png")
        else:
            sq = _subquestion(
                sq_id,
                chart_spec=spec,
                圖片=f"{QUESTION_ID}_sq{sq_no}.png",
            )
        sqs.append(sq)

    return SimpleNamespace(
        chart_spec=None,
        image_spec=None,
        圖片=None,
        verification=None,
        subquestions=sqs,
    )


@pytest.fixture()
def six_slot_configs() -> list[SimpleNamespace]:
    return [_config_with_visual() for _ in range(SLOT_COUNT)]


@pytest.fixture()
def resolution(six_slot_configs: list[SimpleNamespace]) -> _QuestionPositionResolution:
    announced = [_announced_slot(i, QUESTION_ID) for i in range(SLOT_COUNT)]
    return _QuestionPositionResolution(
        announced_slots=announced,
        verification_trail=None,
        resolved_subquestion_configs=six_slot_configs,
        resolved_subquestion_count=SLOT_COUNT,
        has_per_question_resolution=True,
    )


# ---------------------------------------------------------------------------
# A1 — All 6 image slots appear in expected
# ---------------------------------------------------------------------------

class TestVisualObligations:
    """A1–A6 acceptance criteria for the six-slot NS scenario."""

    def test_a1_all_six_image_slots_in_expected(
        self,
        six_slot_question: SimpleNamespace,
        resolution: _QuestionPositionResolution,
        output_dir: pathlib.Path,
    ) -> None:
        """A1: Every visual slot is represented in expected."""
        params = _flat_params(sub_question_count=SLOT_COUNT)
        expected, delivered, missing = _compute_expected_delivered_missing(
            question_id=QUESTION_ID,
            question=six_slot_question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        image_slots = [s for s in expected if s["kind"] == "image"]
        assert len(image_slots) == SLOT_COUNT, (
            f"Expected {SLOT_COUNT} image slots in expected, got {len(image_slots)}"
        )

    def test_a2_empty_image_is_not_delivered(
        self,
        six_slot_question: SimpleNamespace,
        resolution: _QuestionPositionResolution,
        output_dir: pathlib.Path,
    ) -> None:
        """A2: Slot 5's 0-byte file must NOT appear in delivered."""
        params = _flat_params(sub_question_count=SLOT_COUNT)
        _expected, delivered, _missing = _compute_expected_delivered_missing(
            question_id=QUESTION_ID,
            question=six_slot_question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        delivered_sq_ids = {
            s["subquestion_id"]
            for s in delivered
            if s["kind"] == "image"
        }
        sq5_id = f"{QUESTION_ID}-sq005"
        assert sq5_id not in delivered_sq_ids, (
            f"Slot 5 ({sq5_id}) with 0-byte file must not be in delivered"
        )

    def test_a3_missing_slots_produce_partial_delivery_status(
        self,
        six_slot_question: SimpleNamespace,
        resolution: _QuestionPositionResolution,
        output_dir: pathlib.Path,
    ) -> None:
        """A3: delivery_status='partial' when any image slot is missing."""
        params = _flat_params(sub_question_count=SLOT_COUNT)
        _expected, _delivered, missing = _compute_expected_delivered_missing(
            question_id=QUESTION_ID,
            question=six_slot_question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        delivery_status = _compute_delivery_status(
            has_final=True,
            termination_reason="normal",
            missing=missing,
        )
        assert delivery_status == "partial", (
            f"Expected delivery_status='partial' but got '{delivery_status}'"
        )
        assert len(missing) >= 2, (
            f"Expected at least 2 missing slots, got {len(missing)}"
        )

    def test_a4_sibling_slots_intact(
        self,
        six_slot_question: SimpleNamespace,
        resolution: _QuestionPositionResolution,
        output_dir: pathlib.Path,
    ) -> None:
        """A4: Slots 1, 2, 4, 6 are delivered; 3, 5 are missing."""
        params = _flat_params(sub_question_count=SLOT_COUNT)
        _expected, delivered, missing = _compute_expected_delivered_missing(
            question_id=QUESTION_ID,
            question=six_slot_question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        delivered_sq_ids = {
            s["subquestion_id"] for s in delivered if s["kind"] == "image"
        }
        missing_sq_ids = {
            s["subquestion_id"] for s in missing if s["kind"] == "image"
        }

        # Slots 1, 2, 4, 6 should be delivered
        for sq_no in (1, 2, 4, 6):
            sq_id = f"{QUESTION_ID}-sq{sq_no:03d}"
            assert sq_id in delivered_sq_ids, (
                f"Slot {sq_no} ({sq_id}) should be delivered but is not"
            )
        # Slots 3, 5 should be missing
        for sq_no in (3, 5):
            sq_id = f"{QUESTION_ID}-sq{sq_no:03d}"
            assert sq_id in missing_sq_ids, (
                f"Slot {sq_no} ({sq_id}) should be missing but is not"
            )

    def test_a5_delivery_status_not_complete_with_missing_images(
        self,
        six_slot_question: SimpleNamespace,
        resolution: _QuestionPositionResolution,
        output_dir: pathlib.Path,
    ) -> None:
        """A5: delivery_status is never 'complete' when image slots are missing."""
        params = _flat_params(sub_question_count=SLOT_COUNT)
        _expected, _delivered, missing = _compute_expected_delivered_missing(
            question_id=QUESTION_ID,
            question=six_slot_question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        delivery_status = _compute_delivery_status(
            has_final=True,
            termination_reason="normal",
            missing=missing,
        )
        assert delivery_status != "complete"

    def test_a6_reason_distinguishes_render_failed_from_empty_image(
        self,
        six_slot_question: SimpleNamespace,
        resolution: _QuestionPositionResolution,
        output_dir: pathlib.Path,
    ) -> None:
        """A6: missing slots have structured per-slot reasons.

        Slot 3: render failed (圖片=None) → reason='render_failed'
        Slot 5: 0-byte file → reason='empty_image'
        """
        params = _flat_params(sub_question_count=SLOT_COUNT)
        _expected, _delivered, missing = _compute_expected_delivered_missing(
            question_id=QUESTION_ID,
            question=six_slot_question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        missing_by_id = {
            s["subquestion_id"]: s
            for s in missing
            if s["kind"] == "image"
        }

        sq3_id = f"{QUESTION_ID}-sq003"
        sq5_id = f"{QUESTION_ID}-sq005"

        assert sq3_id in missing_by_id, f"Slot 3 missing from missing list: {missing}"
        assert sq5_id in missing_by_id, f"Slot 5 missing from missing list: {missing}"

        assert missing_by_id[sq3_id]["reason"] == "render_failed", (
            f"Slot 3 reason should be 'render_failed', got {missing_by_id[sq3_id]['reason']!r}"
        )
        assert missing_by_id[sq5_id]["reason"] == "empty_image", (
            f"Slot 5 reason should be 'empty_image', got {missing_by_id[sq5_id]['reason']!r}"
        )

    def test_a6_explicitly_visual_no_spec_uses_spec_missing_reason(
        self,
        output_dir: pathlib.Path,
    ) -> None:
        """A6 extended: explicitly-visual slot with no chart_spec → reason='spec_missing'."""
        # One subquestion with content_type="含圖片" but chart_spec=None (LLM didn't emit it)
        sq_id = "q_TEST-sq001"
        sq = SimpleNamespace(
            id=sq_id,
            chart_spec=None,
            image_spec=None,
            圖片=None,
        )
        question = SimpleNamespace(
            chart_spec=None,
            image_spec=None,
            圖片=None,
            verification=None,
            subquestions=[sq],
        )
        config = SimpleNamespace(content_type="含圖片", figure_kind=None)
        announced = [{"subquestion_index": 0, "id": sq_id, "序號": 1}]
        res = _QuestionPositionResolution(
            announced_slots=announced,
            verification_trail=None,
            resolved_subquestion_configs=[config],
            resolved_subquestion_count=1,
            has_per_question_resolution=True,
        )
        params = SimpleNamespace(
            skip_verify=False, sub_question_count=1, subquestion_configs=[config]
        )
        _expected, _delivered, missing = _compute_expected_delivered_missing(
            question_id="q_TEST",
            question=question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=res,
        )
        image_missing = [s for s in missing if s["kind"] == "image"]
        assert len(image_missing) == 1
        assert image_missing[0]["reason"] == "spec_missing", (
            f"Expected 'spec_missing' got {image_missing[0]['reason']!r}"
        )


# ---------------------------------------------------------------------------
# Bonus: subquestion ordering preserved after mixed failures
# ---------------------------------------------------------------------------

class TestSubquestionOrderPreserved:
    """Sibling subquestion slots preserve manifest order regardless of image fate."""

    def test_subquestion_slots_in_manifest_order(
        self,
        six_slot_question: SimpleNamespace,
        resolution: _QuestionPositionResolution,
        output_dir: pathlib.Path,
    ) -> None:
        params = _flat_params(sub_question_count=SLOT_COUNT)
        expected, _delivered, _missing = _compute_expected_delivered_missing(
            question_id=QUESTION_ID,
            question=six_slot_question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        subquestion_slots = [s for s in expected if s["kind"] == "subquestion"]
        indices = [s["subquestion_index"] for s in subquestion_slots]
        assert indices == sorted(indices), (
            f"Subquestion slots not in manifest order: {indices}"
        )
        assert len(subquestion_slots) == SLOT_COUNT


# ---------------------------------------------------------------------------
# History persistence: terminal delivery stored in annotations_json (issue #939)
# ---------------------------------------------------------------------------

class TestHistoryPersistenceTerminalDelivery:
    """Verify that missing-slot state is correctly pre-computed for History records.

    These tests exercise the *same* _compute_expected_delivered_missing +
    _compute_delivery_status path that service.py calls before persist_generation_record,
    checking that:
    - A complete question (all images delivered) produces delivery_status="complete".
    - A partial question (some images missing) produces delivery_status="partial".
    - The missing list round-trips through a plain dict (as annotations_json stores it).
    """

    def test_complete_question_produces_complete_delivery_status(
        self,
        output_dir: pathlib.Path,
    ) -> None:
        """A question with all images delivered produces delivery_status='complete'."""
        q_id = "q_HIST_COMPLETE"
        # One subquestion with a valid PNG on disk
        sq_id = f"{q_id}-sq001"
        png_path = output_dir / f"{q_id}_sq1.png"
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        sq = SimpleNamespace(
            id=sq_id,
            chart_spec=_chart_spec(),
            image_spec=None,
            圖片=f"{q_id}_sq1.png",
        )
        question = SimpleNamespace(
            chart_spec=None,
            image_spec=None,
            圖片=None,
            verification=None,
            subquestions=[sq],
        )
        config = _config_with_visual()
        announced = [{"subquestion_index": 0, "id": sq_id, "序號": 1}]
        resolution = _QuestionPositionResolution(
            announced_slots=announced,
            verification_trail=None,
            resolved_subquestion_configs=[config],
            resolved_subquestion_count=1,
            has_per_question_resolution=True,
        )
        params = _flat_params(sub_question_count=1, subquestion_configs=[config])
        _expected, _delivered, missing = _compute_expected_delivered_missing(
            question_id=q_id,
            question=question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        delivery_status = _compute_delivery_status(
            has_final=True,
            termination_reason="normal",
            missing=missing,
        )
        assert delivery_status == "complete"
        assert missing == []
        # Simulate what annotations_json stores and verify round-trip
        annotations: dict = {
            "terminal_delivery": {
                "delivery_status": delivery_status,
                "missing": missing,
                "termination_reason": "normal",
            }
        }
        assert annotations["terminal_delivery"]["delivery_status"] == "complete"
        assert annotations["terminal_delivery"]["missing"] == []

    def test_partial_question_missing_subquestion_slot(
        self,
        output_dir: pathlib.Path,
    ) -> None:
        """A question with a dropped subquestion produces delivery_status='partial'.

        This is the NS/SS case from issue #937: one 子題 slot fails to generate.
        The slot is in expected but not delivered → missing.
        """
        q_id = "q_HIST_PARTIAL_SQ"
        sq_id_delivered = f"{q_id}-sq001"
        sq_id_missing = f"{q_id}-sq002"
        png_path = output_dir / f"{q_id}_sq1.png"
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        # Only sq1 exists in the question (sq2 was dropped)
        sq1 = SimpleNamespace(
            id=sq_id_delivered,
            chart_spec=_chart_spec(),
            image_spec=None,
            圖片=f"{q_id}_sq1.png",
        )
        question = SimpleNamespace(
            chart_spec=None,
            image_spec=None,
            圖片=None,
            verification=None,
            subquestions=[sq1],
        )
        config_visual = _config_with_visual()
        # Both slots were announced (planned) but only sq1 was delivered
        announced = [
            {"subquestion_index": 0, "id": sq_id_delivered, "序號": 1},
            {"subquestion_index": 1, "id": sq_id_missing, "序號": 2},
        ]
        resolution = _QuestionPositionResolution(
            announced_slots=announced,
            verification_trail=None,
            resolved_subquestion_configs=[config_visual, config_visual],
            resolved_subquestion_count=2,
            has_per_question_resolution=True,
        )
        params = _flat_params(
            sub_question_count=2,
            subquestion_configs=[config_visual, config_visual],
        )
        _expected, _delivered, missing = _compute_expected_delivered_missing(
            question_id=q_id,
            question=question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        delivery_status = _compute_delivery_status(
            has_final=True,
            termination_reason="normal",
            missing=missing,
        )
        assert delivery_status == "partial"
        sq_missing = [s for s in missing if s["kind"] == "subquestion"]
        assert any(s["subquestion_id"] == sq_id_missing for s in sq_missing), (
            f"Missing slot for {sq_id_missing} not found in {missing}"
        )
        # Verify annotations_json round-trip
        annotations: dict = {
            "terminal_delivery": {
                "delivery_status": delivery_status,
                "missing": missing,
                "termination_reason": "normal",
            }
        }
        assert annotations["terminal_delivery"]["delivery_status"] == "partial"
        assert len(annotations["terminal_delivery"]["missing"]) >= 1

    def test_partial_question_missing_visual_slot(
        self,
        six_slot_question: SimpleNamespace,
        resolution: _QuestionPositionResolution,
        output_dir: pathlib.Path,
    ) -> None:
        """A question with failed image renders produces delivery_status='partial'.

        This reuses the six-slot scenario (slots 3 and 5 missing) and verifies
        the annotations_json structure that service.py would write.
        """
        params = _flat_params(sub_question_count=SLOT_COUNT)
        _expected, _delivered, missing = _compute_expected_delivered_missing(
            question_id=QUESTION_ID,
            question=six_slot_question,
            params=params,
            output_dir=output_dir,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )
        delivery_status = _compute_delivery_status(
            has_final=True,
            termination_reason="normal",
            missing=missing,
        )
        # Simulate what annotations_json would store
        annotations: dict = {
            "terminal_delivery": {
                "delivery_status": delivery_status,
                "missing": missing,
                "termination_reason": "normal",
            }
        }
        assert annotations["terminal_delivery"]["delivery_status"] == "partial"
        image_missing = [
            s for s in annotations["terminal_delivery"]["missing"]
            if s["kind"] == "image"
        ]
        assert len(image_missing) >= 2, (
            "Six-slot scenario should have at least 2 missing image slots"
        )
        # Both missing slots should have a 'reason' field
        for slot in image_missing:
            assert "reason" in slot, f"Missing slot has no reason: {slot}"
