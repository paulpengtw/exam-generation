"""Shared complete generation fixtures for server seam tests."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from server.generate.models import GenerateParams
from src.common.resolver import resolve

_MATH_FIXTURE: dict[str, Any] = {
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
}


def _wire_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Encode resolver lists that the GET route models keep as JSON strings."""
    completed = dict(payload)
    # Stream v2 gate: inject stream_version=2 if not already present (#742)
    completed.setdefault("stream_version", 2)
    rows = completed.get("per_question_params")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("subquestion_configs"), list):
                row["subquestion_configs"] = json.dumps(
                    row["subquestion_configs"], ensure_ascii=False
                )
        completed["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    configs = completed.get("subquestion_configs")
    if isinstance(configs, list):
        completed["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)
    return completed


def complete_math_query_params(**overrides: Any) -> dict[str, Any]:
    """Return a resolver-complete math payload suitable for TestClient params."""
    payload = {**_MATH_FIXTURE, **overrides}
    return _wire_payload(resolve(payload).payload)


def resolved_generate_params(payload: dict[str, Any]) -> GenerateParams:
    """Build the service seam's complete model through the shared resolver."""
    return GenerateParams.model_validate(_wire_payload(resolve(payload).payload))


@contextmanager
def publisher_enqueue_gate(
    signal: threading.Event,
    *,
    question_index: int,
    event_names: frozenset[str] = frozenset({"result", "question_terminal"}),
) -> Iterator[None]:
    """Signal after a selected publisher envelope enters the stream queue."""
    from unittest.mock import patch

    from server.generate.publisher import GenerationPublisher

    class _ObservedQueue:
        def __init__(self, queue: Any) -> None:
            self._queue = queue

        def put_nowait(self, item: Any) -> None:
            self._queue.put_nowait(item)
            context = item.get("context", {}) if isinstance(item, dict) else {}
            if (
                isinstance(item, dict)
                and item.get("event") in event_names
                and context.get("index") == question_index
            ):
                signal.set()

    original_init = GenerationPublisher.__init__

    def observed_init(self: Any, run_id: str, loop: Any, queue: Any) -> None:
        original_init(self, run_id, loop, _ObservedQueue(queue))

    with patch.object(GenerationPublisher, "__init__", observed_init):
        yield
