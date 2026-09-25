"""Tests for generation_events and event_protocol contract types."""
from __future__ import annotations

import pytest

from server.generate.event_protocol import (
    CLIENT_UPDATE_REQUIRED_DETAIL,
    PROTOCOL_VERSION,
    SUPPORTED_STREAM_VERSIONS,
    EventContext,
    QuestionTerminalPayload,
    SlotRef,
    StartedPayload,
    client_update_required_body,
    envelope_dict,
)
from src.common.generation_events import allocate_manifest, new_run_id


def test_new_run_id_is_32_char_hex():
    rid = new_run_id()
    assert len(rid) == 32
    int(rid, 16)  # must be valid hex


def test_new_run_id_unique():
    assert new_run_id() != new_run_id()


def test_allocate_manifest_ids_and_padding():
    manifest = allocate_manifest("q_", "abc123", 3)
    assert len(manifest) == 3
    assert manifest[0].question_id == "q_abc123_001"
    assert manifest[1].question_id == "q_abc123_002"
    assert manifest[2].question_id == "q_abc123_003"


def test_allocate_manifest_indices():
    manifest = allocate_manifest("q_", "x", 5)
    for i, ctx in enumerate(manifest):
        assert ctx.index == i
        assert ctx.run_id == "x"


def test_allocate_manifest_ids_unique():
    manifest = allocate_manifest("q_", "run1", 10)
    ids = [ctx.question_id for ctx in manifest]
    assert len(ids) == len(set(ids))


def test_allocate_manifest_count_zero():
    manifest = allocate_manifest("q_", "run1", 0)
    assert manifest == ()


def test_started_payload_valid():
    payload = StartedPayload(
        protocol_version=2,
        total=2,
        questions=[
            {"index": 0, "question_id": "q_001"},
            {"index": 1, "question_id": "q_002"},
        ],
    )
    assert payload.total == 2


def test_started_payload_rejects_gap():
    with pytest.raises(Exception):
        StartedPayload(
            protocol_version=2,
            total=2,
            questions=[
                {"index": 0, "question_id": "q_001"},
                {"index": 2, "question_id": "q_003"},
            ],
        )


def test_started_payload_rejects_duplicate_id():
    with pytest.raises(Exception):
        StartedPayload(
            protocol_version=2,
            total=2,
            questions=[
                {"index": 0, "question_id": "q_001"},
                {"index": 1, "question_id": "q_001"},
            ],
        )


def test_started_payload_rejects_total_mismatch():
    with pytest.raises(Exception):
        StartedPayload(
            protocol_version=2,
            total=3,
            questions=[
                {"index": 0, "question_id": "q_001"},
                {"index": 1, "question_id": "q_002"},
            ],
        )


def test_terminal_normal_complete_passed():
    payload = QuestionTerminalPayload(
        termination_reason="normal",
        has_final=True,
        final_revision=1,
        delivery_status="complete",
        expected=[],
        delivered=[],
        missing=[],
        review={"status": "passed", "content_revision": 1},
    )
    assert payload.delivery_status == "complete"


def test_terminal_normal_partial():
    slot = SlotRef(kind="image", question_id="q_001")
    payload = QuestionTerminalPayload(
        termination_reason="normal",
        has_final=True,
        final_revision=1,
        delivery_status="partial",
        expected=[slot],
        delivered=[],
        missing=[slot],
        review={"status": "passed", "content_revision": 1},
    )
    assert payload.delivery_status == "partial"


def test_terminal_failed_none():
    payload = QuestionTerminalPayload(
        termination_reason="failed",
        has_final=False,
        final_revision=None,
        delivery_status="none",
        expected=[],
        delivered=[],
        missing=[],
        review={"status": "unknown", "reason": "no final content"},
    )
    assert payload.termination_reason == "failed"


def test_terminal_cancelled_unknown():
    payload = QuestionTerminalPayload(
        termination_reason="cancelled",
        has_final=False,
        final_revision=None,
        delivery_status="unknown",
        expected=[],
        delivered=[],
        missing=[],
        review={"status": "unknown", "reason": "cancelled"},
        unknown_reason="cancelled before completion",
    )
    assert payload.unknown_reason == "cancelled before completion"


