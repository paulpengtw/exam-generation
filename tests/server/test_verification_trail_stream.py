"""SSE stream tests for live verification-trail verdict events."""

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
from src.common.verification_trail import (
    VerificationTrailCorrectionEntry,
    VerificationTrailEntry,
    VerificationTrailInitialEntry,
)
from src.social_studies.schemas import ExamQuestion
from tests.server.generate_test_utils import resolved_generate_params


@pytest.mark.parametrize(("skip_verify", "expected_trail_count"), [(False, 4), (True, 0)])
def test_generate_stream_emits_each_trail_entry_with_its_exact_payload(
    tmp_path,
    skip_verify: bool,
    expected_trail_count: int,
) -> None:
    config = ServerConfig(api_key="x", output_dir=tmp_path, data_dir=tmp_path)
    params = resolved_generate_params(
        {"subject": "social_studies", "count": 1, "skip_verify": skip_verify}
    )
    entry = VerificationTrailEntry(
        question_id="ss-trail-question",
        passed=False,
        details="需要修正。",
        my_answer="A",
        provided_answer="B",
        answer_match=False,
        model="verify-model",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    entries = [
        VerificationTrailInitialEntry(
            question_id="ss-trail-question",
            timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
            snapshot={"id": "ss-trail-question", "圖片": "question.png"},
        ),
        entry,
        VerificationTrailCorrectionEntry(
            question_id="ss-trail-question",
            retry_index=1,
            model="correct-model",
            timestamp=datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc),
            snapshot={"id": "ss-trail-question", "圖片": "question.png", "答案": "fixed"},
        ),
        entry.model_copy(
            update={
                "passed": True,
                "details": "通過。",
                "provided_answer": "A",
                "answer_match": True,
                "timestamp": datetime(2026, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
            }
        ),
    ]

    def fake_do_generate(rng_params, _overrides, **kwargs):
        if kwargs["on_trail_entry"] is not None:
            for emitted in entries:
                kwargs["on_trail_entry"](emitted)
        sampled = rng_params
        return ExamQuestion(
            id="ss-trail-question",
            核心問題="核心問題",
            文本="文本",
            情境=[c.value for c in sampled.情境],
            題型種類=sampled.題型種類.value,
            題型=sampled.題型[0].value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    fake_spec = dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)

    async def collect_events() -> list[dict]:
        events = []
        async for event in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            subjects={"social_studies": fake_spec},
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())
    trail_events = [event for event in events if event["event"] == "trail"]

    assert len(trail_events) == expected_trail_count
    if expected_trail_count:
        assert [event["data"] for event in trail_events] == [
            item.model_dump(mode="json") for item in entries
        ]
