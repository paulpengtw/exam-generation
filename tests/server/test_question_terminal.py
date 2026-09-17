"""Slice 6 – question_terminal event tests (real QuestionTerminalPayload).

Tests ensure _worker_one emits a validated question_terminal at every exit:
- normal, passed verification → termination_reason='normal', delivery_status='complete',
  review={'status':'passed',…}
- normal, failed verification → review={'status':'failed',…}
- skip_verify → review={'status':'skipped',…}
- do_generate raising → termination_reason='failed', delivery_status='none', has_final=False
- GenerationCancelled → termination_reason='cancelled', delivery_status='unknown'
- image spec present + file written → image slot in delivered, delivery_status='complete'
- image spec present, no file → missing slot, delivery_status='partial'
- terminal payload validates as QuestionTerminalPayload
- terminal published AFTER result event (normal path)
- exactly one terminal per question
- context matches manifest (question_id, index, run_id)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from src.common.generation_core import GenerationCancelled

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_ctx(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue,
    *,
    skip_verify: bool = True,
    output_dir: Path | None = None,
) -> Any:
    """Build a minimal _RunContext suitable for _worker_one unit tests."""
    from server.config import ServerConfig
    from server.generate.service import _build_run_context
    from server.generate.subjects import SUBJECTS
    from tests.server.generate_test_utils import resolved_generate_params

    params = resolved_generate_params(
        {
            "subject": "math",
            "seed": 41,
            "grade": 8,
            "context": ["個人"],
            "set_type": "單一題",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "math_thinking": ["形成"],
            "learning_content": ["A-7-7"],
            "learning_performance": ["s-IV-12"],
            "core_competency": ["數-J-A2"],
            "content_type": "純文字",
            "count": 1,
            "skip_verify": skip_verify,
        }
    )
    spec = SUBJECTS["math"]
    cfg_kwargs: dict[str, Any] = {"api_key": "x", "gemini_api_key": "x"}
    if output_dir is not None:
        cfg_kwargs["output_dir"] = output_dir
    config = ServerConfig(**cfg_kwargs)
    app_state = MagicMock()
    return _build_run_context(
        params,
        config,
        app_state=app_state,
        spec=spec,
        session_factory=None,
        generation_log_id=None,
        loop=loop,
        queue=queue,
        html_renderer=None,
    )


def _build_fake_question(ctx: Any) -> Any:
    """Build a MagicMock question compatible with the math ExamQuestion spec."""
    import json

    q = MagicMock(spec=ctx.spec.exam_question_cls)
    q.__class__ = ctx.spec.exam_question_cls
    q.model_dump_json.return_value = json.dumps({
        "id": ctx.manifest[0].question_id,
        "題目": ["test question?"],
    })
    q.圖片 = None
    q.subquestions = []
    q.chart_spec = None
    q.verification = None
    return q


def _drain_queue(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> list[dict]:
    async def _collect() -> list[dict]:
        items = []
        while not queue.empty():
            items.append(await queue.get())
        return items

    return loop.run_until_complete(_collect())


def _event_name(e: dict) -> str | None:
    return e.get("event")


def _get_terminal(events: list[dict]) -> dict | None:
    for e in events:
        if _event_name(e) == "question_terminal":
            return e
    return None


# ---------------------------------------------------------------------------
# Terminal payload validation helper
# ---------------------------------------------------------------------------


def _assert_terminal_validates(terminal: dict) -> None:
    from server.generate.event_protocol import QuestionTerminalPayload

    payload = terminal.get("payload", {})
    QuestionTerminalPayload.model_validate(payload)  # raises on invalid


# ---------------------------------------------------------------------------
# Normal path: passed verification
# ---------------------------------------------------------------------------


def test_terminal_normal_passed_after_result() -> None:
    """Normal path: terminal with termination_reason=normal after result."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)
    q = _build_fake_question(ctx)

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    event_names = [_event_name(e) for e in events]
    assert "question_terminal" in event_names, f"missing question_terminal; got {event_names}"

    # Terminal must come AFTER result
    result_idx = next(i for i, e in enumerate(events) if _event_name(e) == "result")
    terminal_idx = next(i for i, e in enumerate(events) if _event_name(e) == "question_terminal")
    assert terminal_idx > result_idx, (
        f"terminal (idx={terminal_idx}) must be after result (idx={result_idx})"
    )


def test_terminal_skip_verify_review_skipped() -> None:
    """skip_verify=True → review.status='skipped'."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue, skip_verify=True)
    q = _build_fake_question(ctx)

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)
    payload = terminal["payload"]
    assert payload["termination_reason"] == "normal"
    assert payload["has_final"] is True
    assert payload["delivery_status"] in ("complete", "partial")
    review = payload["review"]
    assert review["status"] == "skipped", f"expected skipped, got {review['status']!r}"
    assert "passed" not in str(review.get("status", "")), (
        "skip_verify must never produce passed review"
    )


def test_terminal_normal_exactly_once() -> None:
    """Exactly one question_terminal per question."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)
    q = _build_fake_question(ctx)

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminals = [e for e in events if _event_name(e) == "question_terminal"]
    assert len(terminals) == 1, f"expected exactly 1 terminal, got {len(terminals)}"


def test_terminal_context_matches_manifest() -> None:
    """Terminal context must carry question_id and index from manifest."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)
    q = _build_fake_question(ctx)

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    t_ctx = terminal.get("context", {})
    assert t_ctx.get("question_id") == ctx.manifest[0].question_id
    assert t_ctx.get("index") == 0
    assert t_ctx.get("run_id") == ctx.run_id


def test_terminal_has_final_revision_after_normal() -> None:
    """Normal path: has_final=True and final_revision >= 1."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)
    q = _build_fake_question(ctx)

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)
    payload = terminal["payload"]
    assert payload["has_final"] is True
    assert payload["final_revision"] is not None
    assert payload["final_revision"] >= 1


