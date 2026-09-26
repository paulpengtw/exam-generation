"""Stream-level change-image (改圖不改字) revision binding for social and NS (#746 GAP 1).

Drives the real ``generate_question_stream`` path for social-studies and
natural-sciences 題組 where the image bytes of the question change without any
text change.  Two assertions per subject:

  1. ``question_update`` / ``result`` ``context.content_revision`` increments
     when image bytes change even though the text fields are unchanged.

  2. A verification verdict recorded against the older revision is NOT reused as
     the terminal review.  The terminal ``review.status`` must be either
     ``"unknown"`` (stale trail entry) when skip_verify is False, or ``"skipped"``
     when skip_verify is True.
"""
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


class _FakeClient:
    """Minimal LLM-client double that tracks its observer without network I/O."""

    def __init__(self, _config: Any) -> None:
        self._observer = None

    def set_observer(self, observer: Any) -> None:
        self._observer = observer

    def clear_observer(self) -> None:
        self._observer = None

    def emit(self, event: dict[str, Any]) -> None:
        if self._observer is not None:
            self._observer(event)


def _make_ss_question(qid: str, rng_params: Any) -> Any:
    from src.social_studies.schemas import ExamQuestion

    return ExamQuestion(
        id=qid,
        核心問題="核心問題",
        文本="文本內容（不改字）",
        取材來源=["測試來源"],
        情境=list(rng_params.情境),
        題型種類=rng_params.題型種類,
        題型=rng_params.題型[0] if rng_params.題型 else "選擇題",
        題目內容類型=rng_params.題目內容類型,
    )


def _make_ns_question(qid: str, rng_params: Any) -> Any:
    from src.natural_sciences.schemas import ExamQuestion

    return ExamQuestion(
        id=qid,
        核心問題="核心問題",
        文本="文本內容（不改字）",
        取材來源=["測試來源"],
        情境=list(rng_params.情境),
        情境子類別=rng_params.情境子類別,
        題型種類=rng_params.題型種類,
        題型=rng_params.題型,
        科學能力=list(rng_params.科學能力),
        題目內容類型=rng_params.題目內容類型,
    )


