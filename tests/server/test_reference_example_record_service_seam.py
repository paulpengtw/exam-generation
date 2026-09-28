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
from datetime import datetime, timezone
from types import SimpleNamespace

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
    is published (save_generation_record_with_retries); it no longer travels as
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
