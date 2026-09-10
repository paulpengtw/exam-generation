"""Server-side tests for per-question text_instruction routing (issue #637).

Acceptance criteria (slice B):
- build_prompt_previews: with count=2 and an override on 題組 2 only,
  題組 1's text prompt carries the request-level value and 題組 2's carries
  the override, for both social_studies and natural_sciences.
- generate_question_stream: the same routing is observed in the do_generate
  kwargs received by each worker.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import build_prompt_previews, generate_question_stream
from server.generate.subjects import SubjectSpec
from src.common.resolver import resolve

# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolved_params(payload: dict) -> GenerateParams:
    """Resolve a partial payload to a complete GenerateParams."""
    completed = resolve(payload).payload
    for field in ("subquestion_configs",):
        if isinstance(completed.get(field), list):
            completed[field] = json.dumps(completed[field], ensure_ascii=False)
    rows = completed.get("per_question_params")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("subquestion_configs"), list):
                row["subquestion_configs"] = json.dumps(
                    row["subquestion_configs"], ensure_ascii=False
                )
        completed["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    return GenerateParams.model_validate(completed)


# ── Fake SubjectSpec for generate_question_stream tests ───────────────────────


class _FakeQuestion(BaseModel):
    id: str
    圖片: str | None = None


class _FakeParams:
    pass


def _make_capturing_spec(captured: dict[int, str | None]) -> SubjectSpec:
    """Fake spec whose do_generate stores the text_instruction it receives per index."""

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(*a: Any, **kw: Any) -> list:
        return []

    def params_from_resolved_payload(payload: dict, overrides: dict) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kw: Any) -> _FakeQuestion:
        question_id: str = kw["question_id"]
        # question_id ends in "_001", "_002", … for i=0, 1, …
        idx = int(question_id.rsplit("_", 1)[1]) - 1
        captured[idx] = kw.get("text_instruction")
        return _FakeQuestion(id=question_id)

    def extract_prior_scope(q: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kw: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(cfg: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(cfg: Any, grade: Any) -> dict:  # pragma: no cover
        return {}

    return SubjectSpec(
        key="fake",
        question_id_prefix="fake_",
        exam_question_cls=_FakeQuestion,
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        params_from_resolved_payload=params_from_resolved_payload,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        patch_metadata=None,
        plan_core_questions=plan_core_questions,
        load_planner_stage=load_planner_stage,
        build_schemas=build_schemas,
    )


# ── Slice B-1: build_prompt_previews routes per-row text_instruction ──────────


@pytest.mark.parametrize("subject", ["social_studies", "natural_sciences"])
def test_build_prompt_previews_routes_per_question_text_instruction(
    subject: str,
) -> None:
    """题組 1 carries the request-level value; 題組 2 carries its per-row override."""
    request_ti = "request-level instruction"
    override_ti = "override-for-second-group"

    params = _resolved_params(
        {
            "subject": subject,
            "count": 2,
            "seed": 637,
            "disable_reference_fewshot": True,
            "text_instruction": request_ti,
            "per_question_params": json.dumps(
                [
                    {},  # 題組 0: no override
                    {"text_instruction": override_ti},  # 題組 1: override
                ]
            ),
        }
    )
    config = ServerConfig(
        api_key="x", data_dir=Path("data"), creative_planning=False
    )
    app_state = SimpleNamespace(
        ss_curriculum_context=None, ns_curriculum_context=None
    )

    previews = build_prompt_previews(params, config, app_state)

    # Each subject has one text-generator preview per 題組.
    text_previews = [p for p in previews if "subquestion_index" not in p]
    assert len(text_previews) == 2, (
        f"expected 2 text-generator previews, got {len(text_previews)}"
    )

    preview_0 = next(p for p in text_previews if p["index"] == 0)
    preview_1 = next(p for p in text_previews if p["index"] == 1)

    # 題組 0: request-level instruction must appear in the user prompt
    assert request_ti in preview_0["user_prompt"], (
        "題組 0 should carry the request-level text_instruction"
    )
    # 題組 1: override must appear in the user prompt
    assert override_ti in preview_1["user_prompt"], (
        "題組 1 should carry the per-row text_instruction override"
    )
    # The override must NOT appear in 題組 0's prompt
    assert override_ti not in preview_0["user_prompt"], (
        "題組 1's override must not leak into 題組 0"
    )
    # The request-level value must NOT appear in 題組 1's prompt
    # (override fully replaces it for that group)
    assert request_ti not in preview_1["user_prompt"], (
        "Request-level text_instruction must not appear in 題組 1 when overridden"
    )


# ── Slice B-2: generate_question_stream routes per-row text_instruction ───────


def test_generate_question_stream_routes_per_question_text_instruction(
    tmp_path: Path,
) -> None:
    """Each worker receives the correct text_instruction (per-row or request-level)."""
    request_ti = "stream-request-level"
    override_ti = "stream-override-for-second"

    captured: dict[int, str | None] = {}
    spec = _make_capturing_spec(captured)

    # Build a params object for the fake subject.
    # For the fake subject, the resolver doesn't know about it, so we supply
    # a minimal complete payload without per_question_params resolution.
    per_q = json.dumps([
        {},
        {"text_instruction": override_ti},
    ])
    params = GenerateParams(
        subject="fake",
        count=2,
        seed=42,
        text_instruction=request_ti,
        per_question_params=per_q,
        skip_verify=True,
    )

    config = ServerConfig(
        api_key="x", output_dir=tmp_path, data_dir=Path("data"), creative_planning=False
    )
    app_state = SimpleNamespace(renderer_pool=None)

    async def run() -> None:
        async for _ in generate_question_stream(
            params, config, app_state, subjects={"fake": spec}
        ):
            pass

    asyncio.run(run())

    # All workers must have been called.
    assert set(captured.keys()) == {0, 1}, (
        f"Expected workers 0 and 1 to run; got {set(captured.keys())}"
    )
    assert captured[0] == request_ti, (
        f"Worker 0 should receive request-level text_instruction {request_ti!r}, "
        f"got {captured[0]!r}"
    )
    assert captured[1] == override_ti, (
        f"Worker 1 should receive override text_instruction {override_ti!r}, "
        f"got {captured[1]!r}"
    )
