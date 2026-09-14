"""Slice 5 – QuestionSnapshotLedger tests.

The ledger tracks per-question content revisions. For each question_id
it assigns the next revision number every time a new content snapshot is
recorded. The first revision is 1.
"""
from __future__ import annotations


def test_ledger_first_revision_is_one() -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    rev = ledger.record("q_abc_001", content={"some": "data"})
    assert rev == 1


def test_ledger_second_revision_is_two() -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    ledger.record("q_abc_001", content={"v": 1})
    rev = ledger.record("q_abc_001", content={"v": 2})
    assert rev == 2


def test_ledger_different_questions_independent() -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    r1 = ledger.record("q_abc_001", content={"a": 1})
    r2 = ledger.record("q_abc_002", content={"b": 2})
    assert r1 == 1
    assert r2 == 1


def test_ledger_latest_revision_returns_current() -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    ledger.record("q_x_001", content={"v": 1})
    ledger.record("q_x_001", content={"v": 2})
    assert ledger.latest_revision("q_x_001") == 2


def test_ledger_latest_revision_zero_for_unknown() -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    assert ledger.latest_revision("q_unknown_001") == 0


def test_ledger_is_thread_safe() -> None:
    """Concurrent records for the same question must all get distinct revisions."""
    import threading

    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    revisions: list[int] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        rev = ledger.record("q_shared_001", content={"i": i})
        with lock:
            revisions.append(rev)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(revisions) == list(range(1, 11))


def test_run_context_has_snapshot_ledger_field() -> None:
    import dataclasses

    from server.generate.service import _RunContext

    fields = {f.name for f in dataclasses.fields(_RunContext)}
    assert "snapshot_ledger" in fields
