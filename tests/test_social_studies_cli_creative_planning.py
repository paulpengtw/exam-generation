"""Tests for CLI-side batch planning integration (issue #114).

Note on `test_returns_none_list_on_llm_failure`: `plan_context_angles`
(src/common/planner.py) never raises — it already catches `client.plan()`
failures internally and logs its own WARNING ("plan_context_angles:
planning call failed ...") before returning `[None] * count`. That makes
the defensive `except Exception` inside `_plan_batch_briefs` unreachable
in this scenario (kept only as defense-in-depth against future changes to
the planner's contract). Per the Tasks 2-3 compatibility note, this test
asserts the `[None, None]` result and the planner-layer warning text
("planning call failed") rather than a "creative planning" substring that
would never be emitted for this failure path.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.config import Config
from src.social_studies.cli import _plan_batch_briefs, generate_one
from src.social_studies.context_builder import _CREATIVE_BRIEF_SYSTEM_BLOCK
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import CreativeBrief


class _StubClient:
    """Minimal client stub exposing only the methods the planner touches."""

    def __init__(self, briefs: list[CreativeBrief] | Exception) -> None:
        self._briefs = briefs
        self.plan_calls = 0

    def plan(self, system, user, purpose="plan"):
        self.plan_calls += 1
        if isinstance(self._briefs, Exception):
            raise self._briefs
        import json
        return json.dumps([b.model_dump() for b in self._briefs])


def _params(seed: int):
    return sample_params(seed=seed)


def test_returns_none_list_when_creative_planning_disabled() -> None:
    cfg = Config(creative_planning=False)
    client = _StubClient([])
    p = _params(1)
    briefs = _plan_batch_briefs(client, cfg, [p, p])
    assert briefs == [None, None]
    assert client.plan_calls == 0


def test_returns_none_list_when_client_is_none() -> None:
    cfg = Config(creative_planning=True)
    briefs = _plan_batch_briefs(None, cfg, [_params(1)])
    assert briefs == [None]


def test_returns_brief_per_slot_when_planner_succeeds() -> None:
    cfg = Config(creative_planning=True)
    p = _params(1)
    contexts = [c.value for c in p.情境]
    stub_briefs = [
        CreativeBrief(selected_context=contexts[0], 題材_angle=f"角度{i}", framing_hooks=[])
        for i in range(2)
    ]
    client = _StubClient(stub_briefs)
    briefs = _plan_batch_briefs(client, cfg, [p, p])
    assert len(briefs) == 2
    assert all(isinstance(b, CreativeBrief) for b in briefs)
    assert client.plan_calls == 1  # per-batch, not per-question


def test_returns_none_list_on_llm_failure(caplog) -> None:
    cfg = Config(creative_planning=True)
    client = _StubClient(RuntimeError("Opus is down"))
    with caplog.at_level("WARNING"):
        briefs = _plan_batch_briefs(client, cfg, [_params(1), _params(2)])
    assert briefs == [None, None]
    assert any("planning call failed" in r.message.lower() for r in caplog.records)


def test_pads_missing_slots_with_none_when_planner_returns_empty() -> None:
    """When plan_context_angles returns []], all slots are None (briefless)."""
    cfg = Config(creative_planning=True)
    # Response with only out-of-set contexts → survivors = 0 → planner returns []
    class _EmptyClient:
        plan_calls = 0

        def plan(self, system, user, purpose="plan"):
            _EmptyClient.plan_calls += 1
            return '[{"selected_context": "教育", "題材_angle": "x", "framing_hooks": []}]'

    p = _params(1)
    # sampled 情境 excludes 教育 for seed=1? sampler always samples from all_contexts,
    # so pick a params whose 情境 excludes 教育 by construction:
    from src.social_studies.schemas import QuestionContext
    p_only_person = p.model_copy(update={"情境": [QuestionContext("個人")]})
    briefs = _plan_batch_briefs(_EmptyClient(), cfg, [p_only_person, p_only_person])
    assert briefs == [None, None]


def _extract_system_chars(dry_run_output: str) -> int:
    match = re.search(r"=== TEXT SYSTEM PROMPT \((\d+) chars\) ===", dry_run_output)
    assert match, f"could not find TEXT SYSTEM PROMPT char count in: {dry_run_output[:200]}"
    return int(match.group(1))


def test_generate_one_dry_run_forwards_creative_brief_into_system_prompt(tmp_path) -> None:
    """Regression for the integration gap where generate_one() built the 文本生成器

    system prompt via `build_text_system_prompt()` without `creative_brief=params.creative_brief`
    at both the dry-run and real call sites, so the ### 創意指引 system-prompt block
    (added by build_text_system_prompt when creative_brief is not None) never fired in
    production even when a brief was attached to params.

    generate_one's dry-run output truncates the printed system prompt preview to 2000
    chars (`text_system[:2000]`), and the curriculum-heavy system prompt is ~93KB, so the
    appended 創意指引 marker itself falls outside the preview window and can't be asserted
    as a literal substring here. Instead this test asserts on the untruncated `len(text_system)`
    reported in the dry-run header: with a brief attached, the header count must be exactly
    `len(_CREATIVE_BRIEF_SYSTEM_BLOCK)` chars larger than without one — which only happens if
    generate_one actually threads `creative_brief` into `build_text_system_prompt()`.
    The underlying substring behavior of build_text_system_prompt() itself is covered directly
    by `test_system_prompt_appends_創意指引_block_only_with_brief` in
    tests/test_social_studies_creative_brief_prompt.py.
    """
    config = Config(data_dir=Path("data"))
    params = sample_params(seed=7)
    brief = CreativeBrief(
        selected_context=params.情境[0].value,
        題材_angle="以居家防疫日記串起個人與公共衛生決策",
        framing_hooks=["病患日記"],
    )
    params_with_brief = params.model_copy(update={"creative_brief": brief})
    params_without_brief = params.model_copy(update={"creative_brief": None})

    out_with = generate_one(config, None, params_with_brief, "ss_test_001", dry_run=True)
    out_without = generate_one(config, None, params_without_brief, "ss_test_002", dry_run=True)

    chars_with = _extract_system_chars(out_with)
    chars_without = _extract_system_chars(out_without)

    assert chars_with - chars_without == len(_CREATIVE_BRIEF_SYSTEM_BLOCK)
