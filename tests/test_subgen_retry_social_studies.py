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
        self.scopes: list[object] = []


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
            self._state.scopes.append(kwargs.get("scope"))
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
    scopes = [scope for scope in state.scopes if scope is not None]
    assert len(scopes) == 4
    assert {scope.subquestion_index for scope in scopes} == {0, 1, 2}
    slot_two = [scope for scope in scopes if scope.subquestion_index == 1]
    assert len(slot_two) == 2
    assert slot_two[0].operation_id != slot_two[1].operation_id
    assert slot_two[1].supersedes_operation_id == slot_two[0].operation_id
    assert {scope.kind for scope in scopes} == {"subquestion"}


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


def test_dropped_slot_logged_to_stderr(capsys) -> None:
    """The 'dropped after' message is printed to stderr when all retries are exhausted.

    AC3 of issue #160: SS must log the dropped-slot line with the same wording
    as NS — 'Sub-generator sub_generator#N dropped after M attempt(s)'.
    """
    state = _State()
    flaky = _FlakySubClient(state, failing_slot=2, fail_times=99)
    _generate(state, flaky, subgen_retries=2)
    captured = capsys.readouterr()
    assert "Sub-generator sub_generator#2 dropped after 3 attempt(s)" in captured.err


def test_model_identity_is_ignored_and_slots_are_emitted_incrementally() -> None:
    """The resolver-owned slot identity survives arbitrary model metadata."""

    class _WrongIdentityClient(_FlakySubClient):
        def generate_json(self, system, user, images=None, agent_override=None, **kwargs):
            raw = super().generate_json(
                system,
                user,
                images=images,
                agent_override=agent_override,
                **kwargs,
            )
            idx = _slot(agent_override)
            raw["id"] = f"model-chosen-{idx}"
            raw["序號"] = "model-not-an-integer"
            return raw

    state = _State()
    updates: list[tuple[str, list[tuple[str, int, int | None]]]] = []

    def capture(question: ExamQuestion, phase: str) -> None:
        updates.append(
            (
                phase,
                [
                    (sub.id, sub.序號, sub._plan_index)
                    for sub in question.subquestions
                ],
            )
        )

    config = Config(data_dir=Path("data"), subgen_retries=0)
    params = sample_params(seed=11, content_type="純文字")
    question = generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="ss_fixed_identity",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _WrongIdentityClient(state, 0, 0),
        on_question_update=capture,
    )

    assert isinstance(question, ExamQuestion)
    assert [sub.id for sub in question.subquestions] == [
        "ss_fixed_identity-sq001",
        "ss_fixed_identity-sq002",
        "ss_fixed_identity-sq003",
    ]
    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3]
    assert [sub._plan_index for sub in question.subquestions] == [1, 2, 3]
    # #746: SS _ss_ensure_visual_spec stamps ICCS axes after sub-assembly → extra draft
    assert len(updates) == 5
    assert len(updates[0][1]) == 0
    assert sorted(len(rows) for _phase, rows in updates) == [0, 1, 2, 3, 3]


def test_middle_slot_failure_keeps_fixed_identity_in_updates() -> None:
    state = _State()
    updates: list[list[tuple[str, int, int | None]]] = []

    def capture(question: ExamQuestion, _phase: str) -> None:
        updates.append(
            [
                (sub.id, sub.序號, sub._plan_index)
                for sub in question.subquestions
            ]
        )

    config = Config(data_dir=Path("data"), subgen_retries=0)
    question = generate_one(
        config=config,
        client=_FakeTextClient(),
        params=sample_params(seed=11, content_type="純文字"),
        question_id="ss_fixed_gap",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _FlakySubClient(state, failing_slot=2, fail_times=99),
        on_question_update=capture,
    )

    assert isinstance(question, ExamQuestion)
    assert [sub.id for sub in question.subquestions] == [
        "ss_fixed_gap-sq001",
        "ss_fixed_gap-sq003",
    ]
    assert [sub.序號 for sub in question.subquestions] == [1, 3]
    assert [sub._plan_index for sub in question.subquestions] == [1, 3]
    assert updates[-1] == [
        ("ss_fixed_gap-sq001", 1, 1),
        ("ss_fixed_gap-sq003", 3, 3),
    ]


def test_plan_announces_zero_based_fixed_slot_manifest_before_subgenerators() -> None:
    events: list[dict] = []

    class _ObservedTextClient(_FakeTextClient):
        def get_observer(self):
            return events.append

    state = _State()
    question = generate_one(
        config=Config(data_dir=Path("data"), subgen_retries=0),
        client=_ObservedTextClient(),
        params=sample_params(seed=11, content_type="純文字"),
        question_id="ss_manifest",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _FlakySubClient(state, 0, 0),
    )

    assert isinstance(question, ExamQuestion)
    plan = next(event for event in events if event["type"] == "plan")
    assert plan["slots"] == [
        {"subquestion_index": 0, "id": "ss_manifest-sq001", "序號": 1},
        {"subquestion_index": 1, "id": "ss_manifest-sq002", "序號": 2},
        {"subquestion_index": 2, "id": "ss_manifest-sq003", "序號": 3},
    ]
