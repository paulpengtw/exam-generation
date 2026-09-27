"""test(754): Validate JSON examples in docs/generation-event-protocol.md.

Extracts every ```json ... ``` block from the protocol document and validates
each one that looks like an event envelope (contains "context" and "payload")
against the real contract types from server/generate/event_protocol.py.

Blocks that are partial schema illustrations (contain "..." or "< ... >") are
skipped because they are descriptive, not parseable JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from server.generate.event_protocol import (
    EventContext,
    QuestionTerminalPayload,
    StartedPayload,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DOCS_ROOT = Path(__file__).parent.parent.parent / "docs"
PROTOCOL_DOC = DOCS_ROOT / "generation-event-protocol.md"

_CODE_BLOCK_RE = re.compile(r"```json\n(.*?)```", re.DOTALL)


def _extract_json_blocks(path: Path) -> list[str]:
    """Return all ```json ... ``` block bodies from a Markdown file."""
    text = path.read_text(encoding="utf-8")
    return [m.group(1) for m in _CODE_BLOCK_RE.finditer(text)]


def _is_skippable(raw: str) -> bool:
    """True if the block contains template placeholders and cannot be parsed."""
    return "..." in raw or "< " in raw or "<prefix>" in raw


# ---------------------------------------------------------------------------
# Fixture: collect envelope examples
# ---------------------------------------------------------------------------


def _envelope_examples() -> list[tuple[str, dict]]:
    """Return (label, parsed_dict) for every parseable envelope block."""
    blocks = _extract_json_blocks(PROTOCOL_DOC)
    results = []
    for i, raw in enumerate(blocks):
        if _is_skippable(raw):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "context" in obj and "payload" in obj:
            results.append((f"block_{i}", obj))
        elif isinstance(obj, dict) and "_export" in obj:
            # _export examples are validated separately
            pass
    return results


def _export_examples() -> list[tuple[str, dict]]:
    """Return (label, export_dict) for _export schema examples."""
    blocks = _extract_json_blocks(PROTOCOL_DOC)
    results = []
    for i, raw in enumerate(blocks):
        if _is_skippable(raw):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "_export" in obj:
            results.append((f"block_{i}", obj["_export"]))
    return results


def _started_examples() -> list[tuple[str, dict]]:
    """Return (label, envelope) for envelopes whose payload has protocol_version=2."""
    return [
        (label, env)
        for label, env in _envelope_examples()
        if env["payload"].get("protocol_version") == 2
    ]


def _terminal_examples() -> list[tuple[str, dict]]:
    """Return (label, envelope) for envelopes whose payload has termination_reason."""
    return [
        (label, env)
        for label, env in _envelope_examples()
        if "termination_reason" in env["payload"]
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,envelope", _envelope_examples())
def test_envelope_context_valid(label: str, envelope: dict) -> None:
    """Every envelope block's context validates against EventContext."""
    ctx = EventContext(**envelope["context"])
    assert ctx.run_id, f"{label}: run_id must not be empty"
    assert ctx.event_seq >= 1, f"{label}: event_seq must be >= 1"


_STARTED_EXAMPLES = _started_examples()
_TERMINAL_EXAMPLES = _terminal_examples()

# Assert non-empty so a change that removes all examples fails loudly.
assert _STARTED_EXAMPLES, (
    "No started-payload examples found in the protocol doc — "
    "add at least one ```json block with protocol_version=2."
)
assert _TERMINAL_EXAMPLES, (
    "No terminal-payload examples found in the protocol doc — "
    "add at least one ```json block with termination_reason."
)


@pytest.mark.parametrize("label,envelope", _STARTED_EXAMPLES)
def test_started_payload_valid(label: str, envelope: dict) -> None:
    """Envelopes with protocol_version:2 in payload validate as StartedPayload."""
    payload = envelope["payload"]
    started = StartedPayload(**payload)
    assert started.protocol_version == 2
    assert len(started.questions) == started.total


@pytest.mark.parametrize("label,envelope", _TERMINAL_EXAMPLES)
def test_terminal_payload_valid(label: str, envelope: dict) -> None:
    """Envelopes with termination_reason in payload validate as QuestionTerminalPayload."""
    payload = envelope["payload"]
    terminal = QuestionTerminalPayload(**payload)
    assert terminal.termination_reason in ("normal", "failed", "cancelled")
    assert terminal.delivery_status in ("complete", "partial", "none", "unknown")


_EXPORT_REQUIRED_KEYS = {
    "format_version",
    "exported_at",
    "is_draft",
    "run_id",
    "index",
    "content_revision",
    "processing",
    "termination_reason",
    "delivery_status",
    "missing",
    "review",
}


@pytest.mark.parametrize("label,export_meta", _export_examples())
def test_export_meta_has_required_fields(label: str, export_meta: dict) -> None:
    """_export blocks must contain all required fields."""
    missing = _EXPORT_REQUIRED_KEYS - set(export_meta.keys())
    assert not missing, f"{label}: _export missing fields: {missing}"
    assert export_meta["format_version"] == 1, f"{label}: format_version must be 1"
    assert isinstance(export_meta["is_draft"], bool), f"{label}: is_draft must be bool"
    assert export_meta["processing"] in (
        "waiting",
        "running",
        "ended",
        "unknown",
    ), f"{label}: invalid processing value"
    if export_meta["termination_reason"] is not None:
        assert export_meta["termination_reason"] in (
            "normal",
            "failed",
            "cancelled",
        ), f"{label}: invalid termination_reason"
    if export_meta["delivery_status"] is not None:
        assert export_meta["delivery_status"] in (
            "complete",
            "partial",
            "none",
            "unknown",
        ), f"{label}: invalid delivery_status"
    review = export_meta.get("review", {})
    assert review.get("status") in (
        "passed",
        "failed",
        "skipped",
        "unknown",
    ), f"{label}: invalid review.status"


def test_doc_contains_envelope_examples() -> None:
    """The protocol doc must contain at least one envelope and one export example."""
    envelopes = _envelope_examples()
    exports = _export_examples()
    assert len(envelopes) >= 2, "Expected at least 2 envelope examples"
    assert len(exports) >= 1, "Expected at least 1 _export example"


def test_doc_states_slot_array_order_non_normative() -> None:
    """The protocol doc must state that slot array order is non-normative (#897)."""
    text = PROTOCOL_DOC.read_text(encoding="utf-8")
    assert "non-normative" in text, (
        "docs/generation-event-protocol.md must state that slot array order is "
        "non-normative (expected/delivered/missing are compared as multisets)"
    )
    assert "multiset" in text, (
        "docs/generation-event-protocol.md must mention multiset comparison for "
        "expected/delivered/missing slot arrays"
    )