def _run_change_image_stream(
    subject: str,
    skip_verify: bool,
    tmp_path: Path,
) -> tuple[list[dict[str, Any]], str]:
    """Run generate_question_stream with a fake do_generate that changes image bytes.

    The fake produces two ``on_question_update`` calls for the same question: the
    first writes image bytes v1, the second writes v2.  The text fields are
    identical across both calls.  This exercises the snapshot-ledger image-hash
    path for the given subject.

    When skip_verify is False, the fake also emits a synthetic verification trail
    entry bound to revision=1 (the stale revision) so that the terminal-payload
    builder finds a mismatched trail entry and must produce review.status="unknown".
    """
    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from tests.server.generate_test_utils import resolved_generate_params

    params = resolved_generate_params({
        "subject": subject,
        "seed": 746,
        "count": 1,
        "sub_question_count": 3,
        "skip_verify": skip_verify,
    })

    def fake_do_generate(rng_params: Any, _overrides: Any, **kwargs: Any) -> Any:
        qid: str = kwargs["question_id"]
        on_update = kwargs["on_question_update"]
        on_trail = kwargs.get("on_trail_entry")  # None when skip_verify=True
        config = kwargs["config"]

        if subject == "social_studies":
            shell = _make_ss_question(qid, rng_params)
            from src.social_studies.schemas import VerificationResult
        else:
            shell = _make_ns_question(qid, rng_params)
            from src.natural_sciences.schemas import VerificationResult

        img_name = f"{qid}.png"
        output_dir: Path = config.output_dir

        # Write image bytes v1 and register the image on the question.
        (output_dir / img_name).write_bytes(b"image-version-1-\x00\x01\x02")
        shell.圖片 = img_name

        # First update: content is text + image-v1 → revision=1
        rev1: int = on_update(shell, "draft")

        if on_trail is not None:
            # Emit a synthetic verification trail entry pinned to revision=1.
            # This simulates a verifier that ran BEFORE the image changed and
            # must NOT be reused as the terminal review once the revision moves.
            vr = VerificationResult(
                passed=True,
                answer_match=True,
                details="初次驗證通過（此後圖片將被替換）",
                my_answer="A",
                provided_answer="A",
            )
            shell.verification = vr
            from src.common.verification_trail import make_verification_trail_entry
            stale_entry = make_verification_trail_entry(
                qid, vr, "verify-model", content_revision=rev1
            )
            on_trail(stale_entry)

        # Change image bytes WITHOUT changing any text field (改圖不改字).
        (output_dir / img_name).write_bytes(b"image-version-2-\xff\xfe\xfd")

        # Second update: text unchanged but image hash differs → revision must increment.
        on_update(shell, "draft")

        return shell

    spec = dataclasses.replace(SUBJECTS[subject], do_generate=fake_do_generate)
    config = ServerConfig(
        api_key="x",
        gemini_api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    app_state = type(
        "_AppState",
        (),
        {
            "renderer_pool": None,
            "ss_curriculum_context": None,
            "ns_curriculum_context": None,
            "math_curriculum_context": None,
        },
    )()

    async def collect() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in generate_question_stream(
            params,
            config,
            app_state,
            subjects={subject: spec},
            client_factory=_FakeClient,
        ):
            events.append(event)
        return events

    with patch("server.observability.record_generation_outcome"):
        events = asyncio.run(collect())

    return events, events[0]["context"]["run_id"]


@pytest.mark.parametrize(
    "subject,skip_verify",
    [
        ("social_studies", False),
        ("social_studies", True),
        ("natural_sciences", False),
        ("natural_sciences", True),
    ],
)
def test_change_image_increments_revision_stale_verdict_not_reused(
    subject: str,
    skip_verify: bool,
    tmp_path: Path,
) -> None:
    """改圖不改字：image-byte change increments content_revision; stale verdict not reused."""
    events, _run_id = _run_change_image_stream(subject, skip_verify, tmp_path)

    # ── event-stream sanity ────────────────────────────────────────────────────
    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "done"

    updates = [e for e in events if e["event"] == "question_update"]
    results = [e for e in events if e["event"] == "result"]
    terminals = [e for e in events if e["event"] == "question_terminal"]

    assert updates, "expected at least one question_update event"
    assert results, "expected a result event"
    assert terminals, "expected a question_terminal event"

    # ── revision increments when only image bytes change (改圖不改字) ────────────
    update_revisions = [u["context"]["content_revision"] for u in updates]
    assert update_revisions == [1, 2], (
        f"expected content_revision to be [1, 2] (image change bumps revision), "
        f"got {update_revisions}"
    )

    result_revision = results[0]["context"]["content_revision"]
    assert result_revision == 2, (
        f"result content_revision should equal the final revision (2), got {result_revision}"
    )

    # ── terminal review reflects stale-verdict rejection ───────────────────────
    terminal_review = terminals[0]["payload"]["review"]

    if skip_verify:
        # skip_verify=True: review is always "skipped" regardless of trail
        assert terminal_review["status"] == "skipped", (
            f"expected review.status='skipped' when skip_verify=True, "
            f"got {terminal_review}"
        )
        assert terminal_review.get("content_revision") == 2, (
            f"expected review.content_revision=2, got {terminal_review}"
        )
    else:
        # skip_verify=False: the trail entry was recorded at revision=1 but
        # the final revision is 2 → stale verdict MUST NOT be reused.
        assert terminal_review["status"] == "unknown", (
            f"expected review.status='unknown' (stale trail at rev=1 ≠ final rev=2), "
            f"got {terminal_review}"
        )
        assert "reason" in terminal_review, (
            f"expected a 'reason' field in the unknown review, got {terminal_review}"
        )
