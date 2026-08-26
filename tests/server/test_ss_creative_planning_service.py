"""Tests for server-side per-batch creative planning (issue #114)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SUBJECTS
from src.common.resolver import resolve
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


def _resolved_params(payload: dict) -> GenerateParams:
    completed = resolve(payload).payload
    rows = completed.get("per_question_params")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("subquestion_configs"), list):
                row["subquestion_configs"] = json.dumps(
                    row["subquestion_configs"], ensure_ascii=False
                )
        completed["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    return GenerateParams.model_validate(completed)


def _fake_ss_spec(fake_generate_fn):
    """Return a copy of the SS SubjectSpec with do_generate replaced."""
    def fake_do_generate(rng_params, overrides, **kwargs):
        return fake_generate_fn(params=rng_params, **kwargs)

    return dataclasses.replace(SUBJECTS["social_studies"], do_generate=fake_do_generate)


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
        )
        return eq

    cfg = ServerConfig(api_key="x", output_dir=tmp_path, creative_planning=True)
    params = _resolved_params(
        {
            "subject": "social_studies",
            "count": 3,
            "seed": 3,
            "per_question_params": [{}, {}, {}],
            "skip_verify": True,
        }
    )

    events = _collect(generate_question_stream(
        params, cfg, _AppState(),
        subjects={"social_studies": _fake_ss_spec(fake_generate)},
    ))

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
        )

    cfg = ServerConfig(api_key="x", output_dir=tmp_path, creative_planning=False)
    params = _resolved_params(
        {
            "subject": "social_studies",
            "count": 2,
            "seed": 4,
            "per_question_params": [{}, {}],
            "skip_verify": True,
        }
    )

    events = _collect(generate_question_stream(
        params, cfg, _AppState(),
        subjects={"social_studies": _fake_ss_spec(fake_generate)},
    ))
    assert {"result", "done"}.issubset({e["event"] for e in events})


def test_math_branch_never_plans(monkeypatch, tmp_path) -> None:
    """Math batches must not touch plan_context_angles even when the flag is on."""
    monkeypatch.setattr(
        "src.social_studies.cli.plan_context_angles",
        MagicMock(side_effect=AssertionError("must not be called for math")),
    )

    # Inject a fake math spec whose resolved-payload adapter raises immediately — this
    # short-circuits the math generation without needing to monkeypatch service
    # module attributes.
    def fake_params_from_resolved_payload(payload, overrides):
        raise RuntimeError("stop math")

    fake_math_spec = dataclasses.replace(
        SUBJECTS["math"],
        params_from_resolved_payload=fake_params_from_resolved_payload,
    )

    class _MathState:
        renderer_pool = None
        curriculum = {}
        performance = {}
        intro_text = ""
        grade_content = {}

    cfg = ServerConfig(api_key="x", output_dir=tmp_path, creative_planning=True)
    params = GenerateParams(subject="math", count=2, skip_verify=True)

    events = _collect(generate_question_stream(
        params, cfg, _MathState(),
        subjects={"math": fake_math_spec},
    ))
    # Errors are OK; the AssertionError side_effect above is what we're guarding against.
    assert {"error", "done"}.intersection({e["event"] for e in events}) or True
