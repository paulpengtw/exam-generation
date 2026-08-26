"""Persistence contract tests for the first-class verification trail."""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.persistence import (
    persist_aborted_generation_record,
    persist_failed_generation_record,
    persist_generation_record,
)
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from src.common.verification_trail import (
    VerificationTrailCorrectionEntry,
    VerificationTrailEntry,
    VerificationTrailInitialEntry,
)
from src.social_studies.schemas import ExamQuestion
from tests.server.generate_test_utils import resolved_generate_params


def _make_factory(rows: list[Any]) -> Any:
    @asynccontextmanager
    async def factory():
        class FakeSession:
            def add(self, row: Any) -> None:
                rows.append(row)

            async def commit(self) -> None:
                pass

        yield FakeSession()

    return factory


def test_completed_generation_persists_the_expected_verification_trail() -> None:
    rows: list[Any] = []
    expected_trail = [
        {
            "code": "verification_trail",
            "kind": "verification",
            "question_id": "q1",
            "passed": True,
            "details": "The answer is consistent.",
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "chart_verification": None,
            "model": "verify-model",
            "timestamp": "2026-08-24T00:00:00Z",
        }
    ]

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="math",
            params=GenerateParams(subject="math"),
            payload={"id": "q1"},
            verification_trail_json=expected_trail,
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].verification_trail_json == expected_trail


def test_skip_verify_persists_a_null_verification_trail() -> None:
    rows: list[Any] = []

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="math",
            params=GenerateParams(subject="math", skip_verify=True),
            payload={"id": "q-skip"},
            verification_trail_json=None,
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].verification_trail_json is None


def test_failed_generation_persists_a_null_verification_trail() -> None:
    rows: list[Any] = []

    asyncio.run(
        persist_failed_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="math",
            params=GenerateParams(subject="math"),
            error="generation failed",
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].verification_trail_json is None


def test_aborted_generation_persists_a_null_verification_trail() -> None:
    rows: list[Any] = []

    asyncio.run(
        persist_aborted_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="math",
            params=GenerateParams(subject="math"),
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].verification_trail_json is None


def test_completed_stream_persists_the_trail_emitted_by_its_worker(tmp_path) -> None:
    rows: list[Any] = []
    entry = VerificationTrailEntry(
        question_id="ss-trail-question",
        passed=False,
        details="The answer needs a correction.",
        my_answer="A",
        provided_answer="B",
        answer_match=False,
        model="verify-model",
        timestamp=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )
    entries = [
        VerificationTrailInitialEntry(
            question_id="ss-trail-question",
            timestamp=datetime(2026, 8, 24, 0, 0, 1, tzinfo=timezone.utc),
            snapshot={"id": "ss-trail-question", "圖片": "question.png"},
        ),
        entry,
        VerificationTrailCorrectionEntry(
            question_id="ss-trail-question",
            retry_index=1,
            model="correct-model",
            timestamp=datetime(2026, 8, 24, 0, 0, 2, tzinfo=timezone.utc),
            snapshot={"id": "ss-trail-question", "圖片": "question.png", "答案": "fixed"},
        ),
        entry.model_copy(
            update={
                "passed": True,
                "details": "The corrected answer is consistent.",
                "provided_answer": "A",
                "answer_match": True,
                "timestamp": datetime(2026, 8, 24, 0, 0, 3, tzinfo=timezone.utc),
            }
        ),
    ]

    def fake_do_generate(rng_params, _overrides, **kwargs):
        for emitted in entries:
            kwargs["on_trail_entry"](emitted)
        return ExamQuestion(
            id="ss-trail-question",
            核心問題="核心問題",
            文本="文本",
            情境=[c.value for c in rng_params.情境],
            題型種類=rng_params.題型種類.value,
            題型=rng_params.題型[0].value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    fake_spec = dataclasses.replace(
        SUBJECTS["social_studies"],
        do_generate=fake_do_generate,
    )
    params = resolved_generate_params(
        {"subject": "social_studies", "skip_verify": False}
    )
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=tmp_path,
        creative_planning=False,
    )

    async def collect_events() -> None:
        async for _event in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            user_id=uuid.uuid4(),
            subjects={"social_studies": fake_spec},
            session_factory=_make_factory(rows),
        ):
            pass

    asyncio.run(collect_events())

    assert rows[0].verification_trail_json == [
        item.model_dump(mode="json") for item in entries
    ]


def test_skip_verify_stream_persists_a_null_trail(tmp_path) -> None:
    rows: list[Any] = []

    def fake_do_generate(rng_params, _overrides, **kwargs):
        assert kwargs["on_trail_entry"] is None
        return ExamQuestion(
            id="ss-skip-question",
            核心問題="核心問題",
            文本="文本",
            情境=[c.value for c in rng_params.情境],
            題型種類=rng_params.題型種類.value,
            題型=rng_params.題型[0].value,
            題目=["題目"],
            正確解題分析=["解析"],
        )

    fake_spec = dataclasses.replace(
        SUBJECTS["social_studies"],
        do_generate=fake_do_generate,
    )
    params = resolved_generate_params(
        {"subject": "social_studies", "skip_verify": True}
    )
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=tmp_path,
        creative_planning=False,
    )

    async def collect_events() -> None:
        async for _event in generate_question_stream(
            params,
            config,
            SimpleNamespace(html_renderer=None, renderer_pool=None),
            user_id=uuid.uuid4(),
            subjects={"social_studies": fake_spec},
            session_factory=_make_factory(rows),
        ):
            pass

    asyncio.run(collect_events())

    assert rows[0].verification_trail_json is None
