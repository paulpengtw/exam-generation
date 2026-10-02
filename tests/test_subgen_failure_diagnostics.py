"""Public 子題 generation diagnostics for issues #817 and #818.

These scenarios use each subject's public ``generate_one`` pipeline and put a
controlled client at the external LLM boundary.  They deliberately exercise
the real subject parsers and the shared retry/drop path rather than replacing
either collaborator with a parser mock.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE
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
        self.users_by_slot: dict[int, list[str]] = {}


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


def _rubric(*, scalar_one_levels: bool = False, duplicate_one: bool = False) -> list[dict]:
    rows = [
        {
            "code": "2",
            "規準說明": f"完整推理。{EXTRA_ITEMS_FIXED_SENTENCE}",
            "學生作答實例": "完整回答" if scalar_one_levels else ["完整回答"],
        },
        {
            "code": "1",
            "規準說明": "推理鏈有缺口。",
            "學生作答實例": "缺少證據的回答"
            if scalar_one_levels
            else ["缺少證據的回答", "連結錯誤的回答"],
        },
        {
            "code": "0",
            "規準說明": "方向錯誤。",
            "學生作答實例": "錯誤觀念的回答"
            if scalar_one_levels
            else ["錯誤觀念的回答"],
        },
    ]
    if duplicate_one:
        rows.insert(
            2,
            {
                "code": "1",
                "規準說明": "第二個重複級距。",
                "學生作答實例": "另一個缺口",
            },
        )
    return rows


def _open_response_subquestion(
    subject: str,
    idx: int,
    *,
    scalar_one_levels: bool = False,
    duplicate_one: bool = False,
) -> dict[str, Any]:
    raw = _valid_subquestion(subject, idx)
    raw["題型"] = "開放式建構反應題" if subject == "ss" else "Constructed response"
    raw["評分規準"] = _rubric(
        scalar_one_levels=scalar_one_levels,
        duplicate_one=duplicate_one,
    )
    return raw


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
            self.state.users_by_slot.setdefault(idx, []).append(str(args[1]))

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
            if self.mode == "internal_parser_exception":
                raw = _valid_subquestion(self.subject, idx)
                raw["評分規準"] = [{"code": "explode"}]
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
            if self.mode == "safe_scalar":
                raw = _open_response_subquestion(self.subject, idx)
                raw["評分規準"][0]["學生作答實例"] = "完整回答"
                raw["評分規準"][2]["學生作答實例"] = "錯誤觀念的回答"
                return raw
            if self.mode in {"rubric_recover", "observed_rubric_failure"}:
                if attempt == 1:
                    return _open_response_subquestion(
                        self.subject,
                        idx,
                        scalar_one_levels=True,
                    )
                raw = _open_response_subquestion(
                    self.subject,
                    idx,
                    scalar_one_levels=self.mode == "observed_rubric_failure",
                    duplicate_one=self.mode == "observed_rubric_failure",
                )
                raw.update({
                    "id": "model-owned-slot",
                    "序號": 99,
                    "年級": 99,
                    "科學能力": ["模型自選能力"],
                    "核心素養": ["模型自選素養"],
                    "學習內容": [{"編碼": "模型自選內容", "說明": "private"}],
                    "學習表現": [{"編碼": "模型自選表現", "說明": "private"}],
                })
                return raw
        if self.mode in {
            "safe_scalar",
            "rubric_recover",
            "observed_rubric_failure",
        }:
            return _open_response_subquestion(self.subject, idx)
        return _valid_subquestion(self.subject, idx)


def _generate(
    subject: str,
    mode: str,
    *,
    tmp_path: Path,
    retries: int,
    observer: _ObserverCapture,
    state: _CallState,
    params: Any | None = None,
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
        config=Config(
            data_dir=Path("data"),
            output_dir=tmp_path,
            subgen_retries=retries,
        ),
        client=_TextClient(subject, observer),
        params=params or sample_params(seed=11, content_type="純文字"),
        question_id=f"diagnostics_{subject}_{mode}",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=factory,
    )
    assert isinstance(question, ExamQuestion)
    return question


def _open_response_params(subject: str):
    if subject == "ss":
        from src.social_studies.sampler import sample_params
        from src.social_studies.schemas import CoreCompetency, QuestionSubject, QuestionType

        competency = next(iter(CoreCompetency))
        params = sample_params(
            grade=9,
            seed=11,
            q_type=[QuestionType("開放式建構反應題")],
            subject=[QuestionSubject("歷史")],
            core_competency=[competency],
            learning_content=["歷A-Ⅳ-1"],
            learning_performance=["歷1a-Ⅳ-1"],
            content_type="純文字",
            sub_question_count=N_SLOTS,
            subquestion_configs=[
                {
                    "question_type": "開放式建構反應題",
                    "content_type": "純文字",
                    "learning_content": ["歷A-Ⅳ-1"],
                    "learning_performance": ["歷1a-Ⅳ-1"],
                }
                for _ in range(N_SLOTS)
            ],
        )
        return params

    from src.natural_sciences.sampler import sample_params
    from src.natural_sciences.schemas import QuestionType, ScienceCompetency

    competency = list(ScienceCompetency)[1]
    return sample_params(
        grade=8,
        seed=11,
        q_type=[QuestionType("Constructed response")],
        science_competency=[competency],
        learning_content=["Ab-Ⅳ-1"],
        learning_performance=["tr-Ⅳ-1"],
        content_type="純文字",
        sub_question_count=N_SLOTS,
        subquestion_configs=[
            {
                "question_type": "Constructed response",
                "content_type": "純文字",
                "learning_content": ["Ab-Ⅳ-1"],
                "learning_performance": ["tr-Ⅳ-1"],
            }
            for _ in range(N_SLOTS)
        ],
    )


def _core_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "src.common.generation_core"
        and record.levelno >= logging.WARNING
    ]


def _diagnostic_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.WARNING]


def _assert_submitted_pins(subject: str, subquestion: Any, params: Any) -> None:
    assert subquestion.年級 == params.grade
    assert subquestion.題目內容類型 == "純文字"
    assert [ref.編碼 for ref in subquestion.學習內容] == [
        params.subquestion_configs[1].learning_content[0]
    ]
    assert [ref.編碼 for ref in subquestion.學習表現] == [
        params.subquestion_configs[1].learning_performance[0]
    ]
    if subject == "ss":
        assert subquestion.科目 == [params.科目.value]
        assert subquestion.核心素養 == [item.value for item in params.核心素養]
        assert subquestion.題型.value == "開放式建構反應題"
    else:
        assert subquestion.科目 == ["自然科學"]
        assert subquestion.科學能力 == [item.value for item in params.科學能力]
        assert subquestion.題型.value == "Constructed response"


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_scalar_rubric_examples_normalize_without_retry_or_error(
    subject: str,
    tmp_path: Path,
) -> None:
    observer = _ObserverCapture()
    state = _CallState()
    params = _open_response_params(subject)

    question = _generate(
        subject,
        "safe_scalar",
        tmp_path=tmp_path,
        retries=1,
        observer=observer,
        state=state,
        params=params,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot == {1: 1, 2: 1, 3: 1}
    examples = [row.學生作答實例 for row in question.subquestions[1].評分規準]
    assert examples == [
        ["完整回答"],
        ["缺少證據的回答", "連結錯誤的回答"],
        ["錯誤觀念的回答"],
    ]
    assert observer.stages(status="error") == []


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_rubric_retry_uses_safe_feedback_and_restores_submitted_pins(
    subject: str,
    tmp_path: Path,
) -> None:
    observer = _ObserverCapture()
    state = _CallState()
    params = _open_response_params(subject)

    question = _generate(
        subject,
        "rubric_recover",
        tmp_path=tmp_path,
        retries=1,
        observer=observer,
        state=state,
        params=params,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 2, 3]
    assert state.calls_by_slot == {1: 1, 2: 2, 3: 1}
    first_prompt, retry_prompt = state.users_by_slot[2]
    assert retry_prompt != first_prompt
    assert first_prompt in retry_prompt
    assert "評分規準" in retry_prompt
    assert "需要 2 個學生作答實例" in retry_prompt
    assert PRIVATE_PROVIDER_TEXT not in retry_prompt
    assert PRIVATE_VISUAL_TEXT not in retry_prompt
    recovered = question.subquestions[1]
    assert recovered.id == f"diagnostics_{subject}_rubric_recover-sq002"
    assert recovered.序號 == 2
    assert recovered._plan_index == 2
    _assert_submitted_pins(subject, recovered, params)
    assert observer.stages(status="error") == []


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_duplicate_rubric_exhaustion_drops_only_observed_slot_with_safe_fields(
    subject: str,
    tmp_path: Path,
) -> None:
    observer = _ObserverCapture()
    state = _CallState()
    params = _open_response_params(subject)

    question = _generate(
        subject,
        "observed_rubric_failure",
        tmp_path=tmp_path,
        retries=1,
        observer=observer,
        state=state,
        params=params,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 3]
    assert state.calls_by_slot == {1: 1, 2: 2, 3: 1}
    first_prompt, retry_prompt = state.users_by_slot[2]
    assert first_prompt in retry_prompt
    assert "需要 2 個學生作答實例" in retry_prompt
    errors = [
        event
        for event in observer.stages(status="error")
        if event.get("agent") == "sub_generator#2"
    ]
    assert len(errors) == 1
    error = errors[0]
    assert error["code"] == "subquestion_exhausted"
    assert error["failure_code"] == "validation_exhausted"
    assert "評分規準" in error["failure_detail"]
    assert "各一級" in error["failure_detail"]
    assert len(error["failure_detail"]) <= 240
    assert PRIVATE_PROVIDER_TEXT not in error["failure_detail"]
    assert PRIVATE_VISUAL_TEXT not in error["failure_detail"]


def test_unexpected_parser_exception_exposes_only_its_class_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.natural_sciences.cli as natural_sciences_cli

    class PrivateParserFailure(RuntimeError):
        pass

    original_parser = natural_sciences_cli._NS_SPEC.parse_subquestion_fn

    def fail_middle_slot(raw: Any, question_id: str, params: Any, idx: int) -> Any:
        if idx == 2:
            raise PrivateParserFailure(PRIVATE_PROVIDER_TEXT)
        return original_parser(raw, question_id, params, idx)

    monkeypatch.setattr(
        natural_sciences_cli,
        "_NS_SPEC",
        dataclasses.replace(
            natural_sciences_cli._NS_SPEC,
            parse_subquestion_fn=fail_middle_slot,
        ),
    )
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        "ns",
        "recover",
        tmp_path=tmp_path,
        retries=0,
        observer=observer,
        state=state,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 3]
    error = next(
        event
        for event in observer.stages(status="error")
        if event.get("agent") == "sub_generator#2"
    )
    assert error["failure_code"] == "parser_failure"
    assert error["failure_detail"] == (
        "subquestion parser raised PrivateParserFailure"
    )
    assert PRIVATE_PROVIDER_TEXT not in error["message"]


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_subject_parser_unexpected_exception_is_not_validation_feedback(
    subject: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if subject == "ss":
        import src.social_studies.cli as subject_cli
    else:
        import src.natural_sciences.cli as subject_cli

    class PrivateParserFailure(RuntimeError):
        pass

    original_normalizer = subject_cli.normalize_rubric_student_examples

    def fail_for_sentinel(rows: Any) -> Any:
        if any(row.get("code") == "explode" for row in rows):
            raise PrivateParserFailure(PRIVATE_PROVIDER_TEXT)
        return original_normalizer(rows)

    monkeypatch.setattr(
        subject_cli,
        "normalize_rubric_student_examples",
        fail_for_sentinel,
    )
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        "internal_parser_exception",
        tmp_path=tmp_path,
        retries=1,
        observer=observer,
        state=state,
    )

    assert [sub.序號 for sub in question.subquestions] == [1, 3]
    assert state.users_by_slot[2][0] == state.users_by_slot[2][1]
    error = next(
        event
        for event in observer.stages(status="error")
        if event.get("agent") == "sub_generator#2"
    )
    assert error["failure_code"] == "parser_failure"
    assert error["failure_detail"] == (
        "subquestion parser raised PrivateParserFailure"
    )
    assert PRIVATE_PROVIDER_TEXT not in error["message"]


@pytest.mark.parametrize("subject", ["ss", "ns"])
@pytest.mark.parametrize(
    ("mode", "retries", "cause", "failure_code"),
    [
        ("unusable", 0, "題型", "validation_exhausted"),
        ("unusable_list", 0, "題型", "validation_exhausted"),
        ("unusable_object", 0, "題型", "validation_exhausted"),
        ("raised", 0, "RuntimeError", "provider_failure"),
        ("mixed", 1, "題型", "validation_exhausted"),
    ],
)
def test_exhausted_slot_reports_final_failure_cause_without_private_warning_data(
    subject: str,
    mode: str,
    retries: int,
    cause: str,
    failure_code: str,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.WARNING, logger="src.common.generation_core")
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        mode,
        tmp_path=tmp_path,
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
    assert errors[0]["code"] == "subquestion_exhausted"
    assert errors[0]["failure_code"] == failure_code
    assert errors[0]["failure_detail"] in errors[0]["message"]
    assert len(errors[0]["failure_detail"]) <= 240
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
    if mode == "mixed":
        assert state.users_by_slot[2][0] == state.users_by_slot[2][1]


@pytest.mark.parametrize("subject", ["ss", "ns"])
def test_schema_failure_reports_bad_question_field_and_type(
    subject: str,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.WARNING)
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        "bad_question",
        tmp_path=tmp_path,
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
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.WARNING)
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        "visual_then_recover",
        tmp_path=tmp_path,
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
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.WARNING)
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        mode,
        tmp_path=tmp_path,
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
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.WARNING, logger="src.common.generation_core")
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        "recover",
        tmp_path=tmp_path,
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
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.WARNING, logger="src.common.generation_core")
    observer = _ObserverCapture()
    state = _CallState()

    question = _generate(
        subject,
        mode,
        tmp_path=tmp_path,
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
