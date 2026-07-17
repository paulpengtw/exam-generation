"""Tests for src.common.planner.plan_context_angles (issue #114)."""

from __future__ import annotations

import json

from src.common.planner import plan_context_angles
from src.social_studies.schemas import CreativeBrief

_SYSTEM = "test-system-prompt (n={n})"
_USER = (
    "contexts={contexts}\n"
    "count={count}\n"
    "learning_content={learning_content}\n"
    "core_question={core_question}"
)


class _StubClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[tuple[str, str, str]] = []

    def plan(self, system: str, user: str, purpose: str = "plan") -> str:
        self.calls.append((system, user, purpose))
        return self._response


def test_parses_n_briefs_and_returns_exact_count() -> None:
    payload = json.dumps([
        {"selected_context": "個人", "題材_angle": "居家防疫日記", "framing_hooks": ["日記"]},
        {"selected_context": "公共", "題材_angle": "市議會質詢", "framing_hooks": ["質詢紀錄"]},
        {"selected_context": "職業", "題材_angle": "護理排班表", "framing_hooks": ["排班表"]},
    ])
    client = _StubClient(payload)
    briefs = plan_context_angles(
        client,
        count=3,
        sampled_contexts=["個人", "公共", "職業"],
        learning_content_pool=["歷Ka-Ⅳ-1"],
        core_question=None,
        system_prompt=_SYSTEM,
        user_prompt_template=_USER,
    )
    assert len(briefs) == 3
    assert all(isinstance(b, CreativeBrief) for b in briefs)
    assert [b.selected_context for b in briefs] == ["個人", "公共", "職業"]
    # purpose stamped for observability
    assert client.calls[0][2] == "plan_context_angles"


def test_drops_out_of_set_context_to_none_preserving_position() -> None:
    payload = json.dumps([
        {"selected_context": "個人", "題材_angle": "有效角度一", "framing_hooks": []},
        {"selected_context": "教育", "題材_angle": "非法情境, 應該被丟", "framing_hooks": []},
        {"selected_context": "公共", "題材_angle": "有效角度二", "framing_hooks": []},
    ])
    client = _StubClient(payload)
    briefs = plan_context_angles(
        client,
        count=3,
        sampled_contexts=["個人", "公共"],
        learning_content_pool=[],
        system_prompt=_SYSTEM,
        user_prompt_template=_USER,
    )
    # Positional alignment: slot 1 (out-of-set) becomes None, never a
    # duplicate of another slot's brief.
    assert len(briefs) == 3
    assert isinstance(briefs[0], CreativeBrief)
    assert briefs[0].題材_angle == "有效角度一"
    assert briefs[1] is None
    assert isinstance(briefs[2], CreativeBrief)
    assert briefs[2].題材_angle == "有效角度二"


def test_returns_all_none_when_all_briefs_out_of_set(caplog) -> None:
    payload = json.dumps([
        {"selected_context": "教育", "題材_angle": "x", "framing_hooks": []},
    ])
    client = _StubClient(payload)
    with caplog.at_level("WARNING"):
        briefs = plan_context_angles(
            client,
            count=2,
            sampled_contexts=["個人", "公共"],
            learning_content_pool=[],
            system_prompt=_SYSTEM,
            user_prompt_template=_USER,
        )
    assert briefs == [None, None]
    assert any("plan_context_angles" in r.message for r in caplog.records)


def test_malformed_json_logs_warning_and_returns_none_slots(caplog) -> None:
    client = _StubClient("not-json-at-all")
    with caplog.at_level("WARNING"):
        briefs = plan_context_angles(
            client,
            count=3,
            sampled_contexts=["個人"],
            learning_content_pool=[],
            system_prompt=_SYSTEM,
            user_prompt_template=_USER,
        )
    assert briefs == [None, None, None]
    assert any("plan_context_angles" in r.message for r in caplog.records)


def test_client_raising_logs_warning_and_returns_none_slots(caplog) -> None:
    class _RaisingClient:
        def plan(self, system: str, user: str, purpose: str = "plan") -> str:
            raise RuntimeError("Opus is down")

    with caplog.at_level("WARNING"):
        briefs = plan_context_angles(
            _RaisingClient(),
            count=2,
            sampled_contexts=["個人"],
            learning_content_pool=[],
            system_prompt=_SYSTEM,
            user_prompt_template=_USER,
        )
    assert briefs == [None, None]
    assert any("plan_context_angles" in r.message for r in caplog.records)


def test_user_prompt_includes_core_question_when_present() -> None:
    payload = json.dumps([
        {"selected_context": "個人", "題材_angle": "a", "framing_hooks": []},
    ])
    client = _StubClient(payload)
    plan_context_angles(
        client,
        count=1,
        sampled_contexts=["個人"],
        learning_content_pool=["歷Ka-Ⅳ-1"],
        core_question="如何理解疫情擴散？",
        system_prompt=_SYSTEM,
        user_prompt_template=_USER,
    )
    _, user, _ = client.calls[0]
    assert "如何理解疫情擴散？" in user
    assert "歷Ka-Ⅳ-1" in user
