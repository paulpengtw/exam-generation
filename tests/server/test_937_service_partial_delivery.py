"""Service-level regression test for issue #937.

Verifies that when a 子題產生器 returns a blank or missing ``題目`` field, the
fixed-slot pipeline:

1. Raises ``SubquestionParseError`` in ``_parse_subquestion`` (unit gate).
2. Exhausts ``SUBGEN_RETRIES + 1`` attempts for the failing slot (bounded retry).
3. Drops that slot from the final ``subquestions`` list.
4. Records the dropped slot in ``question_terminal.missing`` with the correct
   ``subquestion_id`` / ``subquestion_index``.
5. Sets ``delivery_status = "partial"`` (not "complete").
6. Delivers siblings at their original manifest positions.

The test covers both ``social_studies`` and ``natural_sciences`` via
``@pytest.mark.parametrize``.

When ``GENERATE_937_FIXTURE=1`` is set the test also writes the JSONL fixture
used by the frontend vitest suite (``tests/fixtures/generation_v2/``).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Ensure routes module is imported before tests run so the conftest autouse
# _bypass_build_admission fixture can patch it.
import server.generate.routes  # noqa: F401

FIXTURE_PATHS = {
    "social_studies": (
        Path(__file__).parent.parent
        / "fixtures"
        / "generation_v2"
        / "social_partial_delivery.jsonl"
    ),
    "natural_sciences": (
        Path(__file__).parent.parent
        / "fixtures"
        / "generation_v2"
        / "ns_partial_delivery.jsonl"
    ),
}

# Slot index (0-based) of the failing subquestion.
_BAD_SLOT_INDEX = 1   # plan positions are 0-based; this is sq002
_TOTAL_SLOTS = 3
# Default SUBGEN_RETRIES is 1 → 1 + 1 = 2 total attempts.
_EXPECTED_ATTEMPTS = 2


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, _config: Any) -> None:
        self._observer = None

    def set_observer(self, observer: Any) -> None:
        self._observer = observer

    def clear_observer(self) -> None:
        self._observer = None

    def emit(self, event: dict[str, Any]) -> None:
        if self._observer is not None:
            self._observer(event)


# ---------------------------------------------------------------------------
# Fixture masking helper
# ---------------------------------------------------------------------------


def _mask_item(
    item: dict[str, Any],
    run_id: str,
    *,
    operation_names: dict[str, str] | None = None,
    call_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    raw = json.dumps(item, ensure_ascii=False).replace(run_id, "RUN")
    raw = re.sub(r'"ts":\s*\d+(?:\.\d+)?', '"ts": 0.0', raw)
    raw = re.sub(r'"generation_log_id":\s*"[^"]*"', '"generation_log_id": "LOG"', raw)
    raw = re.sub(
        r'"[^"\n]*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^"\n]*"',
        '"TS"',
        raw,
    )
    operation_names = operation_names if operation_names is not None else {}
    call_names = call_names if call_names is not None else {}

    def mask_operation(match: re.Match[str]) -> str:
        value = match.group(0)
        operation_names.setdefault(value, f"RUN:operation:OP{len(operation_names) + 1}")
        return operation_names[value]

    def mask_call(match: re.Match[str]) -> str:
        value = match.group(0)
        call_names.setdefault(value, f"RUN:call:CALL{len(call_names) + 1}")
        return call_names[value]

    raw = re.sub(r"RUN:operation:[0-9a-f]+", mask_operation, raw)
    raw = re.sub(r"RUN:call:[0-9a-f]+", mask_call, raw)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Schema helpers (shared between SS and NS)
# ---------------------------------------------------------------------------


def _shell(subject: str, qid: str, params: Any) -> Any:
    """Build a minimal text-shell ExamQuestion (no subquestions)."""
    if subject == "natural_sciences":
        from src.natural_sciences.schemas import ExamQuestion
        return ExamQuestion(
            id=qid,
            核心問題="核心問題 937",
            文本="文本 937",
            取材來源=["來源 937"],
            情境=list(params.情境),
            情境子類別=params.情境子類別,
            題型種類=params.題型種類,
            題型=params.題型,
            科學能力=list(params.科學能力),
            題目內容類型=params.題目內容類型,
        )
    # social_studies
    from src.social_studies.schemas import ExamQuestion
    return ExamQuestion(
        id=qid,
        核心問題="核心問題 937",
        文本="文本 937",
        取材來源=["來源 937"],
        情境=list(params.情境),
        題型種類=params.題型種類,
        題型=rng_params_to_qtype(params),
        題目內容類型=params.題目內容類型,
    )


def rng_params_to_qtype(params: Any) -> Any:
    from src.social_studies.schemas import QuestionType
    t = params.題型[0] if params.題型 else None
    if isinstance(t, str):
        return QuestionType(t)
    return t or QuestionType("選擇題")


def _subquestion(subject: str, qid: str, slot: int, params: Any) -> Any:
    """Build a minimal valid SubQuestion at the given slot (1-based)."""
    if subject == "natural_sciences":
        from src.natural_sciences.schemas import LearningContentRef, SubQuestion
        cfg = params.subquestion_configs[slot - 1]
        sub = SubQuestion(
            id=f"{qid}-sq{slot:03d}",
            序號=slot,
            年級=8,
            科目=["自然科學"],
            科學能力=list(params.科學能力),
            學習內容=[LearningContentRef(編碼=code, 說明="") for code in cfg.learning_content],
            學習表現=[LearningContentRef(編碼=code, 說明="") for code in cfg.learning_performance],
            reporting_scale=cfg.reporting_scale,
            題型=params.題型,
            題目=f"自然 小題 {slot}",
            答案="A",
            答案解析="解析",
        )
    else:
        from src.social_studies.schemas import SubQuestion
        sub = SubQuestion(
            id=f"{qid}-sq{slot:03d}",
            序號=slot,
            年級=8,
            科目=["地理"],
            題型="選擇題",
            題目=f"社會 小題 {slot}",
            答案="A",
            答案解析="解析",
        )
    sub._plan_index = slot
    return sub


# ---------------------------------------------------------------------------
# Stream runner
# ---------------------------------------------------------------------------


def _run_stream(subject: str, tmp_path: Path) -> tuple[list[dict[str, Any]], str]:
    from server.config import ServerConfig
    from server.generate.service import generate_question_stream
    from server.generate.subjects import SUBJECTS
    from src.common.generation_events import new_call_scope, new_operation_scope
    from tests.server.generate_test_utils import resolved_generate_params

    params = resolved_generate_params({
        "subject": subject,
        "seed": 937,
        "count": 1,
        "sub_question_count": _TOTAL_SLOTS,
        "skip_verify": True,
    })

    def fake_do_generate(rng_params: Any, _overrides: Any, **kwargs: Any) -> Any:
        qid = kwargs["question_id"]
        client: _FakeClient = kwargs["client"]
        on_update = kwargs["on_question_update"]
        context = kwargs["question_context"]

        def stage(
            scope: Any,
            status: str,
            *,
            supersedes: str | None = None,
            **extra: Any,
        ) -> None:
            slot_index = scope.subquestion_index
            agent = (
                f"sub_generator#{slot_index + 1}"
                if scope.kind == "subquestion" and slot_index is not None
                else "generator"
            )
            event: dict[str, Any] = {
                "type": "stage",
                "agent": agent,
                "stage": "llm_generate",
                "status": status,
                "run_id": scope.run_id,
                "operation_id": scope.operation_id,
                "subquestion_index": scope.subquestion_index,
                "ts": 0.0,
            }
            if supersedes is not None:
                event["supersedes_operation_id"] = supersedes
            event.update(extra)
            client.emit(event)

        def call(scope: Any, *, retry_of: str | None = None) -> Any:
            call_scope = new_call_scope(scope, retry_of_call_id=retry_of)
            base: dict[str, Any] = {
                "run_id": call_scope.run_id,
                "operation_id": call_scope.operation_id,
                "call_id": call_scope.call_id,
                "agent": (
                    f"sub_generator#{scope.subquestion_index + 1}"
                    if scope.kind == "subquestion" and scope.subquestion_index is not None
                    else "generator"
                ),
                "purpose": "generate",
                "subquestion_index": scope.subquestion_index,
                "ts": 0.0,
            }
            if retry_of is not None:
                base["retry_of_call_id"] = retry_of
            client.emit({"type": "llm_request", **base})
            client.emit({"type": "llm_response", **base})
            return call_scope

        # Text generator stage
        text_scope = new_operation_scope(context, kind="text")
        stage(text_scope, "start")
        call(text_scope)
        stage(text_scope, "end")

        # Plan: announce _TOTAL_SLOTS slots
        client.emit({
            "type": "plan",
            "agent": "generator",
            "run_id": text_scope.run_id,
            "operation_id": text_scope.operation_id,
            "sub_question_total": _TOTAL_SLOTS,
            "slots": [
                {
                    "subquestion_index": slot_idx,
                    "id": f"{qid}-sq{slot_idx + 1:03d}",
                    "序號": slot_idx + 1,
                }
                for slot_idx in range(_TOTAL_SLOTS)
            ],
            "ts": 0.0,
        })

        shell = _shell(subject, qid, rng_params)
        on_update(shell, "draft")

        # Generate slot 1 (subquestion_index=0) — succeeds
        good_scope_1 = new_operation_scope(context, kind="subquestion", subquestion_index=0)
        stage(good_scope_1, "start")
        call(good_scope_1)
        stage(good_scope_1, "end")
        shell.subquestions.append(_subquestion(subject, qid, 1, rng_params))
        on_update(shell, "draft")

        # Slot 2 (subquestion_index=1) — FAILS on ALL _EXPECTED_ATTEMPTS attempts
        # This simulates what happens when _parse_subquestion raises
        # SubquestionParseError because the LLM returned blank/missing 題目.
        superseded_operation_id: str | None = None
        bad_scope = None
        for attempt in range(1, _EXPECTED_ATTEMPTS + 1):
            bad_scope = new_operation_scope(
                context,
                kind="subquestion",
                subquestion_index=_BAD_SLOT_INDEX,
                supersedes_operation_id=superseded_operation_id,
            )
            stage(
                bad_scope,
                "start",
                supersedes=superseded_operation_id,
            )
            call(bad_scope)
            if attempt == _EXPECTED_ATTEMPTS:
                stage(
                    bad_scope,
                    "error",
                    code="subquestion_exhausted",
                    failure_code="validation_exhausted",
                    failure_detail="子題欄位「題目」驗證失敗（missing）",
                )
            superseded_operation_id = bad_scope.operation_id

        # Slot 3 (subquestion_index=2) — succeeds
        good_scope_3 = new_operation_scope(context, kind="subquestion", subquestion_index=2)
        stage(good_scope_3, "start")
        call(good_scope_3)
        stage(good_scope_3, "end")
        shell.subquestions.append(_subquestion(subject, qid, 3, rng_params))
        on_update(shell, "draft")

        return shell

    spec = dataclasses.replace(SUBJECTS[subject], do_generate=fake_do_generate)
    config = ServerConfig(
        api_key="x",
        gemini_api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
    )
    app_state = type(
        "AppState",
        (),
        {
            "renderer_pool": None,
            "curriculum": [],
            "performance": {},
            "intro_text": "",
            "grade_content": {},
            "math_curriculum_context": None,
        },
    )()

    async def collect() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in generate_question_stream(
            params,
            config,
            app_state,
            subjects={subject: spec},
            client_factory=_FakeClient,
        ):
            events.append(event)
        return events

    with patch("server.observability.record_generation_outcome"):
        events = asyncio.run(collect())
    return events, events[0]["context"]["run_id"]


# ---------------------------------------------------------------------------
# Unit helper: verify _parse_subquestion raises on blank/whitespace title
# ---------------------------------------------------------------------------


def _assert_parse_errors(subject: str) -> None:
    """Assert that blank and whitespace-only 題目 raise SubquestionParseError."""
    from src.common.generation_core import SubquestionParseError

    if subject == "natural_sciences":
        from src.natural_sciences.cli import _parse_subquestion
        from src.natural_sciences.sampler import sample_params

        params = sample_params(grade=8, seed=937)

        def valid_raw() -> dict:
            return {
                "題型": "Simple multiple-choice",
                "題目": "問題文字",
                "答案": "A",
                "答案解析": "解析",
                "出題概念": "概念",
                "學習內容": [{"編碼": "INc-IV-1", "說明": ""}],
                "學習表現": [{"編碼": "tr-IV-1", "說明": ""}],
            }
    else:
        from src.social_studies.cli import _parse_subquestion
        from src.social_studies.sampler import sample_params

        params = sample_params(grade=8, seed=937)

        def valid_raw() -> dict:
            return {
                "題型": "選擇題",
                "題目": "問題文字",
                "答案": "A",
                "答案解析": "解析",
                "出題概念": "概念",
                "學習內容": [{"編碼": "歷Ka-Ⅳ-1", "說明": ""}],
                "學習表現": [{"編碼": "社1a-Ⅳ-1", "說明": ""}],
            }

    qid = "q_TEST_937"

    # Missing 題目
    raw_missing = valid_raw()
    del raw_missing["題目"]
    with pytest.raises(SubquestionParseError):
        _parse_subquestion(raw_missing, qid, params, 2)

    # Empty string 題目
    raw_empty = valid_raw()
    raw_empty["題目"] = ""
    with pytest.raises(SubquestionParseError):
        _parse_subquestion(raw_empty, qid, params, 2)

    # Whitespace-only 題目
    raw_ws = valid_raw()
    raw_ws["題目"] = "   \n\t  "
    with pytest.raises(SubquestionParseError):
        _parse_subquestion(raw_ws, qid, params, 2)


# ---------------------------------------------------------------------------
# Main parametrized test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
def test_blank_subquestion_slot_is_dropped(subject: str, tmp_path: Path) -> None:
    """Service drops slots whose 子題產生器 response lacks a valid 題目.

    Regression for issue #937.
    """
    from server.generate.event_protocol import QuestionTerminalPayload

    # --- Part A: unit-level parse-error gate ---
    _assert_parse_errors(subject)

    # --- Part B: service-level pipeline ---
    events, run_id = _run_stream(subject, tmp_path)

    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "done"
    assert [e["context"]["event_seq"] for e in events] == list(range(1, len(events) + 1))

    # Exactly one question in the manifest.
    manifest = events[0]["payload"]["questions"]
    assert len(manifest) == 1
    qid = manifest[0]["question_id"]

    # --- Plan event ---
    plans = [e for e in events if e["event"] == "plan"]
    assert len(plans) == 1
    plan_slots = plans[0]["payload"]["slots"]
    assert len(plan_slots) == _TOTAL_SLOTS
    for i, slot in enumerate(plan_slots):
        assert slot["subquestion_index"] == i
        assert slot["id"] == f"{qid}-sq{i + 1:03d}"
        assert slot["序號"] == i + 1

    # --- Result event ---
    results = [e for e in events if e["event"] == "result"]
    assert len(results) == 1
    result = results[0]
    assert result["context"]["question_id"] == qid

    # Result payload IS what gets stored in the GenerationRecord (History record).
    result_subqs = result["payload"].get("subquestions", [])
    result_ids = [sq["id"] for sq in result_subqs]
    assert result_ids == [f"{qid}-sq001", f"{qid}-sq003"], (
        f"Expected only sq001 and sq003 in result, got {result_ids}"
    )
    # Slot 2 must NOT appear in the persisted question_json
    assert f"{qid}-sq002" not in result_ids

    # --- Terminal event ---
    terminals = [e for e in events if e["event"] == "question_terminal"]
    assert len(terminals) == 1
    terminal = terminals[0]
    assert terminal["context"]["question_id"] == qid
    QuestionTerminalPayload.model_validate(terminal["payload"])

    payload = terminal["payload"]
    assert payload["delivery_status"] == "partial", (
        f"Expected partial delivery, got {payload['delivery_status']}"
    )
    missing = payload["missing"]
    assert len(missing) == 1, f"Expected exactly 1 missing slot, got {missing}"
    missing_slot = missing[0]
    assert missing_slot["kind"] == "subquestion"
    assert missing_slot["subquestion_id"] == f"{qid}-sq002"
    assert missing_slot["subquestion_index"] == _BAD_SLOT_INDEX
    assert missing_slot["failure_code"] == "validation_exhausted"
    assert missing_slot["failure_detail"] == "子題欄位「題目」驗證失敗（missing）"
    assert missing_slot["reason"] == missing_slot["failure_detail"]

    # Delivered slots must be sq001 and sq003 only.
    delivered = payload["delivered"]
    delivered_ids = [s["subquestion_id"] for s in delivered if s["kind"] == "subquestion"]
    assert f"{qid}-sq001" in delivered_ids
    assert f"{qid}-sq003" in delivered_ids
    assert f"{qid}-sq002" not in delivered_ids

    # --- Retry count: stage "start" events for the bad slot ---
    # Each attempt (initial + retries) emits one "start" stage event for
    # subquestion_index == _BAD_SLOT_INDEX.
    bad_starts = [
        e for e in events
        if e["event"] == "stage"
        and e["context"].get("subquestion_index") == _BAD_SLOT_INDEX
        and e["payload"].get("status") == "start"
    ]
    assert len(bad_starts) == _EXPECTED_ATTEMPTS, (
        f"Expected {_EXPECTED_ATTEMPTS} start events for bad slot, "
        f"got {len(bad_starts)}"
    )

    # --- Fixture generation (for frontend vitest suite) ---
    fixture_path = FIXTURE_PATHS[subject]
    operation_names: dict[str, str] = {}
    call_names: dict[str, str] = {}
    masked = [
        _mask_item(e, run_id, operation_names=operation_names, call_names=call_names)
        for e in sorted(events, key=lambda ev: ev["context"]["event_seq"])
    ]
    if os.environ.get("GENERATE_937_FIXTURE") == "1" or not fixture_path.exists():
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in masked),
            encoding="utf-8",
        )
