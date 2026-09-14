"""QuestionSnapshotLedger – per-question content revision counter.

Each call to ``record()`` assigns the next revision number for a given
question_id and stores a shallow copy of the content snapshot. Revisions
start at 1 and are strictly monotonic per question_id.

This class is shared across worker threads and is therefore thread-safe.
"""

from __future__ import annotations

import threading
from typing import Any


class QuestionSnapshotLedger:
    """Thread-safe per-question content revision tracker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # question_id -> current revision number (0 = not yet recorded)
        self._revisions: dict[str, int] = {}
        # question_id -> list of stored content snapshots (index 0 = rev 1)
        self._snapshots: dict[str, list[dict[str, Any]]] = {}

    def record(self, question_id: str, content: dict[str, Any]) -> int:
        """Record a new content snapshot and return its revision number (1-based)."""
        with self._lock:
            rev = self._revisions.get(question_id, 0) + 1
            self._revisions[question_id] = rev
            self._snapshots.setdefault(question_id, []).append(dict(content))
            return rev

    def latest_revision(self, question_id: str) -> int:
        """Return the current revision number for *question_id* (0 if unseen)."""
        with self._lock:
            return self._revisions.get(question_id, 0)

    def snapshot_at(self, question_id: str, revision: int) -> dict[str, Any] | None:
        """Return the content snapshot stored at *revision* (1-based), or None."""
        with self._lock:
            snapshots = self._snapshots.get(question_id)
            if snapshots is None or revision < 1 or revision > len(snapshots):
                return None
            return dict(snapshots[revision - 1])
