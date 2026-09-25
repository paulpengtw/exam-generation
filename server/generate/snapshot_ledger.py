"""QuestionSnapshotLedger – per-question content revision counter.

Each call to ``commit()`` computes a content signature for the question and
assigns the next revision number ONLY when the signature changes from the
previous commit. Revisions start at 1 and are strictly monotonic per
question_id.

Content signature: stable JSON (sort_keys, ensure_ascii=False) of the question
dict with these keys removed at every depth:
  verification, verification_trail, figure_policy_trail,
  reference_example_record, image_base64, metadata, review, progress,
  export and _export
PLUS the sha256 hex of bytes of each image file named by the top-level '圖片'
key and each 'subquestions[*].圖片' key, resolved under ``output_dir``.
A missing file contributes the literal string 'missing'.

This class is shared across worker threads and is therefore thread-safe.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from server.generate.event_protocol import QuestionTerminalPayload

# Keys to strip from the question at any depth before computing the signature.
_EXCLUDED_KEYS: frozenset[str] = frozenset(
    [
        "verification",
        "verification_trail",
        "figure_policy_trail",
        "reference_example_record",
        "image_base64",
        "metadata",
        "review",
        "progress",
        "export",
        "_export",
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


def _embedded_image_bytes(value: Any) -> bytes:
    """Decode an embedded image while ignoring presentation-only formatting."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if not isinstance(value, str):
        return json.dumps(value, sort_keys=True, ensure_ascii=False).encode()

    encoded = value.strip()
    if encoded.startswith("data:") and "," in encoded:
        encoded = encoded.split(",", 1)[1]
    encoded = "".join(encoded.split())
    try:
        padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
        return base64.b64decode(padded, validate=True)
    except (ValueError, TypeError):
        # Malformed provider output is still content.  Hash its normalized
        # transport value so an actual change cannot be hidden by exclusion.
        return encoded.encode()


def _embedded_image_hashes(
    obj: Any,
    *,
    path: tuple[str, ...] = (),
    excluded_parent: bool = False,
) -> list[str]:
    """Return stable hashes for content-bearing embedded image fields."""
    if isinstance(obj, dict):
        hashes: list[str] = []
        for key, value in obj.items():
            key_text = str(key)
            if key_text in _EXCLUDED_KEYS and key_text != "image_base64":
                continue
            if key_text == "image_base64" and not excluded_parent:
                digest = hashlib.sha256(_embedded_image_bytes(value)).hexdigest()
                hashes.append(f"embedded:{'.'.join(path + (key_text,))}:{digest}")
                continue
            hashes.extend(
                _embedded_image_hashes(
                    value,
                    path=path + (key_text,),
                    excluded_parent=excluded_parent or key_text in {
                        "verification",
                        "verification_trail",
                        "figure_policy_trail",
                        "reference_example_record",
                        "metadata",
                    },
                )
            )
        return hashes
    if isinstance(obj, list):
        hashes: list[str] = []
        for index, value in enumerate(obj):
            hashes.extend(
                _embedded_image_hashes(
                    value,
                    path=path + (str(index),),
                    excluded_parent=excluded_parent,
                )
            )
        return hashes
    return []


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

    embedded_hashes = sorted(_embedded_image_hashes(question))
    all_hashes = image_hashes + embedded_hashes
    if all_hashes:
        return json_part + "|" + "|".join(all_hashes)
    return json_part


