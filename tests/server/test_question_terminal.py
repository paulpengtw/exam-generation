"""Slice 6 – question_terminal event tests (real QuestionTerminalPayload).

Tests ensure _worker_one emits a validated question_terminal at every exit:
- normal, passed verification → termination_reason='normal', delivery_status='complete',
  review={'status':'passed',…}
- normal, failed verification → review={'status':'failed',…}
- skip_verify → review={'status':'skipped',…}
- do_generate raising → termination_reason='failed', delivery_status='none', has_final=False
- confirmed cancellation → termination_reason='cancelled', delivery_status='unknown'
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
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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


def test_terminal_failure_after_final_keeps_the_delivered_final() -> None:
    """A late terminal failure does not rewrite an already-delivered final as no-final."""
    import server.generate.service as service_mod
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)
    q = _build_fake_question(ctx)
    real_publish_terminal = service_mod._publish_question_terminal
    attempts = 0

    def fail_first_terminal(*args: Any, **kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("terminal enqueue failed")
        real_publish_terminal(*args, **kwargs)

    with (
        patch.object(ctx.spec, "do_generate", return_value=q),
        patch.object(ctx.spec, "extract_prior_scope", return_value=None),
        patch.object(service_mod, "_publish_question_terminal", side_effect=fail_first_terminal),
        patch.object(observability_mod, "record_generation_outcome"),
    ):
        _worker_one(0, MagicMock(), ctx, [])

    events = _drain_queue(loop, queue)
    loop.close()

    result = next(event for event in events if _event_name(event) == "result")
    terminal = _get_terminal(events)
    assert terminal is not None
    _assert_terminal_validates(terminal)
    assert terminal["context"]["event_seq"] > result["context"]["event_seq"]
    assert terminal["payload"]["termination_reason"] == "failed"
    assert terminal["payload"]["has_final"] is True
    assert terminal["payload"]["final_revision"] == result["context"]["content_revision"]
    assert terminal["payload"]["delivery_status"] == "complete"
    assert len([event for event in events if _event_name(event) == "question_terminal"]) == 1


# ---------------------------------------------------------------------------
# Cancelled path
# ---------------------------------------------------------------------------


def test_disconnect_generation_cancelled_does_not_emit_a_terminal() -> None:
    """A client cancellation signal is not proof of confirmed cancellation."""
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

    assert _get_terminal(events) is None


def test_confirmed_generation_cancelled_emits_one_terminal() -> None:
    """Only the explicit internal confirmation may establish cancellation."""
    import server.observability as observability_mod
    from server.generate.service import _worker_one

    loop = asyncio.new_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    ctx = _build_ctx(loop, queue)
    ctx.confirmed_cancel_event.set()

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
    assert terminal["payload"]["termination_reason"] == "cancelled"
    assert terminal["payload"]["delivery_status"] == "unknown"


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


def test_terminal_social_group_keeps_fixed_missing_subquestion_slot() -> None:
    """A grouped final preserves slot 2 as missing between delivered 1 and 3."""
    from types import SimpleNamespace

    from server.generate.service import _build_question_terminal_payload

    question_id = "social-group-fixed"
    question = SimpleNamespace(
        chart_spec=None,
        image_spec=None,
        圖片=None,
        verification=None,
        subquestions=[
            SimpleNamespace(
                id=f"{question_id}-sq001",
                序號=1,
                _plan_index=1,
                chart_spec=None,
                圖片=None,
            ),
            SimpleNamespace(
                id=f"{question_id}-sq003",
                序號=3,
                _plan_index=3,
                chart_spec=None,
                圖片=None,
            ),
        ],
    )
    params = SimpleNamespace(
        subject="social_studies",
        skip_verify=True,
        sub_question_count=3,
        subquestion_configs=[SimpleNamespace(content_type=None) for _ in range(3)],
    )

    payload = _build_question_terminal_payload(
        question_id=question_id,
        termination_reason="normal",
        has_final=True,
        final_revision=3,
        question=question,
        params=params,
        output_dir=None,
        announced_slots=[
            {"subquestion_index": 0, "id": f"{question_id}-sq001", "序號": 1},
            {"subquestion_index": 1, "id": f"{question_id}-sq002", "序號": 2},
            {"subquestion_index": 2, "id": f"{question_id}-sq003", "序號": 3},
        ],
    )

    assert payload["delivery_status"] == "partial"
    assert [slot["kind"] for slot in payload["expected"]] == [
        "subquestion",
        "subquestion",
        "subquestion",
    ]
    assert [slot["subquestion_id"] for slot in payload["delivered"]] == [
        f"{question_id}-sq001",
        f"{question_id}-sq003",
    ]
    assert [slot["subquestion_id"] for slot in payload["missing"]] == [
        f"{question_id}-sq002",
    ]


def test_terminal_social_group_uses_announced_manifest_over_resolved_count() -> None:
    """A plan manifest, rather than the resolved count, defines fixed slots."""
    from types import SimpleNamespace

    from server.generate.service import _build_question_terminal_payload

    question_id = "social-group-announced"
    question = SimpleNamespace(
        chart_spec=None,
        image_spec=None,
        圖片=None,
        verification=None,
        subquestions=[
            SimpleNamespace(
                id=f"{question_id}-sq001",
                序號=1,
                _plan_index=1,
                chart_spec=None,
                圖片=None,
            ),
            SimpleNamespace(
                id=f"{question_id}-sq003",
                序號=3,
                _plan_index=3,
                chart_spec=None,
                圖片=None,
            ),
        ],
    )
    params = SimpleNamespace(
        subject="social_studies",
        skip_verify=True,
        sub_question_count=3,
        subquestion_configs=[SimpleNamespace(content_type=None) for _ in range(3)],
    )
    announced_slots = [
        {"subquestion_index": 0, "id": f"{question_id}-sq001", "序號": 1},
        {"subquestion_index": 2, "id": f"{question_id}-sq003", "序號": 3},
    ]

    payload = _build_question_terminal_payload(
        question_id=question_id,
        termination_reason="normal",
        has_final=True,
        final_revision=3,
        question=question,
        params=params,
        output_dir=None,
        announced_slots=announced_slots,
        resolved_subquestion_count=3,
    )

    assert [slot["subquestion_id"] for slot in payload["expected"]] == [
        f"{question_id}-sq001",
        f"{question_id}-sq003",
    ]
    assert [slot["subquestion_index"] for slot in payload["expected"]] == [0, 2]
    assert payload["missing"] == []


def test_terminal_failed_before_plan_falls_back_to_resolved_count() -> None:
    """A draftless failed group still attributes its resolved fixed slots."""
    from types import SimpleNamespace

    from server.generate.service import _build_question_terminal_payload

    question_id = "social-group-no-plan"
    params = SimpleNamespace(
        subject="social_studies",
        skip_verify=True,
        sub_question_count=2,
        subquestion_configs=[SimpleNamespace(content_type=None) for _ in range(2)],
    )

    payload = _build_question_terminal_payload(
        question_id=question_id,
        termination_reason="failed",
        has_final=False,
        final_revision=None,
        question=None,
        params=params,
        output_dir=None,
        announced_slots=None,
        resolved_subquestion_count=2,
    )

    assert payload["delivery_status"] == "none"
    assert [slot["subquestion_id"] for slot in payload["expected"]] == [
        f"{question_id}-sq001",
        f"{question_id}-sq002",
    ]
    assert [slot["subquestion_id"] for slot in payload["missing"]] == [
        f"{question_id}-sq001",
        f"{question_id}-sq002",
    ]


def test_terminal_failed_flat_math_does_not_inherit_batch_group_slots() -> None:
    """A flat per-question resolution must suppress the batch group count."""
    from types import SimpleNamespace

    from server.generate.service import _build_question_terminal_payload

    payload = _build_question_terminal_payload(
        question_id="math-flat-batch-grouped",
        termination_reason="failed",
        has_final=False,
        final_revision=None,
        question=None,
        params=SimpleNamespace(
            subject="math",
            skip_verify=True,
            sub_question_count=5,
            subquestion_configs=None,
        ),
        output_dir=None,
        announced_slots=None,
        resolved_subquestion_configs=None,
        resolved_subquestion_count=None,
    )

    assert payload["expected"] == []
    assert payload["missing"] == []


def test_terminal_failed_grouped_math_uses_its_resolved_count() -> None:
    """A grouped math row gets missing slots before its plan is announced."""
    from types import SimpleNamespace

    from server.generate.service import _build_question_terminal_payload

    payload = _build_question_terminal_payload(
        question_id="math-grouped-no-plan",
        termination_reason="failed",
        has_final=False,
        final_revision=None,
        question=None,
        params=SimpleNamespace(
            subject="math",
            skip_verify=True,
            sub_question_count=None,
            subquestion_configs=None,
        ),
        output_dir=None,
        announced_slots=None,
        resolved_subquestion_configs=None,
        resolved_subquestion_count=3,
    )

    assert [slot["subquestion_id"] for slot in payload["missing"]] == [
        "math-grouped-no-plan-sq001",
        "math-grouped-no-plan-sq002",
        "math-grouped-no-plan-sq003",
    ]


def test_terminal_social_group_tracks_adopted_image_by_fixed_slot() -> None:
    from types import SimpleNamespace

    from server.generate.service import _build_question_terminal_payload

    question_id = "social-group-image"
    question = SimpleNamespace(
        chart_spec=None,
        image_spec=None,
        圖片=None,
        verification=None,
        subquestions=[
            SimpleNamespace(
                id=f"{question_id}-sq001",
                序號=1,
                _plan_index=1,
                chart_spec=object(),
                圖片="social-group-image_sq1.png",
            ),
            SimpleNamespace(
                id=f"{question_id}-sq002",
                序號=2,
                _plan_index=2,
                chart_spec=None,
                圖片=None,
            ),
            SimpleNamespace(
                id=f"{question_id}-sq003",
                序號=3,
                _plan_index=3,
                chart_spec=None,
                圖片=None,
            ),
        ],
    )
    params = SimpleNamespace(
        subject="social_studies",
        skip_verify=True,
        sub_question_count=3,
        subquestion_configs=[
            SimpleNamespace(content_type="純文字", image_generation_mode="gpt_image"),
            SimpleNamespace(content_type="純文字", image_generation_mode="html"),
            SimpleNamespace(content_type="純文字", image_generation_mode="html"),
        ],
    )

    payload = _build_question_terminal_payload(
        question_id=question_id,
        termination_reason="normal",
        has_final=True,
        final_revision=4,
        question=question,
        params=params,
        output_dir=None,
        announced_slots=[
            {"subquestion_index": 0, "id": f"{question_id}-sq001", "序號": 1},
            {"subquestion_index": 1, "id": f"{question_id}-sq002", "序號": 2},
            {"subquestion_index": 2, "id": f"{question_id}-sq003", "序號": 3},
        ],
    )

    assert payload["delivery_status"] == "partial"
    assert payload["missing"] == [{
        "kind": "image",
        "question_id": question_id,
        "subquestion_id": f"{question_id}-sq001",
        "subquestion_index": 0,
        "reason": "image not delivered",
    }]


@pytest.mark.parametrize("subject", ["natural_sciences", "math"])
def test_terminal_fixed_group_preserves_missing_middle_slot_for_each_adapter(
    subject: str,
) -> None:
    """The shared terminal builder uses the announced manifest for both adapters."""
    from types import SimpleNamespace

    from server.generate.service import _build_question_terminal_payload

    question_id = f"{subject}-group-fixed"
    question = SimpleNamespace(
        chart_spec=None,
        image_spec=None,
        圖片=None,
        verification=None,
        subquestions=[
            SimpleNamespace(id=f"{question_id}-sq001", 序號=1, _plan_index=1),
            SimpleNamespace(id=f"{question_id}-sq003", 序號=3, _plan_index=3),
        ],
    )
    params = SimpleNamespace(
        subject=subject,
        skip_verify=True,
        sub_question_count=3,
        subquestion_configs=[SimpleNamespace(content_type=None) for _ in range(3)],
    )
    announced_slots = [
        {
            "subquestion_index": index,
            "id": f"{question_id}-sq{index + 1:03d}",
            "序號": index + 1,
        }
        for index in range(3)
    ]

    payload = _build_question_terminal_payload(
        question_id=question_id,
        termination_reason="normal",
        has_final=True,
        final_revision=3,
        question=question,
        params=params,
        output_dir=None,
        announced_slots=announced_slots,
    )

    assert payload["delivery_status"] == "partial"
    assert [slot["subquestion_id"] for slot in payload["delivered"]] == [
        f"{question_id}-sq001",
        f"{question_id}-sq003",
    ]
    assert [slot["subquestion_id"] for slot in payload["missing"]] == [
        f"{question_id}-sq002",
    ]


@pytest.mark.parametrize("subject", ["natural_sciences", "math"])
def test_terminal_fixed_group_all_subquestions_failed_keeps_text_final(subject: str) -> None:
    """A surviving text shell is final content even when every fixed slot is absent."""
    from types import SimpleNamespace

    from server.generate.service import _build_question_terminal_payload

    question_id = f"{subject}-group-text-only"
    params = SimpleNamespace(
        subject=subject,
        skip_verify=True,
        sub_question_count=3,
        subquestion_configs=[],
    )
    announced_slots = [
        {
            "subquestion_index": index,
            "id": f"{question_id}-sq{index + 1:03d}",
            "序號": index + 1,
        }
        for index in range(3)
    ]

    payload = _build_question_terminal_payload(
        question_id=question_id,
        termination_reason="normal",
        has_final=True,
        final_revision=1,
        question=SimpleNamespace(
            chart_spec=None,
            image_spec=None,
            圖片=None,
            verification=None,
            subquestions=[],
        ),
        params=params,
        output_dir=None,
        announced_slots=announced_slots,
    )

    assert payload["has_final"] is True
    assert payload["delivery_status"] == "partial"
    assert len(payload["missing"]) == 3


def test_terminal_natural_sciences_tracks_fixed_subquestion_image_slot(tmp_path: Path) -> None:
    """NS image obligations use the same fixed slot identity as delivery."""
    from types import SimpleNamespace

    from server.generate.service import _build_question_terminal_payload

    question_id = "natural-sciences-group-image"
    question = SimpleNamespace(
        chart_spec=None,
        image_spec=None,
        圖片=None,
        verification=None,
        subquestions=[
            SimpleNamespace(
                id=f"{question_id}-sq001",
                序號=1,
                _plan_index=1,
                chart_spec=object(),
                image_spec=None,
                圖片=f"{question_id}_sq1.png",
            ),
            SimpleNamespace(
                id=f"{question_id}-sq002",
                序號=2,
                _plan_index=2,
                chart_spec=None,
                image_spec=None,
                圖片=None,
            ),
            SimpleNamespace(
                id=f"{question_id}-sq003",
                序號=3,
                _plan_index=3,
                chart_spec=None,
                image_spec=None,
                圖片=None,
            ),
        ],
    )
    params = SimpleNamespace(
        subject="natural_sciences",
        skip_verify=True,
        sub_question_count=3,
        subquestion_configs=[
            SimpleNamespace(content_type="純文字"),
            SimpleNamespace(content_type="純文字"),
            SimpleNamespace(content_type="純文字"),
        ],
    )

    payload = _build_question_terminal_payload(
        question_id=question_id,
        termination_reason="normal",
        has_final=True,
        final_revision=4,
        question=question,
        params=params,
        output_dir=tmp_path,
        announced_slots=[
            {
                "subquestion_index": index,
                "id": f"{question_id}-sq{index + 1:03d}",
                "序號": index + 1,
            }
            for index in range(3)
        ],
    )

    assert payload["delivery_status"] == "partial"
    assert payload["missing"] == [{
        "kind": "image",
        "question_id": question_id,
        "subquestion_id": f"{question_id}-sq001",
        "subquestion_index": 0,
        "reason": "image not delivered",
    }]


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

    def generate_with_trail(*_args: Any, **kwargs: Any) -> Any:
        kwargs["on_trail_entry"]({"kind": "verification", "content_revision": 1})
        return q

    with (
        patch.object(ctx.spec, "do_generate", side_effect=generate_with_trail),
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

    def generate_with_trail(*_args: Any, **kwargs: Any) -> Any:
        kwargs["on_trail_entry"]({"kind": "verification", "content_revision": 1})
        return q

    with (
        patch.object(ctx.spec, "do_generate", side_effect=generate_with_trail),
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


@pytest.mark.parametrize(
    ("skip_verify", "passed", "trail_revision", "question_revision", "expected_status"),
    [
        (True, False, None, 4, "skipped"),
        (False, True, 4, 99, "passed"),
        (False, False, 4, 99, "failed"),
        (False, True, None, 4, "unknown"),
        (False, True, 3, 4, "unknown"),
    ],
)
def test_terminal_review_uses_latest_verification_trail_revision(
    skip_verify: bool,
    passed: bool,
    trail_revision: int | None,
    question_revision: int,
    expected_status: str,
) -> None:
    from server.generate.service import _build_question_terminal_payload

    question = SimpleNamespace(
        verification=SimpleNamespace(passed=passed, content_revision=question_revision),
        圖片=None,
        chart_spec=None,
        subquestions=[],
    )
    params = SimpleNamespace(
        subject="math",
        skip_verify=skip_verify,
        sub_question_count=None,
        subquestion_configs=None,
    )
    verification_trail = (
        []
        if trail_revision is None
        else [{"kind": "verification", "content_revision": trail_revision}]
    )

    payload = _build_question_terminal_payload(
        question_id="q-trail-review",
        termination_reason="normal",
        has_final=True,
        final_revision=4,
        question=question,
        params=params,
        output_dir=None,
        verification_trail=verification_trail,
    )

    assert payload["review"]["status"] == expected_status
    if expected_status in {"passed", "failed", "skipped"}:
        assert payload["review"]["content_revision"] == 4
    else:
        assert payload["review"]["reason"] in {
            "no verification evidence",
            "no matching verification evidence",
        }


def test_terminal_does_not_reuse_verdict_from_an_older_content_revision() -> None:
    from server.generate.service import _build_question_terminal_payload

    question = SimpleNamespace(
        verification=SimpleNamespace(passed=True, content_revision=2),
        圖片=None,
        chart_spec=None,
        subquestions=[],
    )
    params = SimpleNamespace(
        subject="math",
        skip_verify=False,
        sub_question_count=None,
        subquestion_configs=None,
    )

    payload = _build_question_terminal_payload(
        question_id="q-stale-review",
        termination_reason="normal",
        has_final=True,
        final_revision=2,
        question=question,
        params=params,
        output_dir=None,
        verification_trail=[{"kind": "verification", "content_revision": 1}],
    )

    assert payload["review"] == {
        "status": "unknown",
        "reason": "no matching verification evidence",
    }
