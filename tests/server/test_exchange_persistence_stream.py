"""Exchange persistence across concurrent generation streams (issue #789)."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from sqlalchemy import text

from server.config import ServerConfig
from server.generate import persistence
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from server.models import GenerationLog, LLMExchange
from src.llm_client import LLMClient
from src.natural_sciences.schemas import ExamQuestion as NSExamQuestion
from src.social_studies.schemas import ExamQuestion as SSExamQuestion
from tests.server.generate_test_utils import resolved_generate_params
from tests.server.test_exchange_persistence_integration import ExchangeStore, exchange_store

_AGENTS = ("sub_generator#1", "sub_generator#2", "sub_generator#3")
_PRIVATE_PROMPT = "PRIVATE_PROMPT"
_PRIVATE_ANSWER = "PRIVATE_ANSWER"


class _FakeMessages:
    """Stub the provider SDK boundary used by the real ``LLMClient``."""

    def create(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            content=[SimpleNamespace(text=f'{{"answer": "{_PRIVATE_ANSWER}"}}')],
            usage=SimpleNamespace(
                input_tokens=5,
                output_tokens=3,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


class _ExchangeGate:
    """Hold only exchange commits while ordinary history commits proceed."""

    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self._entered_count = 0
        self._finished_count = 0
        self._lock = threading.Lock()

    def mark_entered(self) -> None:
        with self._lock:
            self._entered_count += 1
            if self._entered_count == self.expected:
                self.entered.set()

    def mark_finished(self) -> None:
        with self._lock:
            self._finished_count += 1
            if self._finished_count == self.expected:
                self.finished.set()


class _GatedSession:
    """Forward an AsyncSession, gating commits after an LLMExchange is added."""

    def __init__(self, session: Any, gate: _ExchangeGate) -> None:
        self._session = session
        self._gate = gate
        self._has_exchange = False

    def add(self, row: Any) -> None:
        self._has_exchange = self._has_exchange or isinstance(row, LLMExchange)
        self._session.add(row)

    async def commit(self) -> None:
        if not self._has_exchange:
            await self._session.commit()
            return
        self._gate.mark_entered()
        await self._gate.release.wait()
        try:
            await self._session.commit()
        finally:
            self._gate.mark_finished()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def _gated_sessions(store: ExchangeStore, gate: _ExchangeGate) -> Any:
    @asynccontextmanager
    async def sessions() -> AsyncIterator[_GatedSession]:
        async with store.sessions() as session:
            yield _GatedSession(session, gate)

    return sessions


def _question_for(subject: str, sampled: Any, question_id: str) -> Any:
    common = {
        "id": question_id,
        "核心問題": f"fixture-{subject}",
        "文本": "fixture text",
        "subquestions": [],
        "情境": [context.value for context in sampled.情境],
        "題型種類": sampled.題型種類.value,
        "題目": ["fixture question"],
        "正確解題分析": ["fixture answer"],
    }
    if subject == "social_studies":
        return SSExamQuestion(**common, 題型=sampled.題型[0].value)
    return NSExamQuestion(**common, 題型=sampled.題型.value)


def _fake_do_generate(subject: str, sampled: Any, **kwargs: Any) -> Any:
    """Make three parallel public LLMClient calls through the real observer."""
    client: LLMClient = kwargs["client"]
    ready = threading.Barrier(len(_AGENTS))

    def call(agent: str) -> dict:
        ready.wait(timeout=5)
        return client.generate_json(
            _PRIVATE_PROMPT,
            _PRIVATE_PROMPT,
            purpose="generate",
            agent_override=agent,
        )

    with ThreadPoolExecutor(max_workers=len(_AGENTS)) as workers:
        list(workers.map(call, _AGENTS))
    return _question_for(subject, sampled, kwargs["question_id"])


def _client_factory(config: ServerConfig) -> LLMClient:
    client = LLMClient(config)
    # The SDK object is the only external boundary replaced by this test.
    client.client = SimpleNamespace(messages=_FakeMessages())
    return client


async def _add_log(store: ExchangeStore, log_id: uuid.UUID, subject: str) -> None:
    async with store.sessions() as session:
        session.add(
            GenerationLog(
                id=log_id,
                user_id=store.user_id,
                params_json={"subject": subject, "count": 2},
                status="started",
            )
        )
        await session.commit()


async def _exchanges_for(store: ExchangeStore, log_id: uuid.UUID) -> list[dict[str, Any]]:
    response = await store.client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert response.status_code == 200
    return response.json()


async def _collect_stream(
    params: Any,
    config: ServerConfig,
    subject: str,
    log_id: uuid.UUID,
    user_id: uuid.UUID,
    session_factory: Any,
) -> list[dict[str, Any]]:
    fake_spec = dataclasses.replace(
        SUBJECTS[subject],
        do_generate=lambda sampled, _overrides, **kwargs: _fake_do_generate(
            subject, sampled, **kwargs
        ),
    )
    events: list[dict[str, Any]] = []
    async for event in generate_question_stream(
        params,
        config,
        SimpleNamespace(html_renderer=None, renderer_pool=None),
        user_id=user_id,
        generation_log_id=log_id,
        subjects={subject: fake_spec},
        session_factory=session_factory,
        client_factory=_client_factory,
    ):
        events.append(event)
    return events


@pytest.mark.parametrize("reject_exchanges", [False, True])
def test_concurrent_streams_continue_while_exchange_commits_are_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    reject_exchanges: bool,
) -> None:
    """SS and NS batches finish and persist history while exchange writes wait."""
    monkeypatch.setattr(persistence, "EXCHANGE_WRITE_TIMEOUT_SECONDS", 0.05)
    caplog.set_level(logging.WARNING, logger="server.generate.persistence")

    async def exercise() -> None:
        async with exchange_store(tmp_path) as store:
            subjects = ("social_studies", "natural_sciences")
            log_ids = {subject: uuid.uuid4() for subject in subjects}
            for subject in subjects:
                await _add_log(store, log_ids[subject], subject)

            # Two streams × two workers × three parallel agent slots.
            gate = _ExchangeGate(expected=12)
            session_factory = _gated_sessions(store, gate)
            config = ServerConfig(
                api_key="test-key",
                jwt_secret="exchange-test-secret",
                output_dir=tmp_path,
                data_dir=Path("data"),
                model_execute="claude-sonnet-4-6",
                llm_stream=False,
                creative_planning=False,
                llm_exchange_retention_days=30,
            )
            params = {
                subject: resolved_generate_params(
                    {"subject": subject, "count": 2, "seed": 41, "skip_verify": True}
                )
                for subject in subjects
            }

            streams = [
                asyncio.create_task(
                    _collect_stream(
                        params[subject],
                        config,
                        subject,
                        log_ids[subject],
                        store.user_id,
                        session_factory,
                    )
                )
                for subject in subjects
            ]
            try:
                await asyncio.wait_for(gate.entered.wait(), timeout=10)
                results = await asyncio.wait_for(asyncio.gather(*streams), timeout=10)

                for events in results:
                    assert sum(event["event"] == "result" for event in events) == 2
                    assert events[-1]["event"] == "done"

                history = await store.client.get("/api/history?limit=100")
                assert history.status_code == 200
                history_items = history.json()["items"]
                assert len(history_items) == 4
                assert {item["subject"] for item in history_items} == set(subjects)

                # All writes are still waiting at the real SQLite commit boundary.
                assert not gate.release.is_set()
                for subject in subjects:
                    assert await _exchanges_for(store, log_ids[subject]) == []

                if reject_exchanges:
                    async with store.sessions() as session:
                        await session.execute(
                            text(
                                "CREATE TRIGGER reject_stream_exchanges "
                                "BEFORE INSERT ON llm_exchanges "
                                "BEGIN SELECT RAISE(ABORT, 'PRIVATE_DATABASE_MESSAGE'); END"
                            )
                        )
                        await session.commit()

                gate.release.set()
                await asyncio.wait_for(gate.finished.wait(), timeout=10)
                await asyncio.sleep(0)

                for subject in subjects:
                    rows = await _exchanges_for(store, log_ids[subject])
                    if reject_exchanges:
                        assert rows == []
                        continue
                    assert len(rows) == 6
                    assert [row["exchange_order"] for row in rows] == list(range(1, 7))
                    assert sorted(row["agent"] for row in rows) == sorted(_AGENTS * 2)
                    assert {row["purpose"] for row in rows} == {"generate"}

                warnings = [
                    record
                    for record in caplog.records
                    if record.name == "server.generate.persistence"
                ]
                grouped: dict[tuple[str, str, int], list[str]] = {}
                for record in warnings:
                    key = (
                        record.generation_log_id,
                        record.agent,
                        record.exchange_order,
                    )
                    grouped.setdefault(key, []).append(record.outcome)
                assert len(grouped) == 12
                expected_completion = "failed" if reject_exchanges else "committed"
                assert all(
                    sorted(outcomes) == sorted(["pending", expected_completion])
                    for outcomes in grouped.values()
                ), grouped
                assert all(record.exc_info is None for record in warnings)
                assert _PRIVATE_PROMPT not in repr([record.__dict__ for record in warnings])
                assert _PRIVATE_ANSWER not in repr([record.__dict__ for record in warnings])
                if reject_exchanges:
                    assert all(
                        record.error_type == "IntegrityError"
                        for record in warnings
                        if record.outcome == "failed"
                    )
            finally:
                gate.release.set()
                try:
                    await asyncio.wait_for(gate.finished.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass
                await asyncio.gather(*streams, return_exceptions=True)

    asyncio.run(exercise())
