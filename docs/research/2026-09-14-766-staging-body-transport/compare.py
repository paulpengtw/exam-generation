"""Recompute sanitized live #766 evidence; no network or credentials required."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JSON_FIELDS = {"per_question_params", "subquestion_configs", "redraws"}


def normalize(value: object, key: str = "") -> object:
    if key in JSON_FIELDS and isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        return {k: normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


def differences(a: object, b: object, path: str = "$") -> list[dict]:
    if isinstance(a, dict) and isinstance(b, dict):
        result = []
        for key in sorted(a.keys() | b.keys()):
            child = f"{path}.{key}"
            if key not in a:
                result.append({"path": child, "kind": "added", "actual": b[key]})
            elif key not in b:
                result.append({"path": child, "kind": "missing", "expected": a[key]})
            else:
                result.extend(differences(a[key], b[key], child))
        return result
    if isinstance(a, list) and isinstance(b, list):
        result = []
        for i in range(max(len(a), len(b))):
            if i >= len(a):
                result.append({"path": f"{path}[{i}]", "kind": "added", "actual": b[i]})
            elif i >= len(b):
                result.append({"path": f"{path}[{i}]", "kind": "missing", "expected": a[i]})
            else:
                result.extend(differences(a[i], b[i], f"{path}[{i}]"))
        return result
    return [] if a == b else [{"path": path, "kind": "changed", "expected": a, "actual": b}]


def main() -> None:
    captures = {f.stem: json.loads(f.read_text()) for f in ROOT.glob("p*-capture.json")}
    requests = [r for c in captures.values() for r in c["requests"]]
    histories = {
        r["response"]["id"]: r["response"] for r in requests
        if r["path"].startswith("/api/history/") and r.get("response", {}).get("id")
    }
    report = {"runs": {}, "histories": {}, "replays": {}, "sentry": {}, "rejections": {}}
    phases = ("ss-original", "ns-original", "math-original", "ss-replay", "ns-replay")
    defaults = {
        "allow_duplicate_figure_kinds": False, "max_retries": 3,
        "coverage_mode": "balanced", "disable_reference_fewshot": False,
        "core_question_callback": True, "image_generation_mode": "html",
    }
    for phase in phases:
        streams = [r for r in requests if r["phase"] == phase and r["path"] == "/api/generate" and r.get("status") == 200]
        assert len(streams) == 1, (phase, len(streams))
        stream = streams[0]
        submitted = normalize(stream["request"])
        previews = [r for r in requests if r["phase"] == phase and r["path"] == "/api/generate/preview" and r.get("status") == 200]
        assert any(normalize(r["request"]) == submitted for r in previews), phase
        assert stream["method"] == "POST" and stream["targetBytes"] == 13
        expected_count = 1 if phase == "math-original" else 2
        counts = stream.get("eventCounts", {})
        assert counts.get("started") == 1 and counts.get("done") == 1, (phase, counts)
        assert counts.get("result") == expected_count and not counts.get("error"), (phase, counts)
        matching = []
        for record in histories.values():
            if record["status"] != "completed" or record["subject"] != submitted["subject"]:
                continue
            # A record belongs to this submission when its timestamp lies between
            # this run and the next submission for the same subject.
            if record["created_at"] < stream["at"]:
                continue
            later = [r["at"] for r in requests if r["path"] == "/api/generate" and r.get("status") == 200
                     and r.get("request", {}).get("subject") == submitted["subject"] and r["at"] > stream["at"]]
            if later and record["created_at"] >= min(later):
                continue
            saved = normalize(record["params_json"])
            diff = differences(submitted, saved)
            # Only backend materialized defaults may differ from the POST body.
            assert all(d["kind"] == "added" for d in diff), (record["id"], diff)
            for d in diff:
                value = d["actual"]
                key = d["path"].rsplit(".", 1)[-1]
                assert value is None or (key in defaults and value == defaults[key]), d
            matching.append(record["id"])
            report["histories"][record["id"]] = {
                "phase": phase, "question_id": record["question_id"], "status": record["status"],
                "submitted_value_changes": [], "serialization_additions": diff,
            }
        assert len(matching) == expected_count, (phase, matching)
        report["runs"][phase] = {
            "at": stream["at"], "method": stream["method"], "status": stream["status"],
            "request_target_bytes": stream["targetBytes"], "json_body_bytes": stream["bodyBytes"],
            "equivalent_get_target_bytes": stream["equivalentGetTargetBytes"],
            "preview_status": 200, "preview_method": "POST", "preview_payload_equals_submission": True,
            "history_ids": matching, "event_counts": counts,
            "post_done_capture_abort": stream.get("streamCaptureError"),
        }
    for subject in ("ss", "ns"):
        original_phase, replay_phase = f"{subject}-original", f"{subject}-replay"
        saved = normalize(histories[report["runs"][original_phase]["history_ids"][0]]["params_json"])
        replay = normalize(histories[report["runs"][replay_phase]["history_ids"][0]]["params_json"])
        assert saved == replay, (subject, differences(saved, replay))
        resolved = next(r["response"] for r in requests if r["phase"] == replay_phase and r["path"].endswith("resolve"))
        assert resolved["drawn"] == [] and resolved["cleared"] == []
        assert normalize(resolved["payload"])["per_question_params"] == saved["per_question_params"]
        report["replays"][subject] = {
            "fresh_drawn": [], "cleared": [], "complete_batch_differences": [],
            "saved_record_differences": [],
            "saved_to_resolve_envelope_differences": differences(saved, normalize(resolved["payload"])),
        }
    for name, c in captures.items():
        entries = c.get("sentry", [])
        assert all(not x["containsInstructionMarker"] and x["requestBodyFields"] == 0 for x in entries)
        report["sentry"][name] = {"options": c.get("sentryOptions"), "envelopes": len(entries),
                                   "types": sorted({t for x in entries for t in x["types"]})}
        for key in ("authProbes", "incompleteProbes", "uiRejectionEvidence", "canonicalUiRejectionEvidence"):
            if key in c:
                report["rejections"][key] = c[key]
    legacy = next(r for r in requests if r["phase"] == "legacy-get-cancel" and r["path"] == "/api/generate")
    assert legacy["method"] == "GET" and legacy["status"] == 200
    assert legacy["eventCounts"]["started"] == 1 and not legacy["eventCounts"].get("done")
    assert legacy["streamCaptureError"] == "AbortError"
    aborted = [r for r in histories.values() if r["status"] == "aborted" and r["created_at"] >= legacy["at"]]
    assert len(aborted) == 1
    report["legacy_get_cancellation"] = {"target_bytes": legacy["targetBytes"], "status": 200,
        "event_counts": legacy["eventCounts"], "history_id": aborted[0]["id"], "saved_status": "aborted"}
    (ROOT / "comparisons.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("Verified five completed UI runs, nine completed History records, exact SS/NS replay values, and legacy GET cancellation.")
    for phase, run in report["runs"].items():
        print(f"{phase}: POST 200, equivalent GET {run['equivalent_get_target_bytes']} bytes; {len(run['history_ids'])} exact saved records plus defaults")


if __name__ == "__main__":
    main()
