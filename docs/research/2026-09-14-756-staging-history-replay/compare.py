"""Recompute the #756 observations from sanitized ego-browser captures.

This checks the evidence, not a passing product acceptance test. No network,
credentials, browser storage, or generated question contents are needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
ARRAY_FIELDS = {
    "style", "context", "q_type", "subject_filter", "options",
    "science_competency", "learning_performance", "core_competency",
    "math_thinking", "learning_content", "drawn",
}
JSON_FIELDS = {"per_question_params", "subquestion_configs", "redraws"}
BOOL_FIELDS = {
    "skip_verify", "disable_reference_fewshot", "core_question_callback",
    "allow_duplicate_figure_kinds",
}
INT_FIELDS = {
    "grade", "count", "seed", "sub_question_count", "question_word_limit",
    "option_word_limit", "text_word_limit", "max_retries",
}


def read(name: str) -> dict:
    return json.loads((ROOT / name).read_text())


def normalize(value: object, key: str = "") -> object:
    if key in JSON_FIELDS and isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        return {k: normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def query_payload(entry: dict) -> dict:
    payload: dict = {}
    for key, raw in entry["query"]:
        value: object = raw
        if key in ARRAY_FIELDS:
            payload.setdefault(key, []).append(value)
            continue
        if key in BOOL_FIELDS or key in INT_FIELDS:
            value = json.loads(raw)
        payload[key] = value
    return normalize(payload)


def differences(expected: object, actual: object, path: str = "$") -> list[dict]:
    """Exact comparison: preserve array order and report absent keys explicitly."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        result = []
        for key in sorted(expected.keys() | actual.keys()):
            child = f"{path}.{key}"
            if key not in expected:
                result.append({"path": child, "kind": "added", "actual": actual[key]})
            elif key not in actual:
                result.append({"path": child, "kind": "missing", "expected": expected[key]})
            else:
                result.extend(differences(expected[key], actual[key], child))
        return result
    if isinstance(expected, list) and isinstance(actual, list):
        result = []
        for index in range(max(len(expected), len(actual))):
            child = f"{path}[{index}]"
            if index >= len(expected):
                result.append({"path": child, "kind": "added", "actual": actual[index]})
            elif index >= len(actual):
                result.append({"path": child, "kind": "missing", "expected": expected[index]})
            else:
                result.extend(differences(expected[index], actual[index], child))
        return result
    if expected == actual:
        return []
    return [{"path": path, "kind": "changed", "expected": expected, "actual": actual}]


def event(capture: dict, path: str) -> dict:
    return next(row for row in capture["requests"] if row["path"] == path)


def summarize_original(name: str) -> dict:
    capture = read(name)
    resolved = event(capture, "/api/generate/resolve")
    submitted = event(capture, "/api/generate")
    payload = normalize(resolved["response"]["payload"])
    sent = query_payload(submitted)
    request_target = submitted["path"] + "?" + urlencode(
        [tuple(pair) for pair in submitted["query"]]
    )
    return {
        "resolve_status": resolved["status"],
        "generate_status": submitted["status"],
        "resolve_at": resolved["at"],
        "generate_at": submitted["at"],
        "request_target_bytes": len(request_target.encode()),
        "drawn": resolved["response"]["drawn"],
        "seed": payload["seed"],
        "row_seeds": [row["seed"] for row in payload["per_question_params"]],
        "row_subquestion_counts": [
            row["sub_question_count"] for row in payload["per_question_params"]
        ],
        "resolve_to_submission_differences": differences(payload, sent),
        "resolved_row_value_changes": [
            difference
            for difference in differences(
                payload["per_question_params"], sent["per_question_params"],
                "$.per_question_params",
            )
            if difference["kind"] != "added"
        ],
    }


def main() -> None:
    original = read("p1-capture.json")
    replay = read("math-history-capture.json")
    first_history = next(
        row["response"] for row in replay["requests"]
        if row["path"].startswith("/api/history/")
    )
    second_history = read("math-replay-history.json")
    saved = normalize(first_history["params_json"])
    replay_resolve = event(replay, "/api/generate/resolve")["response"]
    original_sent = query_payload(event(original, "/api/generate"))
    replay_sent = query_payload(event(replay, "/api/generate"))
    report = {
        "acceptance": "blocked_by_reproduced_staging_failures",
        "subjects": {
            "math": summarize_original("p1-capture.json"),
            "social_studies": summarize_original("p2-capture.json"),
            "natural_sciences": summarize_original("p3-capture.json"),
        },
        "math_interrupted_record_replay": {
            "original_record_id": first_history["id"],
            "replay_record_id": second_history["id"],
            "record_statuses": [first_history["status"], second_history["status"]],
            "fresh_drawn": replay_resolve["drawn"],
            "submitted_requests_diff": differences(original_sent, replay_sent),
            "submitted_to_saved_rows_diff": differences(
                original_sent["per_question_params"], saved["per_question_params"],
            ),
            "saved_to_replay_resolve_rows_diff": differences(
                saved["per_question_params"],
                normalize(replay_resolve["payload"])["per_question_params"],
            ),
            "saved_to_replay_resolve_envelope_diff": differences(
                saved, normalize(replay_resolve["payload"]),
            ),
            "saved_records_diff": differences(
                saved, normalize(second_history["params_json"]),
            ),
            "raw_params_json_equal": first_history["params_json"] == second_history["params_json"],
        },
    }
    result = report["math_interrupted_record_replay"]
    assert result["fresh_drawn"] == []
    for key in ("saved_to_replay_resolve_rows_diff", "saved_records_diff"):
        assert result[key] == [], (key, result[key])
    # The backend materializes two defaults into each math row before saving.
    # Keep these wire differences visible instead of calling the requests identical.
    for key in ("submitted_requests_diff", "submitted_to_saved_rows_diff"):
        changes = result[key]
        assert len(changes) == 4, (key, changes)
        for change in changes:
            assert change["kind"] == "added", change
            assert (
                change["path"].endswith(".coverage_mode")
                and change["actual"] == "balanced"
            ) or (
                change["path"].endswith(".disable_reference_fewshot")
                and change["actual"] is False
            ), change
    assert result["raw_params_json_equal"]
    assert result["record_statuses"] == ["aborted", "aborted"]
    for name, summary in report["subjects"].items():
        assert summary["resolve_status"] == 200
        assert summary["generate_status"] == (200 if name == "math" else 414)
        assert summary["resolved_row_value_changes"] == []
    (ROOT / "comparisons.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print("Evidence verified; live acceptance remains blocked.")
    print("Math: identical interrupted History params_json; no fresh draws; "
          "replay additionally transmits four persisted default values.")
    for name, summary in report["subjects"].items():
        print(f"{name}: resolve={summary['resolve_status']}, generate={summary['generate_status']}, "
              f"request target={summary['request_target_bytes']} bytes")


if __name__ == "__main__":
    main()
