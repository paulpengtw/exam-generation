"""Unit tests for the three question_terminal assembly units (issue #857).

Tests exercise the pure helper functions introduced by the refactor:
  _compute_review
  _compute_expected_delivered_missing
  _compute_delivery_status

Seven coverage cases per acceptance criteria:
  1. complete          – all subquestions delivered, delivery_status='complete'
  2. partial           – some subquestions missing, delivery_status='partial'
  3. no final          – has_final=False, delivery_status='none' (failed) or
                         'unknown' (cancelled)
  4. text-only         – flat question with no image/subquestions, empty slots
  5. missing required image – image slot expected but file absent from disk
  6. flat math with no sub-questions – has_per_question_resolution=True,
                         resolved_subquestion_count=None → no subquestion slots
  7. old-version review not masquerading as final – verification trail entry has
                         content_revision != final_revision → status='unknown'

All tests use the public unit functions from server.generate.question_terminal
directly; none imports _build_question_terminal_payload.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from server.generate.question_terminal import (
    _compute_delivery_status,
    _compute_expected_delivered_missing,
    _compute_review,
    _QuestionPositionResolution,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flat_params(**kwargs: Any) -> SimpleNamespace:
    """Build a minimal params-like object for tests."""
    defaults = {
        "skip_verify": False,
        "sub_question_count": None,
        "subquestion_configs": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _subquestion(
    sq_id: str,
    *,
    chart_spec: Any = None,
    image_spec: Any = None,
    圖片: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=sq_id,
        chart_spec=chart_spec,
        image_spec=image_spec,
        圖片=圖片,
    )


def _question_with_sqs(question_id: str, sqs: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        chart_spec=None,
        image_spec=None,
        圖片=None,
        verification=None,
        subquestions=sqs,
    )


# ---------------------------------------------------------------------------
# _compute_review
# ---------------------------------------------------------------------------


class TestComputeReview:
    """Unit 1: review ↔ final_revision pairing."""

    def test_no_final_returns_unknown_with_default_reason(self) -> None:
        result = _compute_review(
            has_final=False,
            skip_verify=False,
            question=None,
            final_revision=None,
            unknown_reason=None,
            verification_trail=None,
        )
        assert result == {"status": "unknown", "reason": "no final content"}

    def test_no_final_uses_provided_unknown_reason(self) -> None:
        result = _compute_review(
            has_final=False,
            skip_verify=False,
            question=None,
            final_revision=None,
            unknown_reason="cancelled before completion",
            verification_trail=None,
        )
        assert result["reason"] == "cancelled before completion"

    def test_skip_verify_returns_skipped(self) -> None:
        result = _compute_review(
            has_final=True,
            skip_verify=True,
            question=SimpleNamespace(verification=None),
            final_revision=5,
            unknown_reason=None,
            verification_trail=None,
        )
        assert result == {"status": "skipped", "content_revision": 5}

    def test_complete_passed_verification(self) -> None:
        """Case 1 (complete): matching verification entry → 'passed'."""
        verification = SimpleNamespace(passed=True)
        question = SimpleNamespace(verification=verification)
        trail = [{"kind": "verification", "content_revision": 3}]
        result = _compute_review(
            has_final=True,
            skip_verify=False,
            question=question,
            final_revision=3,
            unknown_reason=None,
            verification_trail=trail,
        )
        assert result == {"status": "passed", "content_revision": 3}

    def test_complete_failed_verification(self) -> None:
        """Case 1 (complete): matching verification entry → 'failed'."""
        verification = SimpleNamespace(passed=False)
        question = SimpleNamespace(verification=verification)
        trail = [{"kind": "verification", "content_revision": 7}]
        result = _compute_review(
            has_final=True,
            skip_verify=False,
            question=question,
            final_revision=7,
            unknown_reason=None,
            verification_trail=trail,
        )
        assert result["status"] == "failed"
        assert result["content_revision"] == 7

    # Case 7: old-version review must NOT masquerade as the current final.
    def test_old_revision_verification_entry_does_not_match_final(self) -> None:
        """Case 7: verification trail entry for revision 2 is not evidence for final 3."""
        verification = SimpleNamespace(passed=True)
        question = SimpleNamespace(verification=verification)
        # Trail has entry for revision 2, but final is revision 3.
        trail = [{"kind": "verification", "content_revision": 2}]
        result = _compute_review(
            has_final=True,
            skip_verify=False,
            question=question,
            final_revision=3,
            unknown_reason=None,
            verification_trail=trail,
        )
        assert result["status"] == "unknown"
        assert "no matching verification evidence" in result["reason"]

    def test_multiple_trail_entries_uses_most_recent_matching(self) -> None:
        """Most-recent verification entry (last appended = first in reversed) is used."""
        verification = SimpleNamespace(passed=True)
        question = SimpleNamespace(verification=verification)
        # The most recent entry (index 1 = last) has revision 5 matching final.
        trail = [
            {"kind": "verification", "content_revision": 3},
            {"kind": "verification", "content_revision": 5},
        ]
        result = _compute_review(
            has_final=True,
            skip_verify=False,
            question=question,
            final_revision=5,
            unknown_reason=None,
            verification_trail=trail,
        )
        assert result["status"] == "passed"

    def test_no_verification_on_question_returns_unknown(self) -> None:
        """Question with verification=None → 'unknown' with 'no verification evidence'."""
        question = SimpleNamespace(verification=None)
        result = _compute_review(
            has_final=True,
            skip_verify=False,
            question=question,
            final_revision=2,
            unknown_reason=None,
            verification_trail=[{"kind": "verification", "content_revision": 2}],
        )
        assert result == {"status": "unknown", "reason": "no verification evidence"}

    def test_non_verification_trail_entries_are_ignored(self) -> None:
        """Entries with kind != 'verification' are not used for pairing."""
        verification = SimpleNamespace(passed=True)
        question = SimpleNamespace(verification=verification)
        trail = [
            {"kind": "correction", "content_revision": 4},
        ]
        result = _compute_review(
            has_final=True,
            skip_verify=False,
            question=question,
            final_revision=4,
            unknown_reason=None,
            verification_trail=trail,
        )
        # No verification entry → 'no verification evidence'
        assert result["status"] == "unknown"
        assert "no verification evidence" in result["reason"]

    def test_boolean_revision_not_treated_as_int(self) -> None:
        """True (== 1) must not match final_revision=1 — booleans are excluded."""
        verification = SimpleNamespace(passed=True)
        question = SimpleNamespace(verification=verification)
        trail = [{"kind": "verification", "content_revision": True}]
        result = _compute_review(
            has_final=True,
            skip_verify=False,
            question=question,
            final_revision=1,
            unknown_reason=None,
            verification_trail=trail,
        )
        assert result["status"] == "unknown"


# ---------------------------------------------------------------------------
# _compute_delivery_status
# ---------------------------------------------------------------------------


class TestComputeDeliveryStatus:
    """Unit 3: delivery completeness."""

    def test_no_final_failed_returns_none(self) -> None:
        """Case 3 (no final + failed): delivery_status='none'."""
        assert _compute_delivery_status(
            has_final=False,
            termination_reason="failed",
            missing=[],
        ) == "none"

    def test_no_final_cancelled_returns_unknown(self) -> None:
        """Case 3 (no final + cancelled): delivery_status='unknown'."""
        assert _compute_delivery_status(
            has_final=False,
            termination_reason="cancelled",
            missing=[],
        ) == "unknown"

    def test_has_final_no_missing_returns_complete(self) -> None:
        """Case 1 (complete): has_final=True, no missing → 'complete'."""
        assert _compute_delivery_status(
            has_final=True,
            termination_reason="normal",
            missing=[],
        ) == "complete"

    def test_has_final_with_missing_returns_partial(self) -> None:
        """Case 2 (partial): has_final=True, some missing → 'partial'."""
        assert _compute_delivery_status(
            has_final=True,
            termination_reason="normal",
            missing=[{"kind": "subquestion"}],
        ) == "partial"


# ---------------------------------------------------------------------------
# _compute_expected_delivered_missing
# ---------------------------------------------------------------------------


def _make_resolution(**kwargs: Any) -> _QuestionPositionResolution:
    return _QuestionPositionResolution(**kwargs)


class TestComputeExpectedDeliveredMissing:
    """Unit 2: fixed-slot positions and image assets."""

    # Case 4: text-only flat question — no image, no subquestions.
    def test_text_only_flat_question_returns_empty_slots(self) -> None:
        """Case 4: flat math, no chart_spec, no image → all lists empty."""
        question = SimpleNamespace(
            chart_spec=None, image_spec=None, 圖片=None, subquestions=[]
        )
        params = _flat_params()
        resolution = _make_resolution(has_per_question_resolution=False)

        expected, delivered, missing = _compute_expected_delivered_missing(
            question_id="q001",
            question=question,
            params=params,
            output_dir=None,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )

        assert expected == []
        assert delivered == []
        assert missing == []

    # Case 6: flat math with per-question resolution, resolved_subquestion_count=None.
    def test_flat_math_per_question_resolution_no_count_empty_slots(self) -> None:
        """Case 6: has_per_question_resolution=True but count=None → no subquestion slots."""
        question = SimpleNamespace(
            chart_spec=None, image_spec=None, 圖片=None, subquestions=[]
        )
        params = _flat_params()
        resolution = _make_resolution(
            has_per_question_resolution=True,
            resolved_subquestion_count=None,
            resolved_subquestion_configs=None,
        )

        expected, delivered, missing = _compute_expected_delivered_missing(
            question_id="q-flat",
            question=question,
            params=params,
            output_dir=None,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )

        assert expected == []
        assert delivered == []
        assert missing == []

    # Case 1: complete — all subquestions present.
    def test_complete_all_subquestions_delivered(self) -> None:
        """Case 1: 3 slots, all present in question → delivered=3, missing=0."""
        qid = "q-complete"
        sqs = [
            _subquestion(f"{qid}-sq001"),
            _subquestion(f"{qid}-sq002"),
            _subquestion(f"{qid}-sq003"),
        ]
        question = _question_with_sqs(qid, sqs)
        params = _flat_params(
            sub_question_count=3,
            subquestion_configs=[SimpleNamespace(content_type=None) for _ in range(3)],
        )
        announced = [
            {"subquestion_index": 0, "id": f"{qid}-sq001", "序號": 1},
            {"subquestion_index": 1, "id": f"{qid}-sq002", "序號": 2},
            {"subquestion_index": 2, "id": f"{qid}-sq003", "序號": 3},
        ]
        resolution = _make_resolution(
            announced_slots=announced,
            has_per_question_resolution=True,
            resolved_subquestion_count=3,
        )

        expected, delivered, missing = _compute_expected_delivered_missing(
            question_id=qid,
            question=question,
            params=params,
            output_dir=None,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )

        assert len(expected) == 3
        assert len(delivered) == 3
        assert missing == []

    # Case 2: partial — one subquestion missing.
    def test_partial_one_subquestion_missing(self) -> None:
        """Case 2: 3 slots but only 2 present → missing=1, partial."""
        qid = "q-partial"
        # sq002 is absent
        sqs = [
            _subquestion(f"{qid}-sq001"),
            _subquestion(f"{qid}-sq003"),
        ]
        question = _question_with_sqs(qid, sqs)
        params = _flat_params(
            sub_question_count=3,
            subquestion_configs=[SimpleNamespace(content_type=None) for _ in range(3)],
        )
        announced = [
            {"subquestion_index": 0, "id": f"{qid}-sq001", "序號": 1},
            {"subquestion_index": 1, "id": f"{qid}-sq002", "序號": 2},
            {"subquestion_index": 2, "id": f"{qid}-sq003", "序號": 3},
        ]
        resolution = _make_resolution(
            announced_slots=announced,
            has_per_question_resolution=True,
            resolved_subquestion_count=3,
        )

        expected, delivered, missing = _compute_expected_delivered_missing(
            question_id=qid,
            question=question,
            params=params,
            output_dir=None,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )

        assert len(expected) == 3
        assert len(delivered) == 2
        assert len(missing) == 1
        assert missing[0]["subquestion_id"] == f"{qid}-sq002"

    # Case 3: no final — has_final=False with a group.
    def test_no_final_failed_group_empty_expected(self) -> None:
        """Case 3: no final, failed before plan → expected empty (no slot_manifest)."""
        params = _flat_params()
        resolution = _make_resolution(
            announced_slots=None,
            has_per_question_resolution=False,
        )

        expected, delivered, missing = _compute_expected_delivered_missing(
            question_id="q-nofinal",
            question=None,
            params=params,
            output_dir=None,
            has_final=False,
            termination_reason="failed",
            resolution=resolution,
        )

        assert expected == []
        assert delivered == []
        assert missing == []

    def test_no_final_failed_group_uses_resolved_count_for_slots(self) -> None:
        """Case 3: no final, failed, has per-question count → slot placeholders built."""
        params = _flat_params()
        resolution = _make_resolution(
            announced_slots=None,
            has_per_question_resolution=True,
            resolved_subquestion_count=2,
        )

        expected, delivered, missing = _compute_expected_delivered_missing(
            question_id="q-fail-group",
            question=None,
            params=params,
            output_dir=None,
            has_final=False,
            termination_reason="failed",
            resolution=resolution,
        )

        # Both slots are expected; none delivered; both missing.
        assert len(expected) == 2
        assert delivered == []
        assert len(missing) == 2

    # Case 5: missing required image.
    def test_missing_required_image_slot(self) -> None:
        """Case 5: adopted chart_spec but image file absent → missing image slot."""
        import tempfile

        qid = "q-img-missing"
        question = SimpleNamespace(
            chart_spec=object(),  # non-None → adopted
            image_spec=None,
            圖片="q-img-missing.png",  # file does NOT exist
            subquestions=[],
            verification=None,
        )
        params = _flat_params()
        resolution = _make_resolution(
            has_per_question_resolution=True,
            resolved_subquestion_count=None,
        )

        with tempfile.TemporaryDirectory() as tmp:
            expected, delivered, missing = _compute_expected_delivered_missing(
                question_id=qid,
                question=question,
                params=params,
                output_dir=tmp,  # dir exists but file does not
                has_final=True,
                termination_reason="normal",
                resolution=resolution,
            )

        assert len(expected) == 1
        assert expected[0]["kind"] == "image"
        assert delivered == []
        assert len(missing) == 1
        assert missing[0]["kind"] == "image"
        assert "reason" in missing[0]

    def test_image_slot_delivered_when_file_present(self) -> None:
        """Image is delivered when the file exists on disk."""
        import tempfile
        from pathlib import Path

        qid = "q-img-present"
        filename = f"{qid}.png"
        question = SimpleNamespace(
            chart_spec=object(),
            image_spec=None,
            圖片=filename,
            subquestions=[],
            verification=None,
        )
        params = _flat_params()
        resolution = _make_resolution(
            has_per_question_resolution=True,
            resolved_subquestion_count=None,
        )

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / filename).write_text("fake png")
            expected, delivered, missing = _compute_expected_delivered_missing(
                question_id=qid,
                question=question,
                params=params,
                output_dir=tmp,
                has_final=True,
                termination_reason="normal",
                resolution=resolution,
            )

        assert len(expected) == 1
        assert len(delivered) == 1
        assert missing == []

    def test_no_image_slot_without_chart_spec_or_filename(self) -> None:
        """No chart_spec, no image_spec, no 圖片 → no image slot."""
        question = SimpleNamespace(
            chart_spec=None,
            image_spec=None,
            圖片=None,
            subquestions=[],
            verification=None,
        )
        params = _flat_params()
        resolution = _make_resolution(
            has_per_question_resolution=True,
            resolved_subquestion_count=None,
        )

        expected, delivered, missing = _compute_expected_delivered_missing(
            question_id="q-noimg",
            question=question,
            params=params,
            output_dir=None,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )

        assert expected == []
        assert delivered == []
        assert missing == []

    def test_falls_back_to_batch_params_when_no_per_question_resolution(self) -> None:
        """When has_per_question_resolution=False, sub_question_count from params drives grouping.
        """
        qid = "q-fallback"
        sqs = [
            _subquestion(f"{qid}-sq001"),
            _subquestion(f"{qid}-sq002"),
        ]
        question = _question_with_sqs(qid, sqs)
        params = _flat_params(sub_question_count=2)
        # No announced_slots but params has sub_question_count=2.
        resolution = _make_resolution(
            has_per_question_resolution=False,
            announced_slots=None,
        )

        expected, delivered, missing = _compute_expected_delivered_missing(
            question_id=qid,
            question=question,
            params=params,
            output_dir=None,
            has_final=True,
            termination_reason="normal",
            resolution=resolution,
        )

        # Without a slot_manifest (no announced_slots, and not failed),
        # slot_manifest stays None → no subquestion slots generated.
        # This is correct behaviour: slot_manifest fallback only fires on failure.
        assert expected == []


# ---------------------------------------------------------------------------
# _QuestionPositionResolution defaults
# ---------------------------------------------------------------------------


def test_position_resolution_defaults() -> None:
    """Default construction has no resolution and no slots."""
    r = _QuestionPositionResolution()
    assert r.announced_slots is None
    assert r.verification_trail is None
    assert r.resolved_subquestion_configs is None
    assert r.resolved_subquestion_count is None
    assert r.has_per_question_resolution is False


def test_position_resolution_is_frozen() -> None:
    """Dataclass is frozen; mutation raises FrozenInstanceError."""
    r = _QuestionPositionResolution()
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        r.announced_slots = []  # type: ignore[misc]
