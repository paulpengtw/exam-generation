"""Issue #754 — fixture drift guard.

Verifies that every committed generation_v2 and generation_legacy fixture file:
  1. Exists on disk.
  2. Is non-empty, well-formed JSON-lines.
  3. Has a 'started' event as the first line.
  4. Has a 'done' event as the last line.
  5. Has contiguous event_seq starting at 1 (for v2 fixtures).

Regeneration command (requires no paid models — uses fake clients):
  bash scripts/generate_v2_fixtures.sh

If any fixture drifts from what the current code would produce, run:
  GENERATE_V2_FIXTURE=1 uv run pytest <specific test file> -q
to regenerate that fixture, then commit the updated file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture file registry
# ---------------------------------------------------------------------------

V2_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "generation_v2"
LEGACY_FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "generation_legacy"

_V2_FIXTURES = [
    "math_single_interleaved.jsonl",
    "math_groups_interleaved.jsonl",
    "social_groups_interleaved.jsonl",
    "natural_sciences_groups_interleaved.jsonl",
    "math_abcd_transport.jsonl",
]

# Fixtures that intentionally omit one or more events to simulate transport loss.
# They are valid v2 fixtures but do NOT have contiguous event_seq (the gap IS the
# test scenario); the contiguous-seq check is skipped for them.
_TRANSPORT_FIXTURES = {
    "math_abcd_transport.jsonl",  # q_RUN_004 terminal omitted (seq 19 absent)
}

_LEGACY_FIXTURES = [
    "math_single_legacy.jsonl",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# Parametrized drift guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _V2_FIXTURES)
def test_v2_fixture_exists_and_valid(name: str) -> None:
    """Each v2 fixture must exist, be valid JSON-lines, and satisfy basic shape."""
    path = V2_FIXTURE_DIR / name
    assert path.exists(), (
        f"Fixture {name} is missing. Regenerate with: bash scripts/generate_v2_fixtures.sh"
    )

    events = _load_jsonl(path)
    assert len(events) > 0, f"{name}: fixture is empty"

    # First event must be 'started'
    assert events[0].get("event") == "started", (
        f"{name}: first event is {events[0].get('event')!r}, expected 'started'"
    )

    # Last event must be 'done'
    assert events[-1].get("event") == "done", (
        f"{name}: last event is {events[-1].get('event')!r}, expected 'done'"
    )

    # 'started' must have the v2 context structure (run_id, event_seq)
    started = events[0]
    assert "context" in started, f"{name}: started event missing 'context'"
    assert "run_id" in started["context"], f"{name}: started context missing 'run_id'"
    assert started["context"].get("event_seq") == 1, (
        f"{name}: started event_seq must be 1, got {started['context'].get('event_seq')}"
    )

    # 'started' payload must have protocol_version=2 and questions list
    payload = events[0].get("payload", {})
    assert payload.get("protocol_version") == 2, (
        f"{name}: started payload protocol_version must be 2"
    )
    assert isinstance(payload.get("questions"), list), (
        f"{name}: started payload must include questions list"
    )
    assert len(payload["questions"]) > 0, f"{name}: started payload questions list is empty"

    # All events must have context with event_seq
    seqs: list[int] = []
    for ev in events:
        ctx = ev.get("context", {})
        if "event_seq" in ctx:
            seqs.append(ctx["event_seq"])

    assert len(seqs) == len(events), (
        f"{name}: not all events have event_seq. "
        f"Got {len(seqs)} out of {len(events)} events."
    )

    # event_seq must be contiguous 1..N — except for transport fixtures that
    # deliberately omit events to simulate network loss.
    if name not in _TRANSPORT_FIXTURES:
        assert sorted(seqs) == list(range(1, len(seqs) + 1)), (
            f"{name}: event_seq is not contiguous. Got: {sorted(seqs)}"
        )
    else:
        # Transport fixtures: just verify seqs are unique and start at 1
        assert seqs[0] == 1, f"{name}: first event_seq must be 1 (transport fixture)"
        assert len(seqs) == len(set(seqs)), (
            f"{name}: duplicate event_seq values in transport fixture"
        )

    # Every question_update and result must have content_revision >= 1
    for ev in events:
        if ev.get("event") in ("question_update", "result"):
            rev = ev.get("context", {}).get("content_revision")
            assert rev is not None and rev >= 1, (
                f"{name}: {ev.get('event')} event missing valid content_revision: {rev}"
            )

    # Every question_terminal must have required payload fields
    for ev in events:
        if ev.get("event") == "question_terminal":
            p = ev.get("payload", {})
            for required in (
                "termination_reason", "has_final", "delivery_status",
                "expected", "delivered", "missing",
            ):
                assert required in p, (
                    f"{name}: question_terminal missing required field: {required!r}"
                )


@pytest.mark.parametrize("name", _LEGACY_FIXTURES)
def test_legacy_fixture_exists_and_valid(name: str) -> None:
    """Each legacy fixture must exist, be valid JSON-lines, and use the old format."""
    path = LEGACY_FIXTURE_DIR / name
    assert path.exists(), f"Legacy fixture {name} is missing"

    events = _load_jsonl(path)
    assert len(events) > 0, f"{name}: fixture is empty"

    # First event must be 'started' in the old format (no 'context' key)
    assert events[0].get("event") == "started", (
        f"{name}: first event is {events[0].get('event')!r}, expected 'started'"
    )
    # Legacy format uses 'data' not 'context'/'payload' at the top level
    assert "context" not in events[0], (
        f"{name}: legacy fixture must not have 'context' key at top level"
    )
    assert "data" in events[0], (
        f"{name}: legacy fixture must have 'data' key at top level"
    )

    # Last event must be 'done'
    assert events[-1].get("event") == "done", (
        f"{name}: last event is {events[-1].get('event')!r}, expected 'done'"
    )

    # Must have at least one 'result' event
    result_events = [ev for ev in events if ev.get("event") == "result"]
    assert len(result_events) > 0, f"{name}: legacy fixture has no result events"

    # Results must have question content in 'data' (JSON string)
    for ev in result_events:
        assert "data" in ev, f"{name}: result event missing 'data'"
        data = json.loads(ev["data"])
        assert "id" in data or "題目" in data, (
            f"{name}: result data missing expected question fields"
        )


# ---------------------------------------------------------------------------
# Cross-fixture consistency checks
# ---------------------------------------------------------------------------


def test_all_v2_fixtures_covered_by_registry() -> None:
    """Every .jsonl file in generation_v2/ must be in the registry."""
    on_disk = {p.name for p in V2_FIXTURE_DIR.glob("*.jsonl")}
    registered = set(_V2_FIXTURES)
    missing_from_registry = on_disk - registered
    assert not missing_from_registry, (
        "These fixtures are on disk but not in the test registry:\n"
        + "\n".join(sorted(missing_from_registry))
        + "\nAdd them to _V2_FIXTURES in test_754_fixture_drift.py"
    )


def test_all_legacy_fixtures_covered_by_registry() -> None:
    """Every .jsonl file in generation_legacy/ must be in the legacy registry."""
    on_disk = (
        {p.name for p in LEGACY_FIXTURE_DIR.glob("*.jsonl")}
        if LEGACY_FIXTURE_DIR.exists()
        else set()
    )
    registered = set(_LEGACY_FIXTURES)
    missing_from_registry = on_disk - registered
    assert not missing_from_registry, (
        "These legacy fixtures are on disk but not in the test registry:\n"
        + "\n".join(sorted(missing_from_registry))
        + "\nAdd them to _LEGACY_FIXTURES in test_754_fixture_drift.py"
    )


def test_fixture_run_id_is_normalized() -> None:
    """All v2 fixtures must normalize run_id to 'RUN' (reproducible output)."""
    for name in _V2_FIXTURES:
        path = V2_FIXTURE_DIR / name
        if not path.exists():
            pytest.skip(f"{name} does not exist")
        text = path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in text.splitlines() if line.strip()]
        for ev in events:
            ctx = ev.get("context", {})
            run_id = ctx.get("run_id")
            if run_id is not None:
                assert run_id == "RUN", (
                    f"{name}: run_id is {run_id!r}, expected 'RUN' (un-normalized fixture). "
                    "Regenerate with GENERATE_V2_FIXTURE=1."
                )
