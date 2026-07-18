"""Integration tests: N 子題產生器 dispatches run in parallel and results
keep 序號 order (issue #117 acceptance criteria), for both SS and NS.

A shared threading.Barrier(N_SLOTS) only releases when all N fake LLM calls
are in flight at once — serialized dispatch would time out and fail loudly
(subgen_retries=0 ensures no retry masks a BrokenBarrierError). Staggered
sleeps then force reverse-序號 completion, so as_completed() yields results
out of order and the 序號-sorted reassembly is actually exercised.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from src.config import Config

N_SLOTS = 4
BARRIER_TIMEOUT_S = 30.0


class _DispatchState:
    def __init__(self) -> None:
        self.barrier = threading.Barrier(N_SLOTS)
        self.lock = threading.Lock()
        self.dispatched_agents: list[str] = []
        self.completion_order: list[int] = []


class _BarrierSubClient:
    """Blocks until all N_SLOTS workers arrive, then finishes in reverse order."""

    def __init__(self, state: _DispatchState, sq_raw_for) -> None:
        self._state = state
        self._sq_raw_for = sq_raw_for

    def set_observer(self, obs) -> None:
        pass

    def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
        idx = int(agent_override.split("#", 1)[1])
        with self._state.lock:
            self._state.dispatched_agents.append(agent_override)
        # Concurrency proof: releases only when N_SLOTS calls are in flight.
        self._state.barrier.wait(timeout=BARRIER_TIMEOUT_S)
        # Scramble completion: higher 序號 finishes first.
        time.sleep(0.1 * (N_SLOTS - idx))
        with self._state.lock:
            self._state.completion_order.append(idx)
        return self._sq_raw_for(idx)


def _config() -> Config:
    # subgen_retries=0: a BrokenBarrierError must surface as a dropped slot,
    # never be absorbed by the Task 2/3 retry path.
    return Config(
        data_dir=Path("data"),
        subgen_max_concurrency=N_SLOTS,
        subgen_retries=0,
    )


def _assert_parallel_and_ordered(state: _DispatchState, question) -> None:
    # N parallel dispatches, exactly one per slot.
    assert sorted(state.dispatched_agents) == [
        f"sub_generator#{i}" for i in range(1, N_SLOTS + 1)
    ]
    # Workers completed out of 序號 order (reverse, via staggered sleeps)...
    assert set(state.completion_order) == set(range(1, N_SLOTS + 1))
    assert state.completion_order != sorted(state.completion_order)
    # ...but the assembled 題組 is in 序號 order with each slot's own payload.
    assert [sq.序號 for sq in question.subquestions] == [1, 2, 3, 4]
    assert [sq.題目 for sq in question.subquestions] == [
        f"第{i}小題題目" for i in range(1, N_SLOTS + 1)
    ]


# ---------------------------------------------------------------- 社會領域


def _ss_sq_raw(idx: int) -> dict:
    return {
        "序號": idx,
        "題型": "選擇題",
        "題目": f"第{idx}小題題目",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": f"概念{idx}",
    }


class _SSTextClient:
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


def test_social_studies_parallel_dispatch_and_seq_order() -> None:
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import ExamQuestion

    state = _DispatchState()
    params = sample_params(seed=23, content_type="純文字")
    question = generate_one(
        config=_config(),
        client=_SSTextClient(),
        params=params,
        question_id="ss_dispatch_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _BarrierSubClient(state, _ss_sq_raw),
    )
    assert isinstance(question, ExamQuestion)
    _assert_parallel_and_ordered(state, question)


# ---------------------------------------------------------------- 自然科學


def _ns_sq_raw(idx: int) -> dict:
    return {
        "序號": idx,
        "題型": "Simple multiple-choice",
        "題目": f"第{idx}小題題目",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": f"概念{idx}",
    }


class _NSTextClient:
    def get_observer(self):
        return None

    def generate_json(self, system, user, images=None, **kwargs):
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [
                {"序號": i, "題型": "Simple multiple-choice", "出題概念": f"概念{i}"}
                for i in range(1, N_SLOTS + 1)
            ],
        }


def test_natural_sciences_parallel_dispatch_and_seq_order() -> None:
    from src.natural_sciences.cli import generate_one
    from src.natural_sciences.sampler import sample_params
    from src.natural_sciences.schemas import ExamQuestion

    state = _DispatchState()
    params = sample_params(seed=23, content_type="純文字")
    question = generate_one(
        config=_config(),
        client=_NSTextClient(),
        params=params,
        question_id="ns_dispatch_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _BarrierSubClient(state, _ns_sq_raw),
    )
    assert isinstance(question, ExamQuestion)
    _assert_parallel_and_ordered(state, question)
