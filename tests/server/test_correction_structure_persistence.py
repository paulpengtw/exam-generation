"""The generation boundary preserves a 題組 through correction and persistence."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from tests.server.test_generate_body_transport import transport_client  # noqa: F401


def _stream_events(response: Any) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for frame in response.text.replace("\r\n", "\n").split("\n\n"):
        fields = {
            key: value
            for line in frame.splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
        if "event" in fields:
            raw_data = fields.get("data", "").strip() or "{}"
            events.append((fields["event"].strip(), json.loads(raw_data)))
    return events


class _CorrectionProvider:
    """Deterministic OpenAI-compatible responses for one real subject pipeline."""

    def __init__(
        self, corrections: Sequence[str] | str, subject: str = "social_studies",
        *, marker: str = "", generator_barrier: threading.Barrier | None = None,
    ) -> None:
        self.subject = subject
        self.marker = marker
        self.generator_barrier = generator_barrier
        self.question_type = "Simple multiple-choice" if subject == "natural_sciences" else "選擇題"
        self._lock = threading.Lock()
        self._corrections = (
            [corrections] if isinstance(corrections, str) else list(corrections)
        )
        assert self._corrections
        self._correction_calls = 0
        self._last_correction: str | None = None
        self._verification_calls = 0
        self.calls: list[str] = []

    def __call__(self, **kwargs: Any):
        user_content = kwargs["messages"][-1]["content"]
        assert isinstance(user_content, str)

        if "## 原始題目（JSON）" in user_content:
            stage = "corrector"
            with self._lock:
                correction_index = self._correction_calls
                self._correction_calls += 1
                correction = self._corrections[
                    min(correction_index, len(self._corrections) - 1)
                ]
                self._last_correction = correction
            indexes = (1, 2, 3, 4) if correction.startswith("short") else range(1, 6)
            payload = {
                "文本": (
                    "原始共享文本"
                    if correction == "valid"
                    else "不應發布的修正共享文本"
                ),
                "subquestions": [
                    {
                        "id": f"original-{index}",
                        "序號": index,
                        "題型": self.question_type,
                        "年級": 99,
                        "學習內容": [],
                        "學習表現": [],
                        "出題指示": "不應改變的出題指示",
                        "題目": (
                            f"有效修正第{index}小題"
                            if correction == "valid" and index == 3
                            else (
                                f"原始第{index}小題"
                                if correction == "valid"
                                else f"錯誤修正第{index}小題"
                            )
                        ),
                        "答案": (
                            "B" if correction == "valid" and index == 3 else "A"
                        ),
                        "答案解析": (
                            "有效修正解析"
                            if correction == "valid" and index == 3
                            else (
                                f"原始第{index}小題解析"
                                if correction == "valid"
                                else "不應發布的修正解析"
                            )
                        ),
                        "評分規準": [],
                    }
                    for index in indexes
                ],
            }
            if correction.startswith("short"):
                payload["chart_spec"] = {
                    "render_mode": "gpt_image",
                    "description": "DISCARDED_CORRECTION_FIGURE",
                    "figure_kind": "bar chart",
                }
        elif "## 本小題規劃" in user_content:
            ordinal_match = re.search(
                r"\*\*序號\*\*：(?:第\s*)?(\d+)", user_content
            )
            assert ordinal_match, user_content
            index = int(ordinal_match.group(1))
            stage = f"sub_generator#{index}"
            payload = {
                "id": f"original-{index}",
                "序號": index,
                "題型": self.question_type,
                "題目": f"原始第{index}小題",
                "答案": "A",
                "答案解析": f"原始第{index}小題解析",
                "評分規準": [],
                "誘答分析": {},
            }
        elif any(marker in user_content for marker in (
            "請審核以下社會領域素養導向題組",
            "請審核以下 PISA Science + 108課綱自然科學題組",
            "請審核以下考試題目",
        )):
            stage = "verifier"
            with self._lock:
                self._verification_calls += 1
                passed = (
                    self._verification_calls > 1
                    and self._last_correction in {"valid", "short-pass"}
                )
            payload = {
                "passed": passed,
                "answer_match": passed,
                "details": (
                    "修正後題組通過自主驗證。"
                    if passed
                    else "原始題組的第三小題答案需要修正。"
                ),
                "my_answer": "A" if passed else "B",
                "provided_answer": "A",
            }
        else:
            stage = "generator"
            payload = {
                "核心問題": f"{self.marker}原始核心問題",
                "文本": "原始共享文本",
                "取材來源": ["controlled fixture"],
                "subquestions": [
                    {"序號": index, "出題概念": f"概念{index}"}
                    for index in range(1, 6)
                ],
            }
            if self.generator_barrier is not None:
                self.generator_barrier.wait(timeout=20)

        with self._lock:
            self.calls.append(stage)
        content = json.dumps(payload, ensure_ascii=False)
        return iter(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
                )
            ]
        )


def _resolved_payload(
    client: Any, *, max_retries: int = 1, subject: str = "social_studies",
    count: int = 1,
) -> dict[str, Any]:
    if subject == "math":
        # The isolated HTTP fixture omits process startup/migrations. Populate
        # its math corpus with the same real loaders used by app startup.
        from src.curriculum_context import load_curriculum_context
        from src.data_loader import (
            get_grade_content,
            load_curriculum,
            load_intro_text,
            load_performance_standards,
        )
        from src.schema_loader import load_grades, load_schemas

        state = client.app.state
        state.curriculum = load_curriculum(Path("data/curriculum/學習內容.json"))
        state.performance = load_performance_standards(Path("data/curriculum/學習表現.json"))
        state.intro_text = load_intro_text(Path('Introduction to "學習表現" and "學習階段".md'))
        state.grade_content = {
            grade: get_grade_content(state.curriculum, grade)
            for grade in load_grades(load_schemas())
        }
        state.math_curriculum_context = load_curriculum_context()
    subject_pins = {
        "social_studies": {
            "context": ["個人"],
            "subject_filter": ["地理"],
            "learning_content": ["地Ac-Ⅳ-1"],
            "learning_performance": ["社3b-Ⅳ-2"],
            "core_competency": ["社-J-B1"],
        },
        "natural_sciences": {
            "context": ["Local and national"],
            "sub_context": "Environmental impact",
            "learning_content": ["Ab-Ⅳ-2"],
            "learning_performance": ["tr-Ⅳ-1"],
        },
        "math": {
            "context": ["個人"],
            "subject_filter": ["數與量"],
            "learning_content": ["N-7-1"],
            "learning_performance": ["n-IV-1"],
            "core_competency": ["數-J-A1"],
        },
    }[subject]
    if subject != "math":
        question_type = "Simple multiple-choice" if subject == "natural_sciences" else "選擇題"
        subject_pins["subquestion_configs"] = json.dumps([
            {
                "question_type": question_type,
                "instruction": f"請保留第{index}小題的身份。",
                "content_type": "純文字",
                "image_generation_mode": "html",
                **({"reporting_scale": "3"} if subject == "natural_sciences" else {}),
            }
            for index in range(1, 6)
        ], ensure_ascii=False)
    response = client.post(
        "/api/generate/resolve",
        json={
            "subject": subject,
            "seed": 401183334,
            "count": count,
            "grade": 8,
            "set_type": "題組題",
            "content_type": "純文字",
            **subject_pins,
            "sub_question_count": 5,
            "disable_reference_fewshot": True,
            "skip_verify": False,
            "max_retries": max_retries,
            "model_execute": "gpt-4.1",
            "model_verify": "gpt-4.1",
            "model_correct": "gpt-4.1",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    payload = body["payload"]
    payload["drawn"] = body["drawn"]
    configs = payload.get("subquestion_configs")
    if isinstance(configs, list):
        payload["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)
    rows = payload.get("per_question_params")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row.get("subquestion_configs"), list):
                row["subquestion_configs"] = json.dumps(
                    row["subquestion_configs"], ensure_ascii=False,
                )
        payload["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    return payload


def _without_verdict(question: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in question.items() if key != "verification"}


def _content_for_compare(question: dict[str, Any]) -> dict[str, Any]:
    content = _without_verdict(question)
    metadata = content.get("metadata")
    if isinstance(metadata, dict):
        metadata = dict(metadata)
        metadata.pop("coverage_mode_used", None)
        metadata.pop("surface_used", None)
        # NS adds this aggregate after the shared core's final update/trail.
        # Its fixed request value is asserted on terminal and saved results.
        metadata.pop("reporting_scales", None)
        content["metadata"] = metadata
    return content


def _without_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_nulls(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_without_nulls(item) for item in value]
    return value


def _assert_content_matches(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    allowed_differences: set[str] | None = None,
) -> None:
    expected_content = _content_for_compare(expected)
    actual_content = _content_for_compare(actual)
    differences = {
        key
        for key in set(expected_content) | set(actual_content)
        if expected_content.get(key) != actual_content.get(key)
    }
    assert differences <= (allowed_differences or set()), differences


def _exchanges_for_detail(
    client: Any, detail_body: dict[str, Any]
) -> list[dict[str, Any]]:
    log_id = detail_body["generation_log_id"]
    assert log_id
    response = client.get(f"/api/generation-logs/{log_id}/exchanges")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize(
    ("corrections", "max_retries", "expected_success", "expected_rejections"),
    [
        pytest.param(["short"], 1, False, 1, id="one-rejected-attempt"),
        pytest.param(["short", "short"], 2, False, 2, id="repeated-rejected-attempts"),
        pytest.param(["valid"], 1, True, 0, id="valid-on-first-attempt"),
        pytest.param(["short", "valid"], 2, True, 1, id="rejected-then-valid"),
        pytest.param(["short-pass"], 1, True, 1, id="retained-content-passes"),
    ],
)
def test_correction_structure_persists_through_sse_history_and_log(
    transport_client: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    corrections: list[str],
    max_retries: int,
    expected_success: bool,
    expected_rejections: int,
    subject: str,
) -> None:
    provider = _CorrectionProvider(corrections, subject)
    monkeypatch.setattr(
        "openai.resources.chat.completions.Completions.create", provider
    )
    payload = _resolved_payload(transport_client, max_retries=max_retries, subject=subject)

    response = transport_client.post("/api/generate", json=payload)
    assert response.status_code == 200, response.text[:1000]
    events = _stream_events(response)

    updates = [data for name, data in events if name == "question_update"]
    expected_phases = ["draft", "verified"]
    for correction in corrections:
        if correction == "valid":
            expected_phases.append("corrected")
        expected_phases.append("verified")
    assert [data["phase"] for data in updates] == expected_phases
    draft_content = updates[0]["question"]
    verified_updates = [data for data in updates if data["phase"] == "verified"]
    assert len(verified_updates) == 1 + len(corrections)
    initial_content = verified_updates[0]["question"]
    final_content = verified_updates[-1]["question"]
    _assert_content_matches(
        initial_content,
        draft_content,
        allowed_differences={"內容領域", "認知歷程"},
    )
    for data in updates:
        if data["phase"] == "corrected":
            continue
        if expected_success and data["question"] is final_content:
            continue
        _assert_content_matches(
            initial_content,
            data["question"],
            allowed_differences=(
                {"內容領域", "認知歷程"} if data["phase"] == "draft" else set()
            ),
        )
    assert len(initial_content["subquestions"]) == 5
    assert initial_content["文本"] == "原始共享文本"

    accepted = "valid" in corrections
    if accepted:
        corrected_updates = [data for data in updates if data["phase"] == "corrected"]
        assert len(corrected_updates) == 1
        corrected_content = corrected_updates[0]["question"]
        _assert_content_matches(corrected_content, final_content)
        assert initial_content["verification"]["passed"] is False
        assert "verification" not in corrected_content
        assert final_content["verification"]["passed"] is True
        assert initial_content["文本"] == corrected_content["文本"]
        assert [
            (subquestion["id"], subquestion["序號"])
            for subquestion in initial_content["subquestions"]
        ] == [
            (subquestion["id"], subquestion["序號"])
            for subquestion in corrected_content["subquestions"]
        ]
        assert corrected_content["subquestions"][2]["題目"] == "有效修正第3小題"
        assert corrected_content["subquestions"][2]["答案"] == "B"
        assert corrected_content["subquestions"][2] == {
            **initial_content["subquestions"][2],
            "題目": "有效修正第3小題",
            "答案": "B",
            "答案解析": "有效修正解析",
        }
        for index in (0, 1, 3, 4):
            assert (
                corrected_content["subquestions"][index]
                == initial_content["subquestions"][index]
            )
        expected_content = corrected_content
    else:
        assert [
            data["question"] for data in updates if data["phase"] == "corrected"
        ] == []
        assert final_content["verification"]["passed"] is expected_success
        expected_content = initial_content

    subquestion_ordinals = sorted(
        int(data.removeprefix("sub_generator#"))
        for data in provider.calls
        if data.startswith("sub_generator#")
    )
    assert subquestion_ordinals == [1, 2, 3, 4, 5]
    assert initial_content["verification"]["passed"] is False

    result_events = [data for name, data in events if name == "result"]
    assert len(result_events) == 1
    result = result_events[0]
    _assert_content_matches(expected_content, result)
    assert result["verification"]["passed"] is expected_success
    if subject == "natural_sciences":
        assert result["metadata"]["reporting_scales"] == ["3", "3", "3", "3", "3"]

    trail_events = [data for name, data in events if name == "trail"]
    verification_entries = [
        entry for entry in trail_events if entry.get("kind") == "verification"
    ]
    correction_entries = [
        entry for entry in trail_events if entry.get("kind") == "correction"
    ]
    initial_entries = [
        entry for entry in trail_events if entry.get("kind") == "initial"
    ]
    assert [entry["passed"] for entry in verification_entries] == (
        [False] + [correction in {"valid", "short-pass"} for correction in corrections]
    )
    assert len(initial_entries) == 1
    assert [entry["outcome"] for entry in correction_entries] == [
        "accepted" if correction == "valid" else "rejected" for correction in corrections
    ]
    assert [entry["retry_index"] for entry in correction_entries] == list(
        range(1, len(corrections) + 1)
    )
    for entry in correction_entries:
        if entry["outcome"] == "rejected":
            assert set(entry["reason"]) == {"code", "path", "message"}
            assert entry["reason"]["path"] == "subquestions"
            assert entry["reason"]["message"]
            assert _without_nulls(entry["snapshot"]) == _without_nulls(
                _without_verdict(initial_content)
            )
        else:
            assert "reason" not in entry
    assert _without_nulls(initial_entries[0]["snapshot"]) == _without_nulls(
        _without_verdict(initial_content)
    )
    if expected_success:
        assert _without_nulls(correction_entries[-1]["snapshot"]) == _without_nulls(
            _without_verdict(expected_content)
        )
    else:
        assert not any(
            entry.get("kind") == "verification" and entry.get("passed") is True
            for entry in trail_events
        )

    diagnostics = [
        data
        for name, data in events
        if name == "stage"
        and data.get("agent") == "corrector"
        and data.get("stage") == "correct"
        and data.get("status") == "error"
    ]
    assert len(diagnostics) == expected_rejections
    assert [diagnostic["retry"] for diagnostic in diagnostics] == list(
        range(1, expected_rejections + 1)
    )
    assert all(diagnostic["code"] == "correction_rejected" for diagnostic in diagnostics)
    assert all(diagnostic["question_id"] == result["id"] for diagnostic in diagnostics)
    assert all(diagnostic.get("message") for diagnostic in diagnostics)
    assert all(
        "小題" in diagnostic["message"]
        or "subquestion" in diagnostic["message"].lower()
        for diagnostic in diagnostics
    )
    completed_corrections = [
        data
        for name, data in events
        if name == "stage" and data.get("agent") == "corrector"
        and data.get("stage") == "correct" and data.get("status") == "end"
    ]
    assert [data["retry"] for data in completed_corrections] == (
        [len(corrections)] if accepted else []
    )
    assert not any(
        name == "stage" and data.get("agent") == "image_agent"
        for name, data in events
    )
    assert "DISCARDED_CORRECTION_FIGURE" not in json.dumps(
        [updates, result, trail_events], ensure_ascii=False,
    )

    history = transport_client.get("/api/history")
    assert history.status_code == 200
    assert history.json()["total"] == 1
    record_id = history.json()["items"][0]["id"]
    detail = transport_client.get(f"/api/history/{record_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    saved = detail_body["question_json"]
    _assert_content_matches(expected_content, saved)
    assert len(saved["subquestions"]) == 5
    assert saved["文本"] == "原始共享文本"
    assert saved["verification"]["passed"] is expected_success
    if subject == "natural_sciences":
        assert saved["metadata"]["reporting_scales"] == ["3", "3", "3", "3", "3"]
    assert detail_body["verification_trail"] == trail_events
    if not expected_success:
        assert not any(
            entry.get("outcome") == "accepted"
            or (entry.get("kind") == "verification" and entry.get("passed") is True)
            for entry in detail_body["verification_trail"]
        )

    exchanges = _exchanges_for_detail(transport_client, detail_body)
    correction_exchanges = [
        row for row in exchanges if row["purpose"] == "correct"
    ]
    assert len(correction_exchanges) == len(corrections)
    assert len([row for row in exchanges if row["purpose"] == "verify"]) == (
        1 + len(corrections)
    )
    if accepted:
        assert "有效修正第3小題" in correction_exchanges[-1]["response_body"]["content"]
    else:
        assert all(
            "不應發布的修正共享文本" in row["response_body"]["content"]
            for row in correction_exchanges
        )
    if len(corrections) > 1:
        assert (
            "不應發布的修正共享文本"
            in correction_exchanges[0]["response_body"]["content"]
        )
    assert provider.calls.count("corrector") == len(corrections)
    assert provider.calls.count("verifier") == 1 + len(corrections)


def test_concurrent_questions_keep_correction_decisions_and_history_isolated(
    transport_client: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = threading.Barrier(2)
    providers = {
        "REJECT_GROUP": _CorrectionProvider(
            "short", marker="REJECT_GROUP", generator_barrier=barrier,
        ),
        "ACCEPT_GROUP": _CorrectionProvider(
            "valid", marker="ACCEPT_GROUP", generator_barrier=barrier,
        ),
    }

    def provider(_sdk_resource: Any, **kwargs: Any):
        prompt = kwargs["messages"][-1]["content"]
        matches = [marker for marker in providers if marker in prompt]
        assert len(matches) == 1, "Every concurrent provider call must identify its question"
        return providers[matches[0]](**kwargs)

    monkeypatch.setattr("openai.resources.chat.completions.Completions.create", provider)
    payload = _resolved_payload(transport_client, count=2)
    rows = json.loads(payload["per_question_params"])
    for row, marker in zip(rows, providers):
        row["text_instruction"] = marker
    payload["per_question_params"] = json.dumps(rows, ensure_ascii=False)

    response = transport_client.post("/api/generate", json=payload)
    assert response.status_code == 200, response.text
    events = _stream_events(response)
    results = [data for name, data in events if name == "result"]
    assert len(results) == 2
    by_marker = {
        marker: next(result for result in results if marker in result["核心問題"])
        for marker in providers
    }
    rejected = by_marker["REJECT_GROUP"]
    accepted = by_marker["ACCEPT_GROUP"]
    assert rejected["id"] != accepted["id"]
    assert rejected["verification"]["passed"] is False
    assert accepted["verification"]["passed"] is True
    assert rejected["subquestions"][2]["答案"] == "A"
    assert accepted["subquestions"][2]["答案"] == "B"

    for marker, outcome in (("REJECT_GROUP", "rejected"), ("ACCEPT_GROUP", "accepted")):
        result = by_marker[marker]
        question_id = result["id"]
        updates = [
            data for name, data in events
            if name == "question_update" and data["question"]["id"] == question_id
        ]
        assert [update["phase"] for update in updates] == (
            ["draft", "verified", "verified"] if outcome == "rejected"
            else ["draft", "verified", "corrected", "verified"]
        )
        entries = [
            data for name, data in events
            if name == "trail" and data["question_id"] == question_id
        ]
        correction = next(entry for entry in entries if entry["kind"] == "correction")
        assert correction["outcome"] == outcome
        assert correction["retry_index"] == 1
        assert marker in correction["snapshot"]["核心問題"]
        if outcome == "rejected":
            assert correction["reason"]["code"] == "subquestions_count"
            assert _without_nulls(correction["snapshot"]) == _without_nulls(
                _without_verdict(updates[1]["question"])
            )
        else:
            assert "reason" not in correction
        assert providers[marker].calls.count("corrector") == 1
        assert providers[marker].calls.count("verifier") == 2

    stages = [
        data for name, data in events
        if name == "stage" and data.get("stage") == "correct"
    ]
    assert len(stages) == 4
    assert {(stage["question_id"], stage["status"], stage["retry"]) for stage in stages} == {
        (rejected["id"], "start", 1), (rejected["id"], "error", 1),
        (accepted["id"], "start", 1), (accepted["id"], "end", 1),
    }
    assert not any(
        name == "stage" and data.get("agent") == "image_agent"
        for name, data in events
    )

    history = transport_client.get("/api/history").json()
    assert history["total"] == 2
    for row in history["items"]:
        detail_response = transport_client.get(f"/api/history/{row['id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        saved = detail["question_json"]
        result = next(result for result in results if result["id"] == saved["id"])
        _assert_content_matches(result, saved)
        assert saved["verification"] == result["verification"]
        assert detail["verification_trail"] == [
            data for name, data in events
            if name == "trail" and data["question_id"] == saved["id"]
        ]
