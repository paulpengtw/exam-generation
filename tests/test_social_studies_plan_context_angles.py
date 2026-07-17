"""Tests for src.social_studies.planner.plan_context_angles shim (issue #114)."""

from __future__ import annotations

import json

from src.social_studies.planner import (
    _SS_CREATIVE_PLANNER_SYSTEM_PROMPT,
    _SS_CREATIVE_PLANNER_USER_TEMPLATE,
    plan_context_angles,
)
from src.social_studies.schemas import CreativeBrief


class _StubClient:
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[tuple[str, str, str]] = []

    def plan(self, system: str, user: str, purpose: str = "plan") -> str:
        self.calls.append((system, user, purpose))
        return self._response


def test_shim_uses_social_studies_prompt_templates() -> None:
    payload = json.dumps([
        {"selected_context": "公共", "題材_angle": "議會辯論", "framing_hooks": ["逐字稿"]},
        {"selected_context": "個人", "題材_angle": "青少年志工日記", "framing_hooks": ["日記"]},
    ])
    client = _StubClient(payload)
    briefs = plan_context_angles(
        client,
        count=2,
        sampled_contexts=["公共", "個人"],
        learning_content_pool=["公Aa-Ⅳ-1"],
        core_question="如何理解青少年參與公共事務？",
    )
    assert len(briefs) == 2
    assert all(isinstance(b, CreativeBrief) for b in briefs)
    # Templates used
    assert "108課綱社會領域" in client.calls[0][0]
    assert "彼此的題材必須互相不同" in client.calls[0][0]
    assert "公Aa-Ⅳ-1" in client.calls[0][1]
    assert "如何理解青少年參與公共事務？" in client.calls[0][1]


def test_shim_returns_empty_list_when_all_out_of_set() -> None:
    payload = json.dumps([
        {"selected_context": "教育", "題材_angle": "x", "framing_hooks": []},
    ])
    client = _StubClient(payload)
    assert plan_context_angles(
        client,
        count=1,
        sampled_contexts=["個人"],
        learning_content_pool=[],
    ) == []


def test_templates_carry_n_and_learning_stage_placeholders() -> None:
    assert "{n}" in _SS_CREATIVE_PLANNER_SYSTEM_PROMPT
    assert "{learning_stage}" in _SS_CREATIVE_PLANNER_SYSTEM_PROMPT
    assert "{contexts}" in _SS_CREATIVE_PLANNER_USER_TEMPLATE
    assert "{count}" in _SS_CREATIVE_PLANNER_USER_TEMPLATE
    assert "{learning_content}" in _SS_CREATIVE_PLANNER_USER_TEMPLATE
    assert "{core_question}" in _SS_CREATIVE_PLANNER_USER_TEMPLATE