def test_terminal_rejects_has_final_without_revision():
    with pytest.raises(Exception):
        QuestionTerminalPayload(
            termination_reason="normal",
            has_final=True,
            final_revision=None,
            delivery_status="complete",
            expected=[],
            delivered=[],
            missing=[],
            review={"status": "passed", "content_revision": None},
        )


def test_terminal_rejects_no_final_claiming_complete():
    with pytest.raises(Exception):
        QuestionTerminalPayload(
            termination_reason="failed",
            has_final=False,
            final_revision=None,
            delivery_status="complete",
            expected=[],
            delivered=[],
            missing=[],
            review={"status": "unknown", "reason": "x"},
        )


def test_terminal_rejects_review_revision_mismatch():
    with pytest.raises(Exception):
        QuestionTerminalPayload(
            termination_reason="normal",
            has_final=True,
            final_revision=2,
            delivery_status="complete",
            expected=[],
            delivered=[],
            missing=[],
            review={"status": "passed", "content_revision": 1},
        )


def test_terminal_rejects_boolean_review_revision():
    with pytest.raises(Exception):
        QuestionTerminalPayload(
            termination_reason="normal",
            has_final=True,
            final_revision=1,
            delivery_status="complete",
            expected=[],
            delivered=[],
            missing=[],
            review={"status": "passed", "content_revision": True},
        )


def test_terminal_rejects_definitive_review_without_a_final():
    with pytest.raises(Exception):
        QuestionTerminalPayload(
            termination_reason="failed",
            has_final=False,
            final_revision=None,
            delivery_status="none",
            expected=[],
            delivered=[],
            missing=[],
            review={"status": "passed", "content_revision": None},
        )


def test_terminal_rejects_unknown_review_without_reason_for_a_final():
    with pytest.raises(Exception):
        QuestionTerminalPayload(
            termination_reason="normal",
            has_final=True,
            final_revision=1,
            delivery_status="complete",
            expected=[],
            delivered=[],
            missing=[],
            review={"status": "unknown"},
        )


def test_terminal_rejects_unknown_without_reason():
    with pytest.raises(Exception):
        QuestionTerminalPayload(
            termination_reason="cancelled",
            has_final=False,
            final_revision=None,
            delivery_status="unknown",
            expected=[],
            delivered=[],
            missing=[],
            review={"status": "unknown", "reason": "cancelled"},
            unknown_reason=None,
        )


def test_context_serialization_omits_none_fields():
    ctx = EventContext(run_id="abc", event_seq=1)
    data = ctx.model_dump(exclude_none=True)
    assert "question_id" not in data
    assert "index" not in data
    assert data["run_id"] == "abc"
    assert data["event_seq"] == 1


def test_envelope_dict_payload_not_mutated():
    ctx = EventContext(run_id="abc", event_seq=1)
    payload = {"key": "value", "nested": {"x": 1}}
    result = envelope_dict(ctx, payload)
    payload["key"] = "CHANGED"
    payload["nested"]["x"] = 999
    assert result["payload"]["key"] == "value"
    assert result["payload"]["nested"]["x"] == 1


def test_envelope_dict_no_envelope_keys_in_payload():
    ctx = EventContext(run_id="abc", event_seq=1)
    payload = {"data": "hello"}
    result = envelope_dict(ctx, payload)
    assert "context" not in result["payload"]
    assert "event_seq" not in result["payload"]
    assert "payload" not in result["payload"]


def test_client_update_required_body():
    body = client_update_required_body()
    assert body["detail"] == CLIENT_UPDATE_REQUIRED_DETAIL
    assert body["code"] == "CLIENT_UPDATE_REQUIRED"
    assert body["supported_stream_versions"] == [2]


def test_protocol_version():
    assert PROTOCOL_VERSION == 2
    assert 2 in SUPPORTED_STREAM_VERSIONS
