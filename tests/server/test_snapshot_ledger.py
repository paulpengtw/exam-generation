"""Slice 5 – QuestionSnapshotLedger tests (new commit() API).

The ledger tracks per-question content revisions using a content-signature
comparison: revision only increments when the effective content changes.
Signature = stable JSON of the question (keys removed at any depth:
verification, verification_trail, figure_policy_trail,
reference_example_record, image_base64, metadata) PLUS sha256 of referenced
image files (missing files contribute 'missing').

API: commit(question_dict, output_dir) -> (revision: int, snapshot: dict)
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path


# ---------------------------------------------------------------------------
# Basic revision behaviour
# ---------------------------------------------------------------------------


def test_first_commit_returns_revision_one(tmp_path: Path) -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    q = {"id": "q_abc_001", "題目": "question text"}
    rev, snap = ledger.commit(q, tmp_path)
    assert rev == 1


def test_identical_content_keeps_same_revision(tmp_path: Path) -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    q = {"id": "q_abc_001", "題目": "same text"}
    rev1, _ = ledger.commit(q, tmp_path)
    rev2, _ = ledger.commit(dict(q), tmp_path)
    assert rev1 == 1
    assert rev2 == 1


def test_changed_題目_text_increments_revision(tmp_path: Path) -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    q1 = {"id": "q_abc_001", "題目": "original text"}
    q2 = {"id": "q_abc_001", "題目": "changed text"}
    rev1, _ = ledger.commit(q1, tmp_path)
    rev2, _ = ledger.commit(q2, tmp_path)
    assert rev1 == 1
    assert rev2 == 2


def test_verification_only_change_does_not_increment(tmp_path: Path) -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    q1 = {"id": "q_abc_001", "題目": "stable text", "verification": None}
    q2 = {"id": "q_abc_001", "題目": "stable text", "verification": {"passed": True}}
    rev1, _ = ledger.commit(q1, tmp_path)
    rev2, _ = ledger.commit(q2, tmp_path)
    assert rev1 == 1
    assert rev2 == 1


def test_metadata_only_change_does_not_increment(tmp_path: Path) -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    q1 = {"id": "q_abc_001", "題目": "stable text", "metadata": None}
    q2 = {"id": "q_abc_001", "題目": "stable text", "metadata": {"grade": 8}}
    rev1, _ = ledger.commit(q1, tmp_path)
    rev2, _ = ledger.commit(q2, tmp_path)
    assert rev1 == 1
    assert rev2 == 1


def test_image_bytes_changed_increments_revision(tmp_path: Path) -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    img_file = tmp_path / "chart.png"
    img_file.write_bytes(b"version1")
    q = {"id": "q_abc_001", "題目": "same text", "圖片": "chart.png"}
    ledger = QuestionSnapshotLedger()
    rev1, _ = ledger.commit(q, tmp_path)
    img_file.write_bytes(b"version2")
    rev2, _ = ledger.commit(q, tmp_path)
    assert rev1 == 1
    assert rev2 == 2


def test_missing_image_contributes_missing_string(tmp_path: Path) -> None:
    """When image file doesn't exist, revision is still computed stably."""
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    q = {"id": "q_abc_001", "題目": "text", "圖片": "nonexistent.png"}
    ledger = QuestionSnapshotLedger()
    rev1, _ = ledger.commit(q, tmp_path)
    rev2, _ = ledger.commit(q, tmp_path)
    assert rev1 == 1
    assert rev2 == 1  # same "missing" sentinel both times


def test_snapshot_is_deep_copy_unaffected_by_later_mutation(tmp_path: Path) -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    q = {"id": "q_abc_001", "題目": "original", "subquestions": [{"text": "sub"}]}
    _, snap = ledger.commit(q, tmp_path)
    # Mutate original dict and nested list
    q["題目"] = "mutated"
    q["subquestions"][0]["text"] = "mutated sub"
    # Snapshot must be unchanged
    assert snap["題目"] == "original"
    assert snap["subquestions"][0]["text"] == "sub"


def test_two_threads_different_questions_independent(tmp_path: Path) -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    results: dict[str, list[int]] = {}
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker(qid: str) -> None:
        try:
            q = {"id": qid, "題目": "text"}
            revs = []
            for _ in range(5):
                rev, _ = ledger.commit(q, tmp_path)
                revs.append(rev)
            with lock:
                results[qid] = revs
        except Exception as e:
            with lock:
                errors.append(e)

    t1 = threading.Thread(target=worker, args=("q_x_001",))
    t2 = threading.Thread(target=worker, args=("q_y_001",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors, f"thread errors: {errors}"
    # Each question stays at rev 1 (identical content)
    assert results["q_x_001"] == [1, 1, 1, 1, 1]
    assert results["q_y_001"] == [1, 1, 1, 1, 1]


def test_concurrent_distinct_content_commits_same_question(tmp_path: Path) -> None:
    """Many threads committing different content to the same qid get distinct revs."""
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    revisions: list[int] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            q = {"id": "q_shared_001", "題目": f"unique text {i}"}
            rev, _ = ledger.commit(q, tmp_path)
            with lock:
                revisions.append(rev)
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"thread errors: {errors}"
    assert len(revisions) == 10
    assert sorted(revisions) == list(range(1, 11))


def test_subquestion_image_bytes_change_increments(tmp_path: Path) -> None:
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    img_file = tmp_path / "sub.png"
    img_file.write_bytes(b"v1")
    q = {
        "id": "q_abc_001",
        "題目": "text",
        "subquestions": [{"圖片": "sub.png", "text": "sub"}],
    }
    ledger = QuestionSnapshotLedger()
    rev1, _ = ledger.commit(q, tmp_path)
    img_file.write_bytes(b"v2")
    rev2, _ = ledger.commit(q, tmp_path)
    assert rev1 == 1
    assert rev2 == 2


def test_snapshot_result_excludes_excluded_keys(tmp_path: Path) -> None:
    """The returned snapshot should be the FULL deep copy, not the stripped version."""
    from server.generate.snapshot_ledger import QuestionSnapshotLedger

    ledger = QuestionSnapshotLedger()
    q = {"id": "q_abc_001", "題目": "text", "verification": {"passed": True}}
    _, snap = ledger.commit(q, tmp_path)
    # Snapshot preserves the original content (including excluded keys)
    assert snap.get("verification") == {"passed": True}


def test_run_context_has_snapshot_ledger_field() -> None:
    import dataclasses

    from server.generate.service import _RunContext

    fields = {f.name for f in dataclasses.fields(_RunContext)}
    assert "snapshot_ledger" in fields
