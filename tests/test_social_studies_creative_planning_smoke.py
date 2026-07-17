"""Env-gated diversity smoke test for creative planning (issue #114).

Not run in CI. Trigger locally with:

    RUN_CREATIVE_PLANNING_SMOKE=1 uv run pytest \
        tests/test_social_studies_creative_planning_smoke.py -s

The test issues one real Opus planning call for a 5-question batch and
asserts that at least 3 distinct 題材 keywords appear across the briefs.
"""

from __future__ import annotations

import os
import re

import pytest

from src.config import Config
from src.llm_client import LLMClient
from src.social_studies.planner import plan_context_angles
from src.social_studies.sampler import sample_params

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_CREATIVE_PLANNING_SMOKE") != "1",
    reason="Set RUN_CREATIVE_PLANNING_SMOKE=1 to run this smoke test.",
)


def test_five_briefs_have_at_least_three_distinct_題材_keywords() -> None:
    cfg = Config.from_env()
    cfg.validate()
    client = LLMClient(cfg)

    params = sample_params(seed=42)
    contexts = [c.value for c in params.情境]

    briefs = plan_context_angles(
        client,
        count=5,
        sampled_contexts=contexts,
        learning_content_pool=params.學習內容_pool,
        core_question=None,
    )

    assert len(briefs) == 5, f"expected 5 briefs, got {len(briefs)}"

    # A very rough "distinct keyword" heuristic: take the first 2 Chinese
    # nouns from each 題材_angle by grabbing runs of 2–5 CJK characters that
    # appear before typical particles/verbs.
    keywords = set()
    for brief in briefs:
        tokens = re.findall(r"[一-鿿]{2,5}", brief.題材_angle)
        keywords.update(tokens[:3])

    print("題材 keywords across 5 briefs:", keywords)
    assert len(keywords) >= 3, (
        f"expected ≥3 distinct 題材 keywords across 5 briefs, got {len(keywords)}: {keywords}"
    )
