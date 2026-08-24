"""Persistence seam tests for the 社會領域 圖像種類 policy trail."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from server.generate.models import GenerateParams
from server.generate.persistence import persist_generation_record


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


def test_completed_social_generation_persists_the_figure_policy_trail() -> None:
    rows: list[Any] = []
    expected_trail = [
        {
            "code": "figure_policy",
            "kind": "spec",
            "question_id": "ss-policy",
            "label": "題幹",
            "effective_figure_kind": "地圖",
            "timestamp": "2026-08-25T00:00:00Z",
        }
    ]

    asyncio.run(
        persist_generation_record(
            user_id=uuid.uuid4(),
            generation_log_id=None,
            subject="social_studies",
            params=GenerateParams(subject="social_studies"),
            payload={"id": "ss-policy"},
            figure_policy_trail_json=expected_trail,
            session_factory=_make_factory(rows),
        )
    )

    assert rows[0].figure_policy_trail_json == expected_trail
