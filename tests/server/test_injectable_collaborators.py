"""Injectable collaborators for generate_question_stream (issue #159).

Two concerns are covered:

1. Guard test — fails hard if any test file still rebinds ``server.generate.service``
   module attributes, ensuring the migration cannot regress silently.

2. Fake-subject SSE ordering test — a fully synthetic ``SubjectSpec`` (its own
   sampler, generator returning a canned question, prior-scope extractor, no
   metadata patch, no batch planning) is injected via
   ``subjects={"fake": spec}`` with ``params.subject="fake"`` and the exact
   SSE event sequence is asserted in order.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from server.config import ServerConfig
from server.generate.models import GenerateParams
from server.generate.service import generate_question_stream
from server.generate.subjects import SubjectSpec

# ─────────────────────────────────────────────────────────────────────────────
# Guard test
# ─────────────────────────────────────────────────────────────────────────────

# Patterns indicating a test still rebinds server.generate.service attributes.
# Keep these narrow — they must NOT match legitimate patches on other modules
# (subjects.py, routes.py, src.social_studies.cli, etc.).
_BANNED_PATTERNS = [
    # Direct attribute assignment:  service.xxx =  (not a read like  x = service.xxx)
    r"\bservice\.[a-z_]+\s*=(?!=)",
    # monkeypatch.setattr targeting the service module namespace
    r'monkeypatch\.setattr\s*\(\s*["\']server\.generate\.service\.',
    # patch.object(service, …) where `service` is the generate service module
    r'patch\.object\s*\(\s*service\s*,',
    # patch("server.generate.service. …")
    r'patch\s*\(\s*["\']server\.generate\.service\.',
]

# Allowlist: file:line patterns that look like bans but are genuinely fine.
# Add entries only with a stated reason.
_ALLOWLIST: list[str] = [
    # None currently needed.
]

# ── Known seams outside the service module ────────────────────────────────────
# These patches target modules OTHER than ``server.generate.service`` and are
# therefore not caught by the banned patterns above.  They are documented here
# so the decision to keep them is explicit and reviewable.
#
# tests/server/test_math_curriculum_context_threading.py
#   patches ``server.generate.subjects._math_generate_with_corrections``
#
#   Why not use ``subjects=`` injection instead?
#   The two tests in that file verify that the real ``_math_do_generate``
#   adapter (1) correctly maps ``overrides["math_curriculum_context"]`` to the
#   ``curriculum_context=`` kwarg, and (2) does not crash when
#   ``app_state`` lacks ``math_curriculum_context``.  Both assertions require
#   the real adapter to remain in the call chain.  Replacing ``do_generate``
#   via ``subjects=`` would bypass ``_math_do_generate`` entirely and lose
#   that coverage.  Patching ``_math_generate_with_corrections`` in
#   ``subjects.py`` keeps the adapter active while stopping the LLM call —
#   this is the correct seam for this test's purpose.
# ─────────────────────────────────────────────────────────────────────────────

_TESTS_ROOT = Path(__file__).parent.parent  # tests/


def test_no_test_rebinds_service_module_attributes() -> None:
    """Fail if any test still monkeypatches server.generate.service attributes.

    Every fake collaborator must be passed as a keyword argument to
    generate_question_stream (subjects=, session_factory=, client_factory=),
    not by rebinding module-level names in the service module.
    """
    violations: list[str] = []

    banned_re = [re.compile(p) for p in _BANNED_PATTERNS]
    allowed_re = [re.compile(p) for p in _ALLOWLIST]

    # Skip this file itself — its comment strings contain the banned patterns
    # as documentation and would create spurious self-violations.
    this_file = Path(__file__).resolve()

    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        if path.resolve() == this_file:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(ar.search(line) for ar in allowed_re):
                continue
            for br in banned_re:
                if br.search(line):
                    violations.append(
                        f"{path.relative_to(_TESTS_ROOT)}:{lineno}: {line.rstrip()}"
                    )
                    break  # one report per line is enough

    if violations:
        joined = "\n  ".join(violations)
        pytest.fail(
            "Tests must not rebind server.generate.service attributes.\n"
            "Migrate these sites to pass fakes via generate_question_stream("
            "..., subjects=, session_factory=, client_factory=) instead:\n"
            f"  {joined}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fake-subject SSE event-ordering test
# ─────────────────────────────────────────────────────────────────────────────


class _FakeQuestion(BaseModel):
    """Minimal Pydantic model satisfying _question_to_event in service.py."""

    id: str
    圖片: str | None = None
    # service.py does `getattr(question, "subquestions", []) or []`;
    # the missing attribute path returns [] automatically.


class _FakeParams:
    """Opaque stand-in for sampled params; fake do_generate ignores it."""


def _make_fake_spec() -> SubjectSpec:
    """Build a minimal SubjectSpec that exercises every callsite in the stream.

    Design choices (stated per the issue):
    - client_factory is not overridden → default LLMClient is constructed but
      never used (the fake do_generate never calls it).
    - session_factory is not overridden → default AsyncSessionLocal is the
      default; no user_id is passed so _persist_generation_record is skipped.
    - plan_all_batch_briefs returns [] → no creative-brief patching happens,
      matching the math/NS no-op behaviour.
    - extract_prior_scope returns None → no prior scope accumulated.
    - patch_metadata is None → no post-generate patching.
    """

    def coerce_overrides(params: Any, app_state: Any) -> dict:
        return {}

    def plan_all_batch_briefs(
        params: Any,
        count: int,
        base_seed: Any,
        overrides: dict,
        config: Any,
        creative_planning: bool,
        decoded_subquestion_configs: Any,
        **_kwargs: Any,
    ) -> list:
        return []

    def do_sample_params(
        params: Any,
        overrides: dict,
        *,
        seed: Any,
        subquestion_configs_decoded: Any,
    ) -> _FakeParams:
        return _FakeParams()

    def do_generate(rng_params: Any, overrides: dict, **kwargs: Any) -> _FakeQuestion:
        return _FakeQuestion(id=kwargs["question_id"])

    def extract_prior_scope(question: Any) -> None:
        return None

    def plan_core_questions(client: Any, topic: str, **kwargs: Any) -> list:  # pragma: no cover
        return []

    def load_planner_stage(config_server: Any, grade: Any) -> str:  # pragma: no cover
        return "第四學習階段"

    def build_schemas(config_server: Any, grade: Any) -> dict:  # pragma: no cover
        return {}

    return SubjectSpec(
        key="fake",
        question_id_prefix="fake_",
        exam_question_cls=_FakeQuestion,
        coerce_overrides=coerce_overrides,
        plan_all_batch_briefs=plan_all_batch_briefs,
        do_sample_params=do_sample_params,
        do_generate=do_generate,
        extract_prior_scope=extract_prior_scope,
        patch_metadata=None,
        plan_core_questions=plan_core_questions,
        load_planner_stage=load_planner_stage,
        build_schemas=build_schemas,
    )


def test_fake_subject_sse_event_ordering(tmp_path: Path) -> None:
    """A synthetic SubjectSpec drives the real stream; exact SSE order is asserted.

    Injected via subjects={"fake": spec} with params.subject="fake".
    No real LLM call, no database, no module-attribute patching.

    Expected event sequence for count=1
    ------------------------------------
    started
    pipeline  (event_name=pipeline_start,  total=1)
    pipeline  (event_name=question_start,  index=0, total=1)
    pipeline  (event_name=question_end,    index=0, total=1)
    result    (data.id starts with "fake_")
    pipeline  (event_name=pipeline_end,    total=1)
    done
    """
    config = ServerConfig(
        api_key="x",
        output_dir=tmp_path,
        data_dir=Path("data"),
        creative_planning=False,
    )
    params = GenerateParams(subject="fake", count=1, skip_verify=True)
    app_state = SimpleNamespace(renderer_pool=None)
    fake_spec = _make_fake_spec()

    async def collect() -> list[dict]:
        events: list[dict] = []
        async for evt in generate_question_stream(
            params,
            config,
            app_state,
            subjects={"fake": fake_spec},
        ):
            events.append(evt)
        return events

    events = asyncio.run(collect())
    types = [e["event"] for e in events]

    # ── Boundary assertions ──────────────────────────────────────────────────
    assert types[0] == "started", f"First event must be 'started', got {types}"
    assert types[-1] == "done", f"Last event must be 'done', got {types}"

    # ── Exactly one result event ─────────────────────────────────────────────
    result_events = [e for e in events if e["event"] == "result"]
    assert len(result_events) == 1, f"Expected 1 result, got {len(result_events)}: {types}"

    result_payload = result_events[0]["data"]
    assert isinstance(result_payload, dict)
    assert result_payload.get("id", "").startswith("fake_"), (
        f"result.data.id should start with 'fake_'; got {result_payload.get('id')!r}"
    )

    # ── result comes before done ─────────────────────────────────────────────
    result_idx = types.index("result")
    done_idx = types.index("done")
    assert result_idx < done_idx, "result must precede done"

    # ── Pipeline sub-events exist and are in the right order ─────────────────
    pipeline_events = [e for e in events if e["event"] == "pipeline"]
    pipeline_names = [e["data"]["event_name"] for e in pipeline_events]

    for required in ("pipeline_start", "question_start", "question_end", "pipeline_end"):
        assert required in pipeline_names, (
            f"Missing pipeline sub-event '{required}': {pipeline_names}"
        )

    idx_ps = pipeline_names.index("pipeline_start")
    idx_qs = pipeline_names.index("question_start")
    idx_qe = pipeline_names.index("question_end")
    idx_pe = pipeline_names.index("pipeline_end")
    assert idx_ps < idx_qs, "pipeline_start must precede question_start"
    assert idx_qs < idx_qe, "question_start must precede question_end"
    assert idx_qe < idx_pe, "question_end must precede pipeline_end"

    # ── pipeline events appear between started and done ──────────────────────
    first_pipeline_global_idx = types.index("pipeline")
    assert 0 < first_pipeline_global_idx < done_idx, (
        "pipeline events must appear after started and before done"
    )

    # ── question_start / question_end carry correct metadata ─────────────────
    qs_event = next(e for e in pipeline_events if e["data"]["event_name"] == "question_start")
    qe_event = next(e for e in pipeline_events if e["data"]["event_name"] == "question_end")
    assert qs_event["data"]["index"] == 0
    assert qs_event["data"]["total"] == 1
    assert qe_event["data"]["index"] == 0
    assert qe_event["data"]["total"] == 1

    # ── pipeline_start / pipeline_end carry total=1 ──────────────────────────
    ps_event = next(e for e in pipeline_events if e["data"]["event_name"] == "pipeline_start")
    pe_event = next(e for e in pipeline_events if e["data"]["event_name"] == "pipeline_end")
    assert ps_event["data"]["total"] == 1
    assert pe_event["data"]["total"] == 1