class QuestionSnapshotLedger:
    """Thread-safe per-question content revision and slot tracker.

    ``commit(question_dict, output_dir)`` returns ``(revision, snapshot)``
    where revision only increments when the effective content changes.  The
    returned snapshot is a caller-owned copy; committed snapshots are not
    retained by the ledger.
    The first announced fixed-slot manifest is retained separately from content
    revisions so terminal evidence can use the plan as its source of truth.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # question_id -> current revision number (0 = not yet committed)
        self._revisions: dict[str, int] = {}
        # question_id -> last-seen content signature
        self._signatures: dict[str, str] = {}
        # question_id -> first announced fixed-slot manifest
        self._slot_manifests: dict[str, list[dict[str, Any]]] = {}
        # question_id -> immutable terminal seal (current signature, summary)
        self._terminal_seals: dict[str, tuple[str, dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def commit(
        self,
        question: dict[str, Any],
        output_dir: Path | None,
    ) -> tuple[int, dict[str, Any]]:
        """Record a content signature; return (revision, deep_copy_snapshot).

        The revision only increments when the content signature changes.  The
        returned snapshot is a deep copy of ``question`` and is not retained.
        """
        snapshot = copy.deepcopy(question)
        question_id: str = snapshot["id"]

        with self._lock:
            # Compute the signature from the same copied object that is
            # returned/stored.  This keeps concurrent queued mutations from
            # assigning a revision to content other than the snapshot.
            sig = _content_signature(snapshot, output_dir)
            sealed = self._terminal_seals.get(question_id)
            if sealed is not None and sig != sealed[0]:
                raise QuestionTerminalSealedError(
                    f"question {question_id!r} is sealed at its terminal content"
                )
            prev_sig = self._signatures.get(question_id)
            if prev_sig is None or sig != prev_sig:
                rev = self._revisions.get(question_id, 0) + 1
                self._revisions[question_id] = rev
                self._signatures[question_id] = sig
            else:
                rev = self._revisions[question_id]

        return rev, snapshot

    def seal_terminal(self, question_id: str, payload: dict[str, Any]) -> bool:
        """Seal one question's terminal summary exactly once.

        Returns ``True`` for the first seal and ``False`` for an identical
        re-send.  A different summary or a final revision that is not the
        latest committed revision is rejected.  The terminal itself is
        validated here so callers cannot bypass the protocol model by using
        the ledger as a lower-level guard.
        """
        validated = QuestionTerminalPayload.model_validate(payload)
        if any(slot.question_id != question_id for slot in (
            *validated.expected,
            *validated.delivered,
            *validated.missing,
        )):
            raise ValueError("terminal slot question_id does not match sealed question")
        canonical = validated.model_dump(mode="json", exclude_none=True)
        final_revision = validated.final_revision

        with self._lock:
            existing = self._terminal_seals.get(question_id)
            if existing is not None:
                if existing[1] == canonical:
                    return False
                raise QuestionTerminalConflictError(
                    f"question {question_id!r} received a contradictory terminal"
                )

            current_revision = self._revisions.get(question_id, 0)
            if validated.has_final and final_revision != current_revision:
                raise QuestionTerminalSealedError(
                    f"terminal final revision {final_revision!r} does not match "
                    f"latest revision {current_revision!r} for {question_id!r}"
                )
            signature = self._signatures.get(question_id, "")
            self._terminal_seals[question_id] = (signature, copy.deepcopy(canonical))
            return True

    def is_terminal_sealed(self, question_id: str) -> bool:
        """Return whether a question has an immutable terminal seal."""
        with self._lock:
            return question_id in self._terminal_seals

    def get_terminal(self, question_id: str) -> dict[str, Any] | None:
        """Return a caller-owned copy of the sealed terminal summary."""
        with self._lock:
            sealed = self._terminal_seals.get(question_id)
            return copy.deepcopy(sealed[1]) if sealed is not None else None

    def record_slot_manifest(
        self,
        question_id: str,
        slots: list[dict[str, Any]],
    ) -> None:
        """Record the first plan slot manifest for *question_id*.

        Plan announcements are authoritative and immutable for one question.
        Store a deep copy so a producer cannot mutate terminal evidence after
        the event has been observed.
        """
        manifest = copy.deepcopy(slots)
        with self._lock:
            self._slot_manifests.setdefault(question_id, manifest)

    def get_slot_manifest(self, question_id: str) -> list[dict[str, Any]] | None:
        """Return a deep copy of the announced slot manifest, if any."""
        with self._lock:
            manifest = self._slot_manifests.get(question_id)
            return copy.deepcopy(manifest) if manifest is not None else None

    # ------------------------------------------------------------------
    # Legacy / compat helpers (kept for tests that pre-date commit())
    # ------------------------------------------------------------------

    def latest_revision(self, question_id: str) -> int:
        """Return the current revision number for *question_id* (0 if unseen)."""
        with self._lock:
            return self._revisions.get(question_id, 0)


class QuestionTerminalSealedError(RuntimeError):
    """Raised when work attempts to change content after terminal sealing."""


class QuestionTerminalConflictError(RuntimeError):
    """Raised when a second terminal summary disagrees with the first one."""
