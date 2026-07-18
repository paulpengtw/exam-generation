"""Per-子題 bounded retry in the SS parallel 子題產生器 pipeline (issue #117).

A failed 子題產生器 call — an exception from generate_json OR output that
_parse_subquestion cannot parse — must get up to config.subgen_retries fresh
LLM calls for that slot only before the slot is dropped from subquestions[].
Other slots are never regenerated.
"""

from __future__ import annotations

import threading
from pathlib import Path

from src.config import Config
from src.social_studies.cli import generate_one
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import ExamQuestion

N_SLOTS = 3


class _State:
    """Call-recording state shared across fake sub-clients (threads)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls_by_slot: dict[int, int] = {}
        self.factory_calls = 0


def _slot(agent_override: str) -> int:
    # generate_one always passes agent_override="sub_generator#<序號>".
    return int(agent_override.split("#", 1)[1])


def _valid_sq_raw(idx: int) -> dict:
    return {
        "序號": idx,
        "題型": "選擇題",
        "題目": f"第{idx}小題題目",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": f"概念{idx}",
    }


class _FakeTextClient:
    """文本生成器 stand-in: text shell with N_SLOTS 子題 plans, no chart_spec."""

    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [
                {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
                for i in range(1, N_SLOTS + 1)
            ],
        }


class _FlakySubClient:
    """Raises for failing_slot on its first fail_times calls, then succeeds."""

    def __init__(self, state: _State, failing_slot: int, fail_times: int) -> None:
        self._state = state
        self._failing_slot = failing_slot
        self._fail_times = fail_times

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = _slot(agent_override)
        with self._state.lock:
            attempt = self._state.calls_by_slot.get(idx, 0) + 1
            self._state.calls_by_slot[idx] = attempt
        if idx == self._failing_slot and attempt <= self._fail_times:
            raise RuntimeError(f"boom: slot {idx} attempt {attempt}")
        return _valid_sq_raw(idx)


def _generate(state: _State, sub_client, subgen_retries: int) -> ExamQuestion:
    config = Config(data_dir=Path("data"), subgen_retries=subgen_retries)

    def factory():
        with state.lock:
            state.factory_calls += 1
        return sub_client

    params = sample_params(seed=11, content_type="純文字")
    question = generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="ss_retry_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=factory,
    )
    assert isinstance(question, ExamQuestion)
    return question


def test_failed_slot_is_retried_and_recovered() -> None:
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=1)
    question = _generate(state, flaky, subgen_retries=1)
    assert [sq.序號 for sq in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot == {1: 1, 2: 2, 3: 1}
    # Fresh client per attempt: 3 initial + 1 retry for slot 2.
    assert state.factory_calls == 4


def test_zero_retries_drops_failed_slot_immediately() -> None:
    """SUBGEN_RETRIES=0 preserves today's drop-on-first-failure behavior."""
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=1)
    question = _generate(state, flaky, subgen_retries=0)
    assert [sq.序號 for sq in question.subquestions] == [1, 3]
    assert state.calls_by_slot == {1: 1, 2: 1, 3: 1}
    assert state.factory_calls == 3


def test_slot_dropped_after_retry_budget_exhausted() -> None:
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=99)
    question = _generate(state, flaky, subgen_retries=2)
    assert [sq.序號 for sq in question.subquestions] == [1, 3]
    assert state.calls_by_slot == {1: 1, 2: 3, 3: 1}  # 1 initial + 2 retries
    assert state.factory_calls == 5


def test_unparseable_output_is_also_retried() -> None:
    """_parse_subquestion returning None (no exception) must also trigger retry."""

    class _GarbageThenGoodClient:
        def __init__(self, state: _State) -> None:
            self._state = state

        def set_observer(self, obs) -> None:
            pass

        def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
            idx = _slot(agent_override)
            with self._state.lock:
                attempt = self._state.calls_by_slot.get(idx, 0) + 1
                self._state.calls_by_slot[idx] = attempt
            if idx == 1 and attempt == 1:
                return ["not", "a", "dict"]  # _parse_subquestion -> None
            return _valid_sq_raw(idx)

    state = _State()
    question = _generate(state, _GarbageThenGoodClient(state), subgen_retries=1)
    assert [sq.序號 for sq in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot[1] == 2
    assert state.factory_calls == 4
