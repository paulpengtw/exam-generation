"""Pure helpers for assembling the question_terminal summary.

Three independently testable units cover distinct concerns:

1. _compute_review          – maps verification evidence to the review dict.
2. _compute_expected_delivered_missing
                            – resolves fixed-slot positions and image assets into
                              the expected / delivered / missing slot lists.
3. _compute_delivery_status – collapses finality + missing into a delivery_status
                              string.

_QuestionPositionResolution bundles the per-question position-resolution inputs
that were previously passed as a data clump (announced_slots, verification_trail,
resolved_subquestion_configs, resolved_subquestion_count) so every exit can hand
them through a single typed boundary.  Issue #858 will use this boundary to
collapse the worker exits into a shared finalize path.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path as _Path2
from typing import Any

# PNG file signature: the first 8 bytes of any valid PNG file.
# Files that do not start with this signature are corrupt / truncated renders
# and must be classified as ``empty_image`` rather than delivered (issue #939).
_PNG_MAGIC: bytes = b"\x89PNG\r\n\x1a\n"


def _is_valid_png_header(path: _Path2) -> bool:
    """Return True iff *path* starts with the 8-byte PNG magic bytes."""
    try:
        with path.open("rb") as fh:
            header = fh.read(8)
    except OSError:
        return False
    return header == _PNG_MAGIC


@dataclasses.dataclass(frozen=True)
class _QuestionPositionResolution:
    """Immutable bundle of per-question position-resolution inputs.

    ``has_per_question_resolution`` distinguishes between:
      True  – the worker resolved its own subquestion configs / count (even when
              the resolved value is None, as for a flat math question that has no
              grouped slots).
      False – no per-question resolution was supplied; the composition point falls
              back to the batch-level params for grouping decisions.
    """

    announced_slots: list[dict[str, Any]] | None = None
    verification_trail: list[dict[str, Any]] | None = None
    resolved_subquestion_configs: list[Any] | None = None
    resolved_subquestion_count: int | None = None
    has_per_question_resolution: bool = False


# ---------------------------------------------------------------------------
# Unit 1: review pairing
# ---------------------------------------------------------------------------


def _compute_review(
    *,
    has_final: bool,
    skip_verify: bool,
    question: Any | None,
    final_revision: int | None,
    unknown_reason: str | None,
    verification_trail: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Build the review dict from verification evidence.

    The review is purely a function of the inputs; it does not read any files
    or perform I/O.

    Pairing rule:  a verification entry is accepted only when its
    ``content_revision`` integer equals ``final_revision`` exactly – an older
    entry from a superseded correction round must not be reported as evidence
    for the current final.
    """
    if not has_final:
        return {
            "status": "unknown",
            "reason": unknown_reason or "no final content",
        }
    if skip_verify:
        return {
            "status": "skipped",
            "content_revision": final_revision,
        }
    if question is not None and getattr(question, "verification", None) is not None:
        verification_entries = [
            entry
            for entry in reversed(verification_trail or [])
            if isinstance(entry, Mapping) and entry.get("kind") == "verification"
        ]
        verification_revision = (
            verification_entries[0].get("content_revision")
            if verification_entries
            else None
        )
        if (
            isinstance(verification_revision, int)
            and not isinstance(verification_revision, bool)
            and verification_revision == final_revision
        ):
            passed = question.verification.passed
            return {
                "status": "passed" if passed else "failed",
                "content_revision": final_revision,
            }
        return {
            "status": "unknown",
            "reason": (
                "no matching verification evidence"
                if verification_entries
                else "no verification evidence"
            ),
        }
    return {
        "status": "unknown",
        "reason": "no verification evidence",
    }


# ---------------------------------------------------------------------------
# Unit 2: expected / delivered / missing items
# ---------------------------------------------------------------------------


