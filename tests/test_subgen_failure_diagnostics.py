"""Public 子題 generation diagnostics for issues #817 and #818.

These scenarios use each subject's public ``generate_one`` pipeline and put a
controlled client at the external LLM boundary.  They deliberately exercise
the real subject parsers and the shared retry/drop path rather than replacing
either collaborator with a parser mock.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from src.config import Config

N_SLOTS = 3
PRIVATE_PROVIDER_TEXT = "PRIVATE_PROVIDER_EXCEPTION"
PRIVATE_VISUAL_TEXT = "PRIVATE_VISUAL_PAYLOAD"


class _ObserverCapture:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, event: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(event)

    def stages(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [
                event
                for event in self.events
                if event.get("type") == "stage"
                and (status is None or event.get("status") == status)
            ]


class _CallState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls_by_slot: dict[int, int] = {}
        self.factory_calls = 0


def _slot(agent_override: str | None) -> int:
    assert agent_override is not None
    return int(agent_override.split("#", 1)[1])


def _valid_subquestion(subject: str, idx: int) -> dict[str, Any]:
    return {
        "序號": idx,
        "題型": "選擇題" if subject == "ss" else "Simple multiple-choice",
        "題目": f"第{idx}小題題目",
        "答案": "A",
        "答案解析": "解析",
        "出題概念": f"概念{idx}",
    }


class _TextClient:
    def __init__(self, subject: str, observer: _ObserverCapture) -> None:
        self.subject = subject
        self.observer = observer

    def get_observer(self) -> _ObserverCapture:
        return self.observer

    def generate_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        qtype = "選擇題" if self.subject == "ss" else "Simple multiple-choice"
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試來源"],
            "subquestions": [
                {"序號": idx, "題型": qtype, "出題概念": f"概念{idx}"}
                for idx in range(1, N_SLOTS + 1)
            ],
        }


class _ScriptedSubClient:
    def __init__(self, subject: str, state: _CallState, mode: str) -> None:
        self.subject = subject
        self.state = state
        self.mode = mode

    def set_observer(self, observer: Any) -> None:
        pass

    def generate_json(self, *args: Any, agent_override: str | None = None, **kwargs: Any):
        idx = _slot(agent_override)
        with self.state.lock:
            attempt = self.state.calls_by_slot.get(idx, 0) + 1
            self.state.calls_by_slot[idx] = attempt

        if idx == 2:
            if self.mode == "raised":
                raise RuntimeError(PRIVATE_PROVIDER_TEXT)
            if self.mode == "unusable":
                return {"題型": "not-a-valid-question-type", "題目": PRIVATE_VISUAL_TEXT}
            if self.mode == "unusable_list":
                return {"題型": [PRIVATE_VISUAL_TEXT], "題目": "題目"}
            if self.mode == "unusable_object":
                return {"題型": {"private": PRIVATE_VISUAL_TEXT}, "題目": "題目"}
            if self.mode == "mixed":
                if attempt == 1:
                    raise RuntimeError(PRIVATE_PROVIDER_TEXT)
                return {"題型": "not-a-valid-question-type", "題目": PRIVATE_VISUAL_TEXT}
            if self.mode == "recover" and attempt == 1:
                return {"題型": "not-a-valid-question-type", "題目": PRIVATE_VISUAL_TEXT}
            if self.mode == "visual":
                raw = _valid_subquestion(self.subject, idx)
                raw["chart_spec"] = {
                    "render_mode": "pdf",
                    "chart_type": "not-a-chart",
                    "description": PRIVATE_VISUAL_TEXT,
                }
                return raw
            if self.mode == "visual_list":
                raw = _valid_subquestion(self.subject, idx)
                raw["image_spec"] = []
                return raw
            if self.mode == "visual_list_with_chart":
                raw = _valid_subquestion(self.subject, idx)
                raw["image_spec"] = []
                raw["chart_spec"] = {
                    "render_mode": "chart",
                    "chart_type": "histogram",
                    "data": {"A": 1},
                }
                return raw
            if self.mode == "visual_dict_with_chart":
                raw = _valid_subquestion(self.subject, idx)
                raw["image_spec"] = {}
                raw["chart_spec"] = {
                    "render_mode": "chart",
                    "chart_type": "histogram",
                    "data": {"A": 1},
                }
                return raw
            if self.mode == "bad_question":
                raw = _valid_subquestion(self.subject, idx)
                raw["題目"] = {"private": PRIVATE_VISUAL_TEXT}
                return raw
            if self.mode == "visual_then_recover" and attempt == 1:
                raw = _valid_subquestion(self.subject, idx)
                raw["題目"] = {"private": PRIVATE_VISUAL_TEXT}
                raw["chart_spec"] = {
                    "render_mode": "pdf",
                    "chart_type": "not-a-chart",
                    "description": PRIVATE_VISUAL_TEXT,
                }
                return raw
        return _valid_subquestion(self.subject, idx)


def _generate(
    subject: str,
    mode: str,
    *,
    retries: int,
    observer: _ObserverCapture,
    state: _CallState,
):
    if subject == "ss":
        from src.social_studies.cli import generate_one
        from src.social_studies.sampler import sample_params
        from src.social_studies.schemas import ExamQuestion
    else:
        from src.natural_sciences.cli import generate_one
        from src.natural_sciences.sampler import sample_params
        from src.natural_sciences.schemas import ExamQuestion

    sub_client = _ScriptedSubClient(subject, state, mode)

    def factory() -> _ScriptedSubClient:
        with state.lock:
            state.factory_calls += 1
        return sub_client

    question = generate_one(
        config=Config(data_dir=Path("data"), subgen_retries=retries),
        client=_TextClient(subject, observer),
        params=sample_params(seed=11, content_type="純文字"),
        question_id=f"diagnostics_{subject}_{mode}",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=factory,
    )
    assert isinstance(question, ExamQuestion)
    return question


def _core_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "src.common.generation_core"
        and record.levelno >= logging.WARNING
    ]


def _diagnostic_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.WARNING]


@pytest.mark.parametrize("subject", ["ss", "ns"])
@pytest.mark.parametrize(
    ("mode", "retries", "cause"),
    [
        ("unusable", 0, "題型"),
        ("unusable_list", 0, "題型"),
        ("unusable_object", 0, "題型"),
        ("raised", 0, "RuntimeError"),
        ("mixed", 1, "題型"),
    ],
)
def test_exhausted_slot_reports_final_failure_cause_without_private_warning_data(
    subject: str,
    mode: str,
    retries: int,
    cause: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="src.common.generation_core")
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        mode,
        retries=retries,
        observer=observer,
        state=state,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 3]
    assert state.calls_by_slot == ({1: 1, 2: 2, 3: 1} if mode == "mixed" else {1: 1, 2: 1, 3: 1})
    assert state.factory_calls == (4 if mode == "mixed" else 3)

    errors = [
        event
        for event in observer.stages(status="error")
        if event.get("agent") == "sub_generator#2"
    ]
    assert len(errors) == 1
    assert cause in errors[0].get("message", "")
    assert PRIVATE_PROVIDER_TEXT not in errors[0].get("message", "")
    assert PRIVATE_VISUAL_TEXT not in errors[0].get("message", "")

    warnings = [
        record
        for record in _diagnostic_warnings(caplog)
        if "subquestion generation exhausted" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert cause in warnings[0].getMessage()
    assert PRIVATE_PROVIDER_TEXT not in warnings[0].getMessage()
    assert PRIVATE_VISUAL_TEXT not in warnings[0].getMessage()


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_schema_failure_reports_bad_question_field_and_type(
    subject: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        "bad_question",
        retries=0,
        observer=observer,
        state=state,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 3]
    error = next(
        event for event in observer.stages(status="error")
        if event.get("agent") == "sub_generator#2"
    )
    # Issue #937: a non-string or blank 題目 is now caught before Pydantic; the
    # error message still names the 題目 field but no longer includes the
    # Pydantic-internal "string_type" type code.
    assert "題目" in error["message"]
    warning = next(
        record for record in _core_warnings(caplog)
        if "subquestion generation exhausted" in record.getMessage()
    )
    assert "題目" in warning.getMessage()
    assert PRIVATE_VISUAL_TEXT not in warning.getMessage()


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_visual_discard_waits_for_a_constructed_row_before_warning(
    subject: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        "visual_then_recover",
        retries=1,
        observer=observer,
        state=state,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot == {1: 1, 2: 2, 3: 1}
    assert observer.stages(status="error") == []
    assert not any(
        "subquestion visual specification" in record.getMessage()
        for record in _diagnostic_warnings(caplog)
    )


@pytest.mark.parametrize("subject", ["ss", "ns"])
@pytest.mark.parametrize("mode", ["visual_list_with_chart", "visual_dict_with_chart"])
def test_falsey_primary_visual_alias_falls_back_to_valid_chart(
    subject: str,
    mode: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        mode,
        retries=0,
        observer=observer,
        state=state,
    )

    assert question.subquestions[1].chart_spec is not None
    assert not any(
        "subquestion visual specification" in record.getMessage()
        for record in _diagnostic_warnings(caplog)
    )


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_unusable_slot_recovery_keeps_budget_without_drop_diagnostic(
    subject: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="src.common.generation_core")
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        "recover",
        retries=1,
        observer=observer,
        state=state,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot == {1: 1, 2: 2, 3: 1}
    assert state.factory_calls == 4
    assert observer.stages(status="error") == []
    assert not any(
        "subquestion generation exhausted" in record.getMessage()
        for record in _core_warnings(caplog)
    )


@pytest.mark.parametrize("subject", ["ss", "ns"])
@pytest.mark.parametrize("mode", ["visual", "visual_list"])
def test_malformed_visual_spec_retains_subquestion_and_logs_safe_discard(
    subject: str,
    mode: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="src.common.generation_core")
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        mode,
        retries=0,
        observer=observer,
        state=state,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3]
    assert question.subquestions[1].chart_spec is None
    assert observer.stages(status="error") == []
    assert [
        event for event in observer.stages()
        if event.get("agent") == "image_agent"
    ] == []
    warnings = [
        record
        for record in _diagnostic_warnings(caplog)
        if "visual" in record.getMessage().lower()
        or "chart" in record.getMessage().lower()
    ]
    assert warnings
    assert any(
        "question_id=diagnostics_" in record.getMessage()
        and "slot=2" in record.getMessage()
        for record in warnings
    )
    assert all(PRIVATE_VISUAL_TEXT not in record.getMessage() for record in warnings)
