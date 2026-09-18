"""QuestionSnapshotLedger – per-question content revision counter.

Each call to ``commit()`` computes a content signature for the question and
assigns the next revision number ONLY when the signature changes from the
previous commit. Revisions start at 1 and are strictly monotonic per
question_id.

Content signature: stable JSON (sort_keys, ensure_ascii=False) of the question
dict with these keys removed at every depth:
  verification, verification_trail, figure_policy_trail,
  reference_example_record, image_base64, metadata
PLUS the sha256 hex of bytes of each image file named by the top-level '圖片'
key and each 'subquestions[*].圖片' key, resolved under ``output_dir``.
A missing file contributes the literal string 'missing'.

This class is shared across worker threads and is therefore thread-safe.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

# Keys to strip from the question at any depth before computing the signature.
_EXCLUDED_KEYS: frozenset[str] = frozenset(
    [
        "verification",
        "verification_trail",
        "figure_policy_trail",
        "reference_example_record",
        "image_base64",
        "metadata",
    ]
)


def _strip_excluded(obj: Any) -> Any:
    """Recursively remove excluded keys from dicts; leave other types intact."""
    if isinstance(obj, dict):
        return {
            k: _strip_excluded(v)
            for k, v in obj.items()
            if k not in _EXCLUDED_KEYS
        }
    if isinstance(obj, list):
        return [_strip_excluded(item) for item in obj]
    return obj


def _image_hash(filename: str | None, output_dir: Path | None) -> str:
    """Return sha256 hex of the image bytes, or 'missing' when absent."""
    if not filename:
        return "missing"
    if output_dir is None:
        return "missing"
    path = output_dir / filename
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_signature(question: dict[str, Any], output_dir: Path | None) -> str:
    """Compute a stable string signature for the question content."""
    stripped = _strip_excluded(question)
    json_part = json.dumps(stripped, sort_keys=True, ensure_ascii=False)

    # Collect image filenames from 圖片 and subquestions[*].圖片
    image_hashes: list[str] = []
    top_img = question.get("圖片")
    if top_img:
        image_hashes.append(f"top:{_image_hash(top_img, output_dir)}")
    for sub in question.get("subquestions") or []:
        if isinstance(sub, dict):
            sub_img = sub.get("圖片")
            if sub_img:
                image_hashes.append(f"sub:{_image_hash(sub_img, output_dir)}")

    if image_hashes:
        return json_part + "|" + "|".join(image_hashes)
    return json_part


class QuestionSnapshotLedger:
    """Thread-safe per-question content revision tracker.

    ``commit(question_dict, output_dir)`` returns ``(revision, snapshot)``
    where revision only increments when the effective content changes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # question_id -> current revision number (0 = not yet committed)
        self._revisions: dict[str, int] = {}
        # question_id -> last-seen content signature
        self._signatures: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def commit(
        self,
        question: dict[str, Any],
        output_dir: Path | None,
    ) -> tuple[int, dict[str, Any]]:
        """Record a content snapshot; return (revision, deep_copy_snapshot).

        The revision only increments when the content signature changes.
        The returned snapshot is a deep copy of ``question``.
        """
        question_id: str = question["id"]
        sig = _content_signature(question, output_dir)
        snapshot = copy.deepcopy(question)

        with self._lock:
            prev_sig = self._signatures.get(question_id)
            if prev_sig is None or sig != prev_sig:
                rev = self._revisions.get(question_id, 0) + 1
                self._revisions[question_id] = rev
                self._signatures[question_id] = sig
            else:
                rev = self._revisions[question_id]

        return rev, snapshot

    # ------------------------------------------------------------------
    # Legacy / compat helpers (kept for tests that pre-date commit())
    # ------------------------------------------------------------------

    def latest_revision(self, question_id: str) -> int:
        """Return the current revision number for *question_id* (0 if unseen)."""
        with self._lock:
            return self._revisions.get(question_id, 0)