def test_terminal_payload_validates_on_normal() -> None:
    """Terminal payload must pass QuestionTerminalPayload.model_validate."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)
    q = _build_fake_question(ctx)

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)  # raises ValidationError if invalid


# ---------------------------------------------------------------------------
# Exception path
# ---------------------------------------------------------------------------


def test_terminal_failed_on_exception() -> None:
    """do_generate raising → termination_reason='failed', has_final=False, delivery='none'."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)

    with (
        patch.object(ctx.spec, "do_generate", side_effect=RuntimeError("boom")),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)
    payload = terminal["payload"]
    assert payload["termination_reason"] == "failed"
    assert payload["has_final"] is False
    assert payload["final_revision"] is None
    assert payload["delivery_status"] in ("none", "unknown")
    review = payload["review"]
    assert review["status"] == "unknown"
    assert "no final content" in review.get("reason", "")


def test_terminal_failed_exactly_once() -> None:
    """Exactly one terminal on error path."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)

    with (
        patch.object(ctx.spec, "do_generate", side_effect=RuntimeError("boom")),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminals = [e for e in events if _event_name(e) == "question_terminal"]
    assert len(terminals) == 1


# ---------------------------------------------------------------------------
# Cancelled path
# ---------------------------------------------------------------------------


def test_terminal_cancelled_on_generation_cancelled() -> None:
    """GenerationCancelled with cancel_event set → termination_reason='cancelled'."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)
    ctx.cancel_event.set()

    with (
        patch.object(ctx.spec, "do_generate", side_effect=GenerationCancelled()),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)
    payload = terminal["payload"]
    assert payload["termination_reason"] == "cancelled"
    assert payload["has_final"] is False
    assert payload["delivery_status"] == "unknown"
    assert payload.get("unknown_reason") is not None


# ---------------------------------------------------------------------------
# Image slot: delivered vs missing
# ---------------------------------------------------------------------------


def test_terminal_image_slot_delivered(tmp_path: Path) -> None:
    """Image file exists → image slot in delivered, delivery_status='complete'."""
    import json

    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue, output_dir=tmp_path)
    qid = ctx.manifest[0].question_id
    img_filename = f"{qid}.png"
    (tmp_path / img_filename).write_bytes(b"PNG_DATA")

    q = MagicMock(spec=ctx.spec.exam_question_cls)
    q.__class__ = ctx.spec.exam_question_cls
    q.model_dump_json.return_value = json.dumps({
        "id": qid, "題目": ["q with image"], "圖片": img_filename,
    })
    q.圖片 = img_filename
    q.subquestions = []
    q.chart_spec = MagicMock()  # non-None → pipeline adopted an image
    q.verification = None

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)
    payload = terminal["payload"]
    assert payload["delivery_status"] == "complete", f"expected complete: {payload}"
    assert len(payload["expected"]) == 1
    assert payload["expected"][0]["kind"] == "image"
    assert len(payload["delivered"]) == 1
    assert payload["missing"] == []


def test_terminal_image_slot_missing(tmp_path: Path) -> None:
    """Image spec present but no file → slot in missing, delivery_status='partial'."""
    import json

    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue, output_dir=tmp_path)
    qid = ctx.manifest[0].question_id
    img_filename = f"{qid}.png"
    # No actual file written

    q = MagicMock(spec=ctx.spec.exam_question_cls)
    q.__class__ = ctx.spec.exam_question_cls
    q.model_dump_json.return_value = json.dumps({
        "id": qid, "題目": ["q with image"], "圖片": img_filename,
    })
    q.圖片 = img_filename
    q.subquestions = []
    q.chart_spec = MagicMock()  # pipeline adopted an image
    q.verification = None

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)
    payload = terminal["payload"]
    assert payload["delivery_status"] == "partial", f"expected partial: {payload}"
    assert len(payload["expected"]) == 1
    assert payload["delivered"] == []
    assert len(payload["missing"]) == 1


# ---------------------------------------------------------------------------
# Verification status reflected in review
# ---------------------------------------------------------------------------


def test_terminal_verification_failed_review() -> None:
    """Verification.passed=False → review.status='failed'."""
    import json

    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue, skip_verify=False)
    qid = ctx.manifest[0].question_id

    q = MagicMock(spec=ctx.spec.exam_question_cls)
    q.__class__ = ctx.spec.exam_question_cls
    q.model_dump_json.return_value = json.dumps({"id": qid, "題目": ["q"]})
    q.圖片 = None
    q.subquestions = []
    q.chart_spec = None
    # Set verification.passed = False
    q.verification = MagicMock()
    q.verification.passed = False

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)
    payload = terminal["payload"]
    review = payload["review"]
    assert review["status"] == "failed", f"expected failed, got {review['status']!r}"


def test_terminal_verification_passed_review() -> None:
    """Verification.passed=True → review.status='passed'."""
    import json

    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue, skip_verify=False)
    qid = ctx.manifest[0].question_id

    q = MagicMock(spec=ctx.spec.exam_question_cls)
    q.__class__ = ctx.spec.exam_question_cls
    q.model_dump_json.return_value = json.dumps({"id": qid, "題目": ["q"]})
    q.圖片 = None
    q.subquestions = []
    q.chart_spec = None
    q.verification = MagicMock()
    q.verification.passed = True

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)
    payload = terminal["payload"]
    review = payload["review"]
    assert review["status"] == "passed", f"expected passed, got {review['status']!r}"
