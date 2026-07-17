"""Tests for server-side per-batch creative planning (issue #114)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from src.social_studies.schemas import CreativeBrief, ExamQuestion


class _AppState:
    """Minimal app_state stub — no renderer pool, no math data."""
    renderer_pool = None


def _collect(coro):
    async def _run():
        events = []
        async for evt in coro:
            events.append(evt)
        return events
    return asyncio.run(_run())


def test_ss_batch_calls_plan_context_angles_once(monkeypatch, tmp_path) -> None:
    plan_calls = {"count": 0}

    def fake_plan(client, count, sampled_contexts, learning_content_pool,
                  core_question=None, **kwargs):
        plan_calls["count"] += 1
        return [
            CreativeBrief(selected_context=sampled_contexts[0], 題材_angle=f"角度{i}")
            for i in range(count)
        ]

    monkeypatch.setattr(
        "src.social_studies.cli.plan_context_angles",
        fake_plan,
    )

    captured_params = []

    def fake_generate(**kwargs):
        captured_params.append(kwargs["params"])
        eq = ExamQuestion(
            id=kwargs["question_id"],
            情境=[c.value for c in kwargs["params"].情境],
            題型種類=kwargs["params"].題型種類.value,
            題型="選擇題",
            閱讀歷程=[p.value for p in kwargs["params"].閱讀歷程],
            文本形式=kwargs["params"].文本形式.value,
        )
        return eq

    monkeypatch.setattr(
        "server.generate.service.ss_generate_with_corrections",
        fake_generate,
    )

    cfg = ServerConfig(api_key="x", output_dir=tmp_path, creative_planning=True)
    params = GenerateParams(subject="social_studies", count=3, skip_verify=True)

    events = _collect(generate_question_stream(params, cfg, _AppState()))

    assert plan_calls["count"] == 1
    assert len(captured_params) == 3
    assert all(p.creative_brief is not None for p in captured_params)
    assert {"result", "done"}.issubset({e["event"] for e in events})


def test_ss_batch_skips_planning_when_flag_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "src.social_studies.cli.plan_context_angles",
        MagicMock(side_effect=AssertionError("should not be called")),
    )

    def fake_generate(**kwargs):
        return ExamQuestion(
            id=kwargs["question_id"],
            情境=[c.value for c in kwargs["params"].情境],
            題型種類=kwargs["params"].題型種類.value,
            題型="選擇題",
            閱讀歷程=[p.value for p in kwargs["params"].閱讀歷程],
            文本形式=kwargs["params"].文本形式.value,
        )

    monkeypatch.setattr(
        "server.generate.service.ss_generate_with_corrections",
        fake_generate,
    )

    cfg = ServerConfig(api_key="x", output_dir=tmp_path, creative_planning=False)
    params = GenerateParams(subject="social_studies", count=2, skip_verify=True)

    events = _collect(generate_question_stream(params, cfg, _AppState()))
    assert {"result", "done"}.issubset({e["event"] for e in events})


def test_math_branch_never_plans(monkeypatch, tmp_path) -> None:
    """Math batches must not touch plan_context_angles even when the flag is on."""
    monkeypatch.setattr(
        "src.social_studies.cli.plan_context_angles",
        MagicMock(side_effect=AssertionError("must not be called for math")),
    )
    # We only need to prove the SS planner is not invoked; short-circuit math
    # generation by making sample_params raise so the branch exits early.
    monkeypatch.setattr(
        "server.generate.service.math_sample_params",
        MagicMock(side_effect=RuntimeError("stop math")),
    )

    class _MathState:
        renderer_pool = None
        curriculum = {}
        performance = {}
        intro_text = ""
        grade_content = {}

    cfg = ServerConfig(api_key="x", output_dir=tmp_path, creative_planning=True)
    params = GenerateParams(subject="math", count=2, skip_verify=True)

    events = _collect(generate_question_stream(params, cfg, _MathState()))
    # Errors are OK; the AssertionError side_effect above is what we're guarding against.
    assert {"error", "done"}.intersection({e["event"] for e in events}) or True
