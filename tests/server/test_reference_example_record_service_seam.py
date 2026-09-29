"""Service seam tests for the 參考範例紀錄 feature (#670).

Verifies that:
- The result event does NOT carry reference_example_record as a sidecar (#904:
  sidecars dropped from the queue envelope; saved directly in the worker)
- Each entry is emitted live as a trail event via the trail emitter
- The CLI output (question JSON) does not include the record field
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from src.social_studies.schemas import ExamQuestion
from tests.server.generate_test_utils import resolved_generate_params

_NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)

_EXAMPLE_ENTRY = {
    "code": "reference_example",
    "kind": "example",
    "question_id": "ss-ref-seam",
    "stage": "text_generator",
    "slot": None,
    "description": "ICCS test example",
    "source": "data/social_studies/few_shot",
    "timestamp": _NOW.isoformat(),
}

_SUB_ENTRY = {
    "code": "reference_example",
    "kind": "example",
    "question_id": "ss-ref-seam",
    "stage": "subquestion_generator",
    "slot": 1,
    "description": "subquestion example",
    "source": "data/social_studies/few_shot",
    "timestamp": _NOW.isoformat(),
}


def _fake_question() -> ExamQuestion:
    return ExamQuestion(
        id="ss-ref-seam",
        核心問題="核心問題",
        文本="文本",
        情境=["個人"],
        題型種類="題組題",
        題型="選擇題",
        題目=["題目"],
        正確解題分析=["解析"],
    )


def _fake_spec(entries: list[dict]) -> object:
    def fake_do_generate(rng_params, _overrides, **kwargs):
        on_ref_entry = kwargs.get("on_reference_example_entry")
        if on_ref_entry is not None:
            for entry in entries:
                on_ref_entry(entry)
        return _fake_question()

    return dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)


def test_result_event_does_not_carry_reference_example_record_sidecar(
    tmp_path,
) -> None:
    """issue #904: sidecars are dropped from the queue envelope.

    The reference_example_record is saved directly in the worker before RESULT
    is published (persist_generation_record(..., max_attempts=...,
    report_exhaustion=True)); it no longer travels as
    a top-level sidecar on the result event dict.
    """
    entries = [_EXAMPLE_ENTRY, _SUB_ENTRY]
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=tmp_path)
    params = resolved_generate_params(
        {"subject": "social_studies", "count": 1, "skip_verify": True}
    )
    fake_spec = _fake_spec(entries)

    async def collect() -> list[dict]:
        evts = []
        async for ev in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": fake_spec},
        ):
            evts.append(ev)
        return evts

    events = asyncio.run(collect())
    result_events = [ev for ev in events if ev["event"] == "result"]
    assert len(result_events) == 1

    result_event = result_events[0]
    # The sidecar is no longer in the queue envelope (issue #904).
    assert "reference_example_record" not in result_event, (
        "reference_example_record sidecar must not appear in the result envelope"
        " after issue #904 (save-before-RESULT)"
    )
    # The question payload also must not include the sidecar.
    assert "reference_example_record" not in result_event.get("payload", {})


def test_reference_example_entries_emitted_as_live_trail_events(tmp_path) -> None:
    """Each reference example entry is emitted as a separate trail event."""
    entries = [_EXAMPLE_ENTRY, _SUB_ENTRY]
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=tmp_path)
    params = resolved_generate_params(
        {"subject": "social_studies", "count": 1, "skip_verify": True}
    )
    fake_spec = _fake_spec(entries)

    async def collect() -> list[dict]:
        evts = []
        async for ev in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": fake_spec},
        ):
            evts.append(ev)
        return evts

    events = asyncio.run(collect())
    trail_events = [ev for ev in events if ev["event"] == "trail"]
    ref_trail_events = [
        ev for ev in trail_events
        if isinstance(ev.get("payload"), dict)
        and ev["payload"].get("code") == "reference_example"
    ]
    assert len(ref_trail_events) == len(entries)
    emitted_payloads = [ev["payload"] for ev in ref_trail_events]
    assert emitted_payloads == entries


def test_reference_example_record_json_content_passed_to_save_seam(
    tmp_path,
) -> None:
    """issue #904 + #903: saved record receives correct reference_example_record_json.

    Monkeypatches persist_generation_record in the service module and
    asserts that the worker passes the expected reference_example_record_json with
    disabled=False and the full entries list.
    """
    entries = [_EXAMPLE_ENTRY, _SUB_ENTRY]
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=tmp_path)
    params = resolved_generate_params(
        {"subject": "social_studies", "count": 1, "skip_verify": True}
    )
    fake_spec = _fake_spec(entries)
    user_id = uuid.uuid4()

    saved_calls: list[dict] = []

    async def fake_save(**kwargs):  # type: ignore[return]
        saved_calls.append(kwargs)
        return uuid.uuid4()

    async def collect() -> list[dict]:
        evts = []
        async for ev in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": fake_spec},
            user_id=user_id,
        ):
            evts.append(ev)
        return evts

    with patch(
        "server.generate.service.persist_generation_record",
        side_effect=fake_save,
    ):
        asyncio.run(collect())

    assert len(saved_calls) == 1, (
        f"expected exactly 1 save call for 1 question, got {len(saved_calls)}"
    )
    expected_rer = {"disabled": False, "entries": entries}
    assert saved_calls[0].get("reference_example_record_json") == expected_rer, (
        "reference_example_record_json must carry disabled=False and the entries list"
    )


def test_cli_result_json_does_not_include_reference_example_record(tmp_path) -> None:
    """The question JSON in the result event data field has no reference_example_record key."""
    entries = [_EXAMPLE_ENTRY]
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=tmp_path)
    params = resolved_generate_params(
        {"subject": "social_studies", "count": 1, "skip_verify": True}
    )
    fake_spec = _fake_spec(entries)

    async def collect() -> list[dict]:
        evts = []
        async for ev in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": fake_spec},
        ):
            evts.append(ev)
        return evts

    events = asyncio.run(collect())
    result_events = [ev for ev in events if ev["event"] == "result"]
    assert len(result_events) == 1
    question_data = result_events[0]["payload"]
    # The question JSON sent to the client must not include internal trail fields.
    assert "reference_example_record" not in question_data
    assert "reference_example_entries" not in question_data
