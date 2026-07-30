"""Dropped 子題 slot emits a stage error event (issue #257 slice 1).

When all retry attempts for a slot are exhausted, an error stage event is
emitted to the observer with the exception text and slot identity.
When a slot eventually succeeds (possibly after retries), no error event is emitted.
"""

from __future__ import annotations

import threading
from pathlib import Path

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion

N_SLOTS = 3


class _ObserverCapture:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self._lock = threading.Lock()

    def __call__(self, event: dict) -> None:
        with self._lock:
            self.events.append(event)

    def error_events(self) -> list[dict]:
        with self._lock:
            return [
                e for e in self.events
                if e.get("type") == "stage" and e.get("status") == "error"
            ]


def _make_text_client(observer: _ObserverCapture):
    class _FakeTextClient:
        def get_observer(self):
            return observer

        def generate_json(self, *args, **kwargs):
            return {
                "核心問題": "測試核心問題",
                "文本": "測試文本",
                "取材來源": ["測試"],
                "subquestions": [
                    {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
                    for i in range(1, N_SLOTS + 1)
                ],
            }
    return _FakeTextClient()


class _AlwaysFailClient:
    """Always raises RuntimeError on generate_json."""
    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, *args, **kwargs):
        raise RuntimeError("boom: always fails slot")


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls_by_slot: dict[int, int] = {}


def _slot(agent_override: str) -> int:
    return int(agent_override.split("#", 1)[1])


class _FailOnceThenSucceed:
    """Fails the first call per slot, succeeds thereafter."""
    def __init__(self, state: _State) -> None:
        self._state = state

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, *args, agent_override=None, **kwargs):
        idx = _slot(agent_override)
        with self._state.lock:
            count = self._state.calls_by_slot.get(idx, 0) + 1
            self._state.calls_by_slot[idx] = count
        if count == 1:
            raise RuntimeError(f"first attempt fails: slot {idx}")
        return {
            "序號": idx,
            "題型": "選擇題",
            "題目": f"題目{idx}",
            "答案": "A",
            "答案解析": "解析",
            "出題概念": f"概念{idx}",
        }


def _generate(text_client, factory, subgen_retries: int) -> ExamQuestion:
    config = Config(data_dir=Path("data"), subgen_retries=subgen_retries)
    params = sample_params(seed=11, content_type="純文字")
    question = generate_one(
        config=config,
        client=text_client,
        params=params,
        question_id="test_error_event",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=factory,
    )
    assert isinstance(question, ExamQuestion)
    return question


def test_exhausted_slot_emits_error_stage_event() -> None:
    """When all attempts are exhausted, an error stage event is emitted."""
    observer = _ObserverCapture()
    text_client = _make_text_client(observer)

    def factory():
        return _AlwaysFailClient()

    _generate(text_client, factory, subgen_retries=0)

    errors = observer.error_events()
    # All N_SLOTS should have emitted error events
    assert len(errors) == N_SLOTS
    # Each error event must contain "boom" (the exception text)
    for e in errors:
        assert "boom" in e.get("message", ""), f"Missing exception text in: {e}"


def test_error_event_contains_slot_identity() -> None:
    """The agent field of the error event identifies the failing slot."""
    observer = _ObserverCapture()
    text_client = _make_text_client(observer)

    def factory():
        return _AlwaysFailClient()

    _generate(text_client, factory, subgen_retries=0)

    errors = observer.error_events()
    agents = {e.get("agent", "") for e in errors}
    # Every agent must match sub_generator#N pattern
    for agent in agents:
        assert agent.startswith("sub_generator#"), f"Unexpected agent: {agent}"


def test_successful_retry_emits_no_error_event() -> None:
    """When a slot fails once but succeeds on retry, no error event is emitted."""
    observer = _ObserverCapture()
    text_client = _make_text_client(observer)
    state = _State()
    client = _FailOnceThenSucceed(state)

    def factory():
        return client

    question = _generate(text_client, factory, subgen_retries=1)

    # All slots should succeed
    assert len(question.subquestions) == N_SLOTS
    # No error events should have been emitted
    assert observer.error_events() == [], f"Unexpected error events: {observer.error_events()}"


def test_successful_slot_has_end_event_not_error() -> None:
    """A slot that succeeds emits an end event, not an error event."""
    observer = _ObserverCapture()
    text_client = _make_text_client(observer)
    state = _State()
    client = _FailOnceThenSucceed(state)

    def factory():
        return client

    _generate(text_client, factory, subgen_retries=1)

    end_events = [
        e for e in observer.events
        if e.get("type") == "stage" and e.get("status") == "end"
        and e.get("agent", "").startswith("sub_generator#")
    ]
    # Each slot should have exactly one end event (from the successful attempt)
    assert len(end_events) == N_SLOTS
