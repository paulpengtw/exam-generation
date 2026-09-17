"""Contract and transition tests for the live release controller (#778)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gateway.release_controller import (
    POLICY_SCHEMA,
    ReleaseController,
    ReleasePolicyError,
    parse_policy,
)


def _policy(build_id: str = "build-a", revision: int = 1, **overrides: object) -> dict:
    value: dict = {
        "schema": POLICY_SCHEMA,
        "environment": "test",
        "release_revision": revision,
        "released_build_id": build_id,
        "admission": "open",
        "supported_recovery_formats": ["json-v1"],
        "reader_version": "reader-1",
        "artifacts": {
            "current": {
                "build_id": build_id,
                "release_revision": revision,
                "reader_version": "reader-1",
            },
            "prepared_rollback": None,
            "transition": [],
        },
    }
    value.update(overrides)
    return value


def _drain(instance_id: str = "backend-1", *, captured_at: str | None = None, **extra) -> dict:
    return {
        "instance_id": instance_id,
        "captured_at": captured_at or datetime.now(UTC).isoformat(),
        "active_runs": 0,
        "active_workers": 0,
        "open_streams": 0,
        "pending_deliveries": 0,
        "pending_persistence": 0,
        "renderer_leases_held": 0,
        "integrity_errors": 0,
        "quiescent": True,
        **extra,
    }


def _evidence(*, build_id: str = "build-b", revision: int = 2, **overrides) -> dict:
    evidence = {
        "pending_admissions": 0,
        "drain_snapshots": [_drain("backend-1"), _drain("backend-2")],
        "instances": ["backend-1", "backend-2"],
        "expected_routes": ["frontend", "gateway"],
        "routes": [
            {
                "name": "frontend",
                "build_id": build_id,
                "release_revision": revision,
                "reader_version": "reader-1",
            },
            {
                "name": "gateway",
                "build_id": build_id,
                "release_revision": revision,
                "reader_version": "reader-1",
            },
        ],
    }
    evidence.update(overrides)
    return evidence


def test_parse_policy_requires_release_contract() -> None:
    parsed = parse_policy(_policy())
    assert parsed["schema"] == POLICY_SCHEMA
    assert parsed["release_revision"] == 1
    assert parsed["supported_recovery_formats"] == ["json-v1"]

    for field in (
        "schema",
        "environment",
        "release_revision",
        "released_build_id",
        "admission",
        "supported_recovery_formats",
    ):
        malformed = _policy()
        malformed.pop(field)
        with pytest.raises(ReleasePolicyError):
            parse_policy(malformed)


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "other/1"},
        {"environment": ""},
        {"release_revision": 0},
        {"release_revision": True},
        {"released_build_id": ""},
        {"admission": "unknown"},
        {"supported_recovery_formats": [1]},
    ],
)
def test_parse_policy_rejects_malformed_values(change: dict) -> None:
    malformed = _policy()
    malformed.update(change)
    with pytest.raises(ReleasePolicyError):
        parse_policy(malformed)


def test_prepare_blocks_admission_and_preserves_current_and_transition_assets(tmp_path) -> None:
    controller = ReleaseController(tmp_path, environment="test")
    controller.initialize(_policy())

    prepared = controller.prepare_target(
        {
            "build_id": "build-b",
            "release_revision": 2,
            "reader_version": "reader-1",
            "supported_recovery_formats": ["json-v1"],
        },
        transition_assets=[{"name": "schema-v2", "format": "json-v1"}],
    )

    assert prepared["admission"] == "preparing"
    assert prepared["released_build_id"] == "build-a"
    assert prepared["preparation"]["target"]["build_id"] == "build-b"
    assert prepared["artifacts"]["prepared_rollback"]["build_id"] == "build-a"
    assert prepared["artifacts"]["transition"] == [{"name": "schema-v2", "format": "json-v1"}]


def test_publish_requires_positive_drain_routes_and_no_pending_admissions(tmp_path) -> None:
    controller = ReleaseController(tmp_path, environment="test")
    controller.initialize(_policy())
    controller.prepare_target(
        {"build_id": "build-b", "release_revision": 2, "reader_version": "reader-1"}
    )

    with pytest.raises(ReleasePolicyError, match="pending admissions"):
        controller.publish_target(_evidence(pending_admissions=1))
    with pytest.raises(ReleasePolicyError, match="drain"):
        controller.publish_target(_evidence(drain_snapshots=[_drain("backend-1")]))
    with pytest.raises(ReleasePolicyError, match="stale"):
        controller.publish_target(
            _evidence(
                drain_snapshots=[
                    _drain(
                        "backend-1",
                        captured_at=(datetime.now(UTC) - timedelta(seconds=60)).isoformat(),
                    ),
                    _drain("backend-2"),
                ]
            )
        )
    with pytest.raises(ReleasePolicyError, match="route"):
        controller.publish_target(
            _evidence(
                routes=[
                    {
                        "name": "frontend",
                        "build_id": "build-a",
                        "release_revision": 1,
                        "reader_version": "reader-1",
                    }
                ]
            )
        )

    published = controller.publish_target(_evidence())
    assert published["released_build_id"] == "build-b"
    assert published["release_revision"] == 2
    assert published["admission"] == "paused"
    assert published["artifacts"]["prepared_rollback"]["build_id"] == "build-a"


def test_publish_revision_must_increase_and_rollback_cannot_reopen_gate(tmp_path) -> None:
    controller = ReleaseController(tmp_path, environment="test")
    controller.initialize(_policy())

    with pytest.raises(ReleasePolicyError, match="increase"):
        controller.prepare_target(
            {"build_id": "build-old", "release_revision": 1, "reader_version": "reader-1"}
        )

    controller.prepare_target(
        {"build_id": "build-b", "release_revision": 2, "reader_version": "reader-1"}
    )
    controller.publish_target(_evidence())
    assert controller.read_policy()["admission"] == "paused"

    # A new controller object sees the persistent paused state. A backend/app
    # rollback cannot mutate this independently owned gate.
    restarted = ReleaseController(tmp_path, environment="test")
    assert restarted.read_policy()["released_build_id"] == "build-b"
    assert restarted.read_policy()["admission"] == "paused"


def test_retirement_requires_evidence_and_keeps_current_and_rollback(tmp_path) -> None:
    controller = ReleaseController(tmp_path, environment="test")
    controller.initialize(_policy())
    controller.prepare_target(
        {"build_id": "build-b", "release_revision": 2, "reader_version": "reader-1"},
        transition_assets=[{"name": "transition", "format": "json-v1"}],
    )
    controller.publish_target(_evidence())

    with pytest.raises(ReleasePolicyError, match="pending admissions"):
        controller.retire_artifact("transition", {"pending_admissions": 1})

    state = controller.retire_artifact(
        "transition",
        {
            "pending_admissions": 0,
            "instances": ["backend-1", "backend-2"],
            "drain_snapshots": [_drain("backend-1"), _drain("backend-2")],
        },
    )
    assert state["artifacts"]["current"]["build_id"] == "build-b"
    assert state["artifacts"]["prepared_rollback"]["build_id"] == "build-a"
    assert state["artifacts"]["transition"] == []

    retired_rollback = controller.retire_artifact(
        "build-a",
        {
            "pending_admissions": 0,
            "instances": ["backend-1", "backend-2"],
            "drain_snapshots": [_drain("backend-1"), _drain("backend-2")],
        },
    )
    assert retired_rollback["artifacts"]["current"]["build_id"] == "build-b"
    assert retired_rollback["artifacts"]["prepared_rollback"] is None
