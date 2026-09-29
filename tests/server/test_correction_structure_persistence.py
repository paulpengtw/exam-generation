"""The generation boundary preserves a 題組 through correction and persistence."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.auth.dependencies import get_config
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
            data = json.loads(raw_data)
            if isinstance(data, dict) and "context" in data and "payload" in data:
                # The merged stream protocol wraps every v2 event. Keep the
                # assertions below focused on the event payload while exposing
                # question-scoped context fields (for example question_id).
                context = data["context"]
                payload = data["payload"]
                if isinstance(context, dict) and isinstance(payload, dict):
                    data = payload
                    if fields["event"].strip() in {"stage", "trail"}:
                        data = {
                            **payload,
                            **(
                                {"question_id": context["question_id"]}
                                if "question_id" in context
                                else {}
                            ),
                        }
            events.append((fields["event"].strip(), data))
    return events


def _stream_events_full(
    response: Any,
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Return ``(event_name, context, payload)`` triples for every v2 envelope.

    Unlike ``_stream_events``, the context dict is preserved unmodified so
    callers can read per-event fields such as ``content_revision`` that live in
    the context rather than the payload (e.g. ``question_update``, ``result``).
    Non-envelope frames are skipped.
    """
    result: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for frame in response.text.replace("\r\n", "\n").split("\n\n"):
        fields = {
            key: value
            for line in frame.splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
        if "event" not in fields:
            continue
        raw_data = fields.get("data", "").strip() or "{}"
        data = json.loads(raw_data)
        if (
            isinstance(data, dict)
            and "context" in data
            and "payload" in data
            and isinstance(data["context"], dict)
            and isinstance(data["payload"], dict)
        ):
            result.append(
                (fields["event"].strip(), data["context"], data["payload"])
            )
    return result


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
    payload["stream_version"] = 3
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


def _execute_run(client: Any) -> None:
    """Claim and execute one queued run using the transport_client's session factory."""
    from server.generate.run import claim_next_run, execute_run

    sessions = client.app.state.test_async_session_local
    config = client.app.dependency_overrides[get_config]()
    app_state = client.app.state

    async def _run() -> None:
        claimed = await claim_next_run(sessions, host_id="test-host")
        if claimed is not None:
            await execute_run(
                claimed, app_state=app_state, config=config,
                session_factory=sessions, host_id="test-host",
            )

    asyncio.run(_run())


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
    assert response.status_code == 202, response.text[:1000]
    _execute_run(transport_client)

    # --- Read DB state ---
    history = transport_client.get("/api/history")
    assert history.status_code == 200
    assert history.json()["total"] == 1
    record_id = history.json()["items"][0]["id"]
    detail = transport_client.get(f"/api/history/{record_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    saved = detail_body["question_json"]
    trail_events = detail_body["verification_trail"]

    # --- Derive trail entry groups ---
    verification_entries = [
        entry for entry in trail_events if entry.get("kind") == "verification"
    ]
    correction_entries = [
        entry for entry in trail_events if entry.get("kind") == "correction"
    ]
    initial_entries = [
        entry for entry in trail_events if entry.get("kind") == "initial"
    ]

    assert len(initial_entries) == 1
    initial_snapshot = initial_entries[0]["snapshot"]  # question without verification

    # --- Provider call counts ---
    subquestion_ordinals = sorted(
        int(data.removeprefix("sub_generator#"))
        for data in provider.calls
        if data.startswith("sub_generator#")
    )
    assert subquestion_ordinals == [1, 2, 3, 4, 5]
    # First verification always fails
    assert verification_entries[0]["passed"] is False

    # --- Verify trail structure ---
    assert [entry["passed"] for entry in verification_entries] == (
        [False] + [correction in {"valid", "short-pass"} for correction in corrections]
    )
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
            assert _without_nulls(entry["snapshot"]) == _without_nulls(initial_snapshot)
        else:
            assert "reason" not in entry

    # --- Initial content assertions (via trail snapshot) ---
    assert len(initial_snapshot["subquestions"]) == 5
    assert initial_snapshot["文本"] == "原始共享文本"

    # --- Derive expected content for DB comparison ---
    accepted = "valid" in corrections
    if accepted:
        accepted_entries = [e for e in correction_entries if e.get("outcome") == "accepted"]
        assert len(accepted_entries) == 1
        corrected_snapshot = accepted_entries[0]["snapshot"]
        # Verify correction applied the right change to subquestion 3 (trail snapshot)
        assert corrected_snapshot["subquestions"][2]["題目"] == "有效修正第3小題"
        assert corrected_snapshot["subquestions"][2]["答案"] == "B"
        assert corrected_snapshot["subquestions"][2]["答案解析"] == "有效修正解析"
        # Other subquestions are unaffected (trail snapshot → trail snapshot)
        for index in (0, 1, 3, 4):
            sq_c = corrected_snapshot["subquestions"][index]
            sq_i = initial_snapshot["subquestions"][index]
            assert sq_c["id"] == sq_i["id"]
            assert sq_c["答案"] == sq_i["答案"]
        assert initial_snapshot["文本"] == corrected_snapshot["文本"]
    # else: rejected — no corrected_snapshot assertions needed here

    # --- DB content assertions ---
    # No invalid correction content should appear in the saved question
    assert "不應發布" not in json.dumps(saved, ensure_ascii=False)
    assert len(saved["subquestions"]) == 5
    assert saved["文本"] == "原始共享文本"
    assert saved["verification"]["passed"] is expected_success
    if subject == "natural_sciences":
        assert saved["metadata"]["reporting_scales"] == ["3", "3", "3", "3", "3"]
    if accepted:
        # Accepted correction: subquestion 3 was changed
        assert saved["subquestions"][2]["題目"] == "有效修正第3小題"
        assert saved["subquestions"][2]["答案"] == "B"
        assert saved["subquestions"][2]["答案解析"] == "有效修正解析"
        # Subquestion identity preserved across correction
        for index in (0, 1, 3, 4):
            saved_sq = saved["subquestions"][index]
            assert saved_sq["id"] == initial_snapshot["subquestions"][index]["id"]
            assert saved_sq["答案"] == "A"
    else:
        # Rejected correction: original answers unchanged
        assert saved["subquestions"][2]["答案"] == "A"
        for i, sq in enumerate(saved["subquestions"]):
            assert sq["id"] == initial_snapshot["subquestions"][i]["id"]
    if not expected_success:
        assert not any(
            entry.get("outcome") == "accepted"
            or (entry.get("kind") == "verification" and entry.get("passed") is True)
            for entry in trail_events
        )

    # DISCARDED_CORRECTION_FIGURE must not appear in saved question or trail
    assert "DISCARDED_CORRECTION_FIGURE" not in json.dumps(
        [saved, trail_events], ensure_ascii=False,
    )

    # --- Exchange assertions ---
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
    assert response.status_code == 202, response.text
    _execute_run(transport_client)

    history = transport_client.get("/api/history").json()
    assert history["total"] == 2

    by_marker: dict[str, tuple[dict, dict]] = {}
    for row in history["items"]:
        detail_response = transport_client.get(f"/api/history/{row['id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        saved = detail["question_json"]
        for marker in providers:
            if marker in saved["核心問題"]:
                by_marker[marker] = (saved, detail)
                break

    assert set(by_marker.keys()) == {"REJECT_GROUP", "ACCEPT_GROUP"}, (
        f"Could not find both markers in history; found: {list(by_marker.keys())}"
    )
    rejected_saved, rejected_detail = by_marker["REJECT_GROUP"]
    accepted_saved, accepted_detail = by_marker["ACCEPT_GROUP"]

    assert rejected_saved["id"] != accepted_saved["id"]
    assert rejected_saved["verification"]["passed"] is False
    assert accepted_saved["verification"]["passed"] is True
    assert rejected_saved["subquestions"][2]["答案"] == "A"
    assert accepted_saved["subquestions"][2]["答案"] == "B"

    for marker, outcome, detail_body in (
        ("REJECT_GROUP", "rejected", rejected_detail),
        ("ACCEPT_GROUP", "accepted", accepted_detail),
    ):
        trail = detail_body["verification_trail"]
        correction = next(
            (entry for entry in trail if entry.get("kind") == "correction"), None
        )
        assert correction is not None, f"No correction entry found for {marker}"
        assert correction["outcome"] == outcome
        assert correction["retry_index"] == 1
        assert marker in correction["snapshot"]["核心問題"]
        if outcome == "rejected":
            assert correction["reason"]["code"] == "subquestions_count"
        else:
            assert "reason" not in correction
        assert providers[marker].calls.count("corrector") == 1
        assert providers[marker].calls.count("verifier") == 2


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences", "math"])
@pytest.mark.parametrize(
    ("corrections", "max_retries", "accepted"),
    [
        pytest.param(["valid"], 1, True, id="accepted"),
        pytest.param(["short"], 1, False, id="rejected"),
    ],
)
def test_revision_binding_across_subjects_and_outcomes(
    transport_client: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    corrections: list[str],
    max_retries: int,
    accepted: bool,
    subject: str,
) -> None:
    """#746: content_revision is consistently bound across the stream, trail, and history.

    Assertions (per subject × correction outcome):

    Accepted correction (``corrections=["valid"]``):
    - ``question_update`` context ``content_revision`` values: pre-correction
      verified phase carries R1; the corrected phase carries R2 > R1; the final
      verified phase (after reverification) still carries R2.
    - ``trail`` events: initial and first (failed) verification carry R1;
      the correction entry and the final (passed) verification carry R2.
    - ``question_terminal``: ``final_revision == R2``, ``review.status == 'passed'``,
      ``review.content_revision == R2``.

    Rejected correction (``corrections=["short"]``):
    - No ``corrected`` phase update; both verified phases carry R1.
    - All trail entries carry R1.
    - ``question_terminal``: ``final_revision == R1``, ``review.status == 'failed'``,
      ``review.content_revision == R1``.

    History read-back: ``detail["verification_trail"]`` matches the stream's
    trail events (sibling 歷程讀回指向相同版本).
    """
    provider = _CorrectionProvider(corrections, subject)
    monkeypatch.setattr(
        "openai.resources.chat.completions.Completions.create", provider
    )
    payload = _resolved_payload(transport_client, max_retries=max_retries, subject=subject)

    response = transport_client.post("/api/generate", json=payload)
    assert response.status_code == 202, response.text[:1000]
    _execute_run(transport_client)

    # Read trail from DB
    history = transport_client.get("/api/history")
    assert history.status_code == 200
    record_id = history.json()["items"][0]["id"]
    detail = transport_client.get(f"/api/history/{record_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    trail_events = detail_body["verification_trail"]

    verification_entries = [e for e in trail_events if e.get("kind") == "verification"]
    correction_entries = [e for e in trail_events if e.get("kind") == "correction"]
    initial_entries = [e for e in trail_events if e.get("kind") == "initial"]

    assert len(initial_entries) == 1
    R1 = initial_entries[0].get("content_revision")
    assert isinstance(R1, int) and R1 >= 1, (
        f"[{subject}/{corrections}] initial trail entry content_revision must be "
        f"a positive int, got {R1!r}"
    )
    assert len(verification_entries) >= 1
    assert verification_entries[0].get("content_revision") == R1, (
        f"[{subject}/{corrections}] first verification entry content_revision="
        f"{verification_entries[0].get('content_revision')!r}, expected R1={R1}"
    )

    if accepted:
        assert len(correction_entries) == 1
        R2 = correction_entries[0].get("content_revision")
        assert isinstance(R2, int) and R2 > R1, (
            f"[{subject}/{corrections}] R2={R2!r} must exceed R1={R1}"
        )
        # Reverification entry is at R2 and passed
        assert len(verification_entries) == 2
        assert verification_entries[1].get("content_revision") == R2, (
            f"[{subject}/{corrections}] reverification entry content_revision="
            f"{verification_entries[1].get('content_revision')!r}, expected R2={R2}"
        )
        assert verification_entries[1].get("passed") is True
    else:
        # Rejected correction: all entries remain at R1
        for entry in correction_entries:
            assert entry.get("content_revision") == R1, (
                f"[{subject}/{corrections}] rejected correction entry content_revision="
                f"{entry.get('content_revision')!r}, expected R1={R1}"
            )
        assert verification_entries[-1].get("content_revision") == R1, (
            f"[{subject}/{corrections}] final verification content_revision="
            f"{verification_entries[-1].get('content_revision')!r}, expected R1={R1}"
        )
        assert verification_entries[-1].get("passed") is False

    # Sibling 歷程讀回: trail is consistently stored in DB
    assert detail_body["verification_trail"] == trail_events
