"""The repeatable #778 local admission rehearsal records dispatch evidence."""
from __future__ import annotations

import json

from scripts.release_admission_rehearsal import run_rehearsal


def test_release_admission_rehearsal_records_two_instances_and_all_routes(tmp_path) -> None:
    output = tmp_path / "evidence.json"
    evidence = run_rehearsal(output)

    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8")) == evidence
    assert len(evidence["backend_instances"]) == 2
    assert evidence["checks"]["current_build_accepted"]["status"] == 200
    assert evidence["checks"]["current_build_accepted"]["generation_dispatches"] == 1
    assert evidence["checks"]["stale_or_missing_build"]["rejected_statuses"] == [426, 426]
    assert evidence["checks"]["stale_or_missing_build"]["generation_dispatches_delta"] == 0
    assert evidence["checks"]["paused_or_unavailable_authority"]["statuses"] == [503, 503]
    assert evidence["checks"]["paused_or_unavailable_authority"]["generation_dispatches_delta"] == 0
    assert evidence["checks"]["existing_stream_and_read_only"]["stream_completed"] is True
    assert evidence["checks"]["pending_transition"]["pending_publish_status"] == 409
    assert evidence["checks"]["pending_transition"]["published_status"] == 200
    assert evidence["checks"]["nginx_headers"]["nginx.conf"] is True
    assert evidence["checks"]["nginx_headers"]["nginx.conf.template"] is True
    assert evidence["route_inventory"]
    assert all(item["status"] is not None for item in evidence["route_inventory"])
    assert all(item["generation_dispatches"] >= 0 for item in evidence["dispatch_evidence"])