def _compute_expected_delivered_missing(
    *,
    question_id: str,
    question: Any | None,
    params: Any,
    output_dir: Any,  # Path | None
    has_final: bool,
    termination_reason: str,
    resolution: _QuestionPositionResolution,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the expected, delivered, and missing slot lists.

    Fixed grouped slots are identified by the announced plan or the resolved
    count.  Renderer mode is deliberately kept out of the obligation set: only
    an adopted chart/image or an explicitly visual subquestion configuration
    creates an image slot.
    """
    from pathlib import Path as _Path

    expected: list[dict[str, Any]] = []
    delivered: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    # Determine whether this question has fixed grouped slots.
    is_fixed_group = resolution.announced_slots is not None or (
        resolution.has_per_question_resolution
        and resolution.resolved_subquestion_count is not None
    ) or (
        not resolution.has_per_question_resolution
        and getattr(params, "sub_question_count", None) is not None
    )

    def _add_image_slot(
        *,
        subquestion_id: str | None,
        filename: str | None,
        adopted: bool,
        reason: str,
        subquestion_index: int | None = None,
    ) -> None:
        if not adopted and not filename:
            return
        slot: dict[str, Any] = {
            "kind": "image",
            "question_id": question_id,
            "subquestion_id": subquestion_id,
        }
        if subquestion_index is not None:
            slot["subquestion_index"] = subquestion_index
        expected.append(slot)
        if filename and output_dir is not None:
            img_path = _Path(output_dir) / filename
            if img_path.exists():
                # A delivered image must have a valid PNG header (issue #939).
                # Files that are empty, truncated, or have a bad magic header
                # (e.g. HTML error pages written to the output path) are treated
                # as render failures rather than delivered images.
                if img_path.stat().st_size >= 8 and _is_valid_png_header(img_path):
                    delivered.append(slot)
                    return
                # File exists but is empty, truncated, or not a valid PNG
                missing.append({**slot, "reason": "empty_image"})
                return
        missing.append({**slot, "reason": reason})

    if is_fixed_group:
        # Resolve configs from the per-question resolution or fall back to batch.
        if not resolution.has_per_question_resolution:
            configs: Any = getattr(params, "subquestion_configs", None) or []
        else:
            configs = resolution.resolved_subquestion_configs or []
        if isinstance(configs, str):
            try:
                decoded_configs = json.loads(configs)
            except (TypeError, json.JSONDecodeError):
                decoded_configs = []
            configs = decoded_configs if isinstance(decoded_configs, list) else []

        slot_manifest = resolution.announced_slots
        if slot_manifest is None and not has_final and termination_reason == "failed":
            if resolution.has_per_question_resolution:
                slot_count = resolution.resolved_subquestion_count or len(configs) or 0
            else:
                slot_count = (
                    getattr(params, "sub_question_count", None)
                    or len(configs)
                    or 0
                )
            slot_manifest = [
                {
                    "subquestion_index": slot_index,
                    "id": f"{question_id}-sq{slot_index + 1:03d}",
                    "序號": slot_index + 1,
                }
                for slot_index in range(slot_count)
            ]

        visual_types = {"含圖片", "graphs/charts/tables"}

        def _config_value(config: Any, key: str) -> Any:
            if isinstance(config, dict):
                return config.get(key)
            return getattr(config, key, None)

        if slot_manifest is not None:
            subquestions = (
                list(getattr(question, "subquestions", []) or [])
                if question is not None
                else []
            )
            by_id = {
                getattr(sub, "id", None): sub
                for sub in subquestions
                if getattr(sub, "id", None)
            }
            for pos, raw_slot in enumerate(slot_manifest):
                slot_index = raw_slot.get("subquestion_index")
                if not isinstance(slot_index, int) or slot_index < 0:
                    slot_index = pos
                raw_id = raw_slot.get("id") or raw_slot.get("subquestion_id")
                subquestion_id = (
                    raw_id
                    if isinstance(raw_id, str) and raw_id
                    else f"{question_id}-sq{slot_index + 1:03d}"
                )
                sub_slot = {
                    "kind": "subquestion",
                    "question_id": question_id,
                    "subquestion_id": subquestion_id,
                    "subquestion_index": slot_index,
                }
                expected.append(sub_slot)
                sub = by_id.get(subquestion_id)
                if sub is None:
                    missing.append({**sub_slot, "reason": "subquestion not delivered"})
                else:
                    delivered.append(sub_slot)

                if has_final and question is not None:
                    config = configs[slot_index] if slot_index < len(configs) else None
                    spec_adopted = bool(
                        sub is not None
                        and (
                            getattr(sub, "chart_spec", None) is not None
                            or getattr(sub, "image_spec", None) is not None
                        )
                    )
                    explicitly_visual = bool(
                        config is not None
                        and (
                            _config_value(config, "content_type") in visual_types
                            or _config_value(config, "figure_kind")
                        )
                    )
                    # Structured per-slot reason:
                    # • spec_adopted → spec was set but render failed or produced
                    #   no file (or a 0-byte file, handled inside _add_image_slot)
                    # • explicitly_visual but no spec → LLM omitted the spec
                    if spec_adopted:
                        img_reason = "render_failed"
                    elif explicitly_visual:
                        img_reason = "spec_missing"
                    else:
                        img_reason = "image not delivered"
                    _add_image_slot(
                        subquestion_id=subquestion_id,
                        filename=getattr(sub, "圖片", None) if sub is not None else None,
                        adopted=spec_adopted or explicitly_visual,
                        reason=img_reason,
                        subquestion_index=slot_index,
                    )

        if has_final and question is not None:
            _add_image_slot(
                subquestion_id=None,
                filename=getattr(question, "圖片", None),
                adopted=(
                    getattr(question, "chart_spec", None) is not None
                    or getattr(question, "image_spec", None) is not None
                ),
                reason="render_failed",
            )
    elif has_final and question is not None:
        # Flat question: an image slot exists only when the pipeline adopted an
        # image (chart_spec or image_spec non-None on the final question).
        has_image_spec = (
            getattr(question, "chart_spec", None) is not None
            or getattr(question, "image_spec", None) is not None
        )
        _add_image_slot(
            subquestion_id=None,
            filename=getattr(question, "圖片", None),
            adopted=has_image_spec,
            reason="render_failed",
        )

    return expected, delivered, missing


# ---------------------------------------------------------------------------
# Unit 3: delivery completeness
# ---------------------------------------------------------------------------


def _compute_delivery_status(
    *,
    has_final: bool,
    termination_reason: str,
    missing: list[dict[str, Any]],
) -> str:
    """Determine the delivery_status from finality and missing slots.

    Completeness rule:
      - No final → 'unknown' (cancelled) or 'none' (failed/other).
      - Final + missing slots → 'partial'.
      - Final + no missing → 'complete'.
    """
    if not has_final:
        if termination_reason == "cancelled":
            return "unknown"
        return "none"
    if missing:
        return "partial"
    return "complete"
