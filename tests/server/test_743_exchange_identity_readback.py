"""Integration test: context-bearing exchange identity survives the persistence
write path and reads back correctly through GET /api/generation-logs/{id}/exchanges.

Covers acceptance criterion for #743:
  "有 context 的 LLM exchanges 按 run/call 配對 … 驗證 UI 與讀回 exchanges"

persistence.py strips the flat run_id/call_id/operation_id/retry_of_call_id
fields before writing to the DB (schema compat); the only surviving copy of
identity is inside request_body["identity"] / response_body["identity"].  These
tests ensure:
  - two interleaved same-agent context-bearing exchanges are NOT cross-paired,
  - each returned exchange's body carries the matching identity dict,
  - a JSON retry's body carries retry_of_call_id,
  - a legacy (no-context) exchange has NO identity key in its bodies,
  - a whole-slot redo (new operation_id, no retry_of_call_id) keeps superseded
    and superseding operations' exchanges separate.

FIX 3 note: _req/_resp helpers are imported from test_exchange_recorder.py,
which is the established pattern for cross-module test imports in this repo
(e.g. from tests.server.test_generate_body_transport import transport_client).
The helpers were extended there to accept **extra identity kwargs.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.generate import persistence
from tests.server.test_exchange_persistence_integration import exchange_store
from tests.server.test_exchange_recorder import _req, _resp

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _record_all(recorder, events: list[dict]) -> None:
    """Feed a sequence of events to the recorder from a thread (matches production path)."""
    for event in events:
        recorder(event)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_context_bearing_identity_survives_persistence_and_api_readback(
    tmp_path: Path,
) -> None:
    """Two interleaved same-agent context-bearing exchanges, one JSON retry, one
    legacy exchange — all written through make_exchange_recorder and read back
    via the API.  Asserts correct pairing and body identity, no cross-pairing.
    """
    run_id = "RUN-743"

    # Events for call A (operation:a, call:a)
    req_a = _req(
        "sub_generator#1", purpose="slot-a",
        run_id=run_id, operation_id=f"{run_id}:op:a", call_id=f"{run_id}:call:a",
    )
    req_b = _req(
        "sub_generator#1", purpose="slot-b",
        run_id=run_id, operation_id=f"{run_id}:op:b", call_id=f"{run_id}:call:b",
    )
    resp_a = _resp(
        "sub_generator#1", purpose="slot-a",
        run_id=run_id, operation_id=f"{run_id}:op:a", call_id=f"{run_id}:call:a",
    )
    resp_b = _resp(
        "sub_generator#1", purpose="slot-b",
        run_id=run_id, operation_id=f"{run_id}:op:b", call_id=f"{run_id}:call:b",
    )

    # JSON retry for slot-a: same operation, new call, retry_of_call_id set
    req_retry = _req(
        "sub_generator#1", purpose="slot-a",
        run_id=run_id, operation_id=f"{run_id}:op:a",
        call_id=f"{run_id}:call:a2",
        retry_of_call_id=f"{run_id}:call:a",
    )
    resp_retry = _resp(
        "sub_generator#1", purpose="slot-a",
        run_id=run_id, operation_id=f"{run_id}:op:a",
        call_id=f"{run_id}:call:a2",
        retry_of_call_id=f"{run_id}:call:a",
    )

    # Legacy exchange: no run_id/call_id — old schema, no identity in bodies
    req_legacy = _req("generator", purpose="generate")
    resp_legacy = _resp("generator", purpose="generate")

    # Interleaved order: A request, B request, A response, B response, then retry,
    # then legacy — matches a real concurrent-worker scenario.
    events = [req_a, req_b, resp_a, resp_b, req_retry, resp_retry, req_legacy, resp_legacy]

    order_counter = itertools.count(1)
    order_lock = threading.Lock()

    def next_order() -> int:
        with order_lock:
            return next(order_counter)

    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            recorder = persistence.make_exchange_recorder(
                generation_log_id=store.log_id,
                retention_days=30,
                loop=asyncio.get_running_loop(),
                session_factory=store.sessions,
                next_order=next_order,
            )
            # Run recording in a thread (recorder is called from workers in prod)
            await asyncio.to_thread(_record_all, recorder, events)
            await recorder.flush()

            rows = await store.exchanges()

        # --- basic shape ---
        assert len(rows) == 4, (
            f"expected 4 exchanges, got {len(rows)}: {[r['purpose'] for r in rows]}"
        )
        purposes = [r["purpose"] for r in rows]
        # Three slot-a/b rows (original call-a, call-b, retry call-a2) + one legacy
        assert "slot-a" in purposes
        assert "slot-b" in purposes
        assert "generate" in purposes

        by_purpose: dict[str, list[dict]] = {}
        for row in rows:
            by_purpose.setdefault(row["purpose"], []).append(row)

        # --- slot-b: one row, no cross-pairing with slot-a ---
        slot_b_rows = by_purpose["slot-b"]
        assert len(slot_b_rows) == 1
        row_b = slot_b_rows[0]
        assert row_b["request_body"]["identity"] == {
            "run_id": run_id,
            "operation_id": f"{run_id}:op:b",
            "call_id": f"{run_id}:call:b",
        }, f"slot-b identity wrong: {row_b['request_body'].get('identity')}"
        assert row_b["response_body"]["identity"] == {
            "run_id": run_id,
            "operation_id": f"{run_id}:op:b",
            "call_id": f"{run_id}:call:b",
        }

        # --- slot-a: two rows (original call and JSON retry) ---
        slot_a_rows = sorted(by_purpose["slot-a"], key=lambda r: r["exchange_order"])
        assert len(slot_a_rows) == 2

        # First slot-a row is the original call (no retry_of_call_id)
        row_a_orig = slot_a_rows[0]
        orig_req_identity = row_a_orig["request_body"]["identity"]
        assert orig_req_identity["call_id"] == f"{run_id}:call:a"
        assert orig_req_identity["run_id"] == run_id
        assert orig_req_identity["operation_id"] == f"{run_id}:op:a"
        assert "retry_of_call_id" not in orig_req_identity
        assert row_a_orig["response_body"]["identity"] == orig_req_identity

        # Second slot-a row is the retry; it carries retry_of_call_id
        row_a_retry = slot_a_rows[1]
        retry_req_identity = row_a_retry["request_body"]["identity"]
        assert retry_req_identity["call_id"] == f"{run_id}:call:a2"
        assert retry_req_identity["retry_of_call_id"] == f"{run_id}:call:a"
        assert retry_req_identity["operation_id"] == f"{run_id}:op:a"
        assert row_a_retry["response_body"]["identity"] == retry_req_identity

        # --- legacy exchange: NO identity key in either body ---
        legacy_rows = by_purpose["generate"]
        assert len(legacy_rows) == 1
        row_legacy = legacy_rows[0]
        assert "identity" not in row_legacy["request_body"], (
            f"legacy request body should have no identity, got {row_legacy['request_body']}"
        )
        assert "identity" not in row_legacy["response_body"], (
            f"legacy response body should have no identity, got {row_legacy['response_body']}"
        )

    asyncio.run(exercise())


def test_whole_slot_redo_keeps_superseded_and_superseding_operations_separate(
    tmp_path: Path,
) -> None:
    """#743 criterion: a whole-slot redo uses a NEW operation_id (no retry_of_call_id).

    supersedes_operation_id is carried only on stage start events, NOT on exchange
    rows — exchanges carry run_id/operation_id/call_id/retry_of_call_id only.

    Verify that read-back rows keep the superseded and superseding operations'
    exchanges separate: distinct operation_id values, each request paired with its
    own response, no cross-pairing with the superseded call.
    """
    run_id = "RUN-743-REDO"
    op1_id = f"{run_id}:op:first"
    op2_id = f"{run_id}:op:second"

    # Superseded operation (first attempt at the slot)
    req_op1 = _req(
        "sub_generator#1", purpose="slot-redo",
        run_id=run_id, operation_id=op1_id, call_id=f"{run_id}:call:op1",
    )
    resp_op1 = _resp(
        "sub_generator#1", purpose="slot-redo",
        run_id=run_id, operation_id=op1_id, call_id=f"{run_id}:call:op1",
    )

    # Superseding operation (whole-slot redo — new operation, fresh call, no retry_of_call_id)
    req_op2 = _req(
        "sub_generator#1", purpose="slot-redo",
        run_id=run_id, operation_id=op2_id, call_id=f"{run_id}:call:op2",
    )
    resp_op2 = _resp(
        "sub_generator#1", purpose="slot-redo",
        run_id=run_id, operation_id=op2_id, call_id=f"{run_id}:call:op2",
    )

    events = [req_op1, resp_op1, req_op2, resp_op2]

    order_counter = itertools.count(1)
    order_lock = threading.Lock()

    def next_order() -> int:
        with order_lock:
            return next(order_counter)

    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            recorder = persistence.make_exchange_recorder(
                generation_log_id=store.log_id,
                retention_days=30,
                loop=asyncio.get_running_loop(),
                session_factory=store.sessions,
                next_order=next_order,
            )
            await asyncio.to_thread(_record_all, recorder, events)
            await recorder.flush()

            rows = await store.exchanges()

        # Two exchange rows (one per operation)
        assert len(rows) == 2, (
            f"expected 2 exchanges (one per operation), got {len(rows)}: "
            f"{[r.get('request_body', {}).get('identity') for r in rows]}"
        )

        rows_by_op: dict[str, dict] = {}
        for row in rows:
            op_id = row["request_body"]["identity"]["operation_id"]
            assert op_id not in rows_by_op, f"duplicate operation_id in read-back: {op_id}"
            rows_by_op[op_id] = row

        # Both operations must be present
        assert op1_id in rows_by_op, f"superseded operation {op1_id!r} missing"
        assert op2_id in rows_by_op, f"superseding operation {op2_id!r} missing"

        row1 = rows_by_op[op1_id]
        row2 = rows_by_op[op2_id]

        # Superseded operation: paired with its own call, no retry_of_call_id
        op1_identity = row1["request_body"]["identity"]
        assert op1_identity["call_id"] == f"{run_id}:call:op1"
        assert op1_identity["operation_id"] == op1_id
        assert "retry_of_call_id" not in op1_identity
        assert row1["response_body"]["identity"] == op1_identity

        # Superseding operation: fresh call, no retry_of_call_id (not a JSON retry)
        op2_identity = row2["request_body"]["identity"]
        assert op2_identity["call_id"] == f"{run_id}:call:op2"
        assert op2_identity["operation_id"] == op2_id
        assert "retry_of_call_id" not in op2_identity
        assert row2["response_body"]["identity"] == op2_identity

        # No cross-pairing: response of op1 must not appear in op2's row and vice versa
        assert row1["request_body"]["identity"]["operation_id"] == op1_id
        assert row2["request_body"]["identity"]["operation_id"] == op2_id

    asyncio.run(exercise())
