"""Issue #291 end-to-end guard: 年級 10-12 request reaches the generated 自然科學 question.

A stubbed 文本生成器/子題產生器 that returns 年級 8 / 第四學習階段 codes for a
grade-11 request must produce a question whose every 小題 has 年級 11 with only
第五學習階段 學習內容/學習表現 — proving the three upstream fixes compose:

    ┌─────────────────────────────────┬──────────────────────────────────────────────┐
    │ assertion                       │ which fix it guards                          │
    ├─────────────────────────────────┼──────────────────────────────────────────────┤
    │ sq.年級 == 11                   │ #286 — 年級 forcing via force_grade()        │
    │ LC/LP codes are 第五學習階段    │ #287 — stage-aware repair_lc/lp_refs()       │
    │ sub-system has no stage-4 ex.   │ #288 — stage-matched subquestion example     │
    └─────────────────────────────────┴──────────────────────────────────────────────┘

A parallel grade-8 request (control) confirms 第四 codes are kept — no over-correction.

All three fixes must be present for the grade-11 scenario to pass:
  - Without #286: sq.年級 would remain 8 (the LLM value) → assertion fails.
  - Without #287: stage-4 LC/LP codes would survive repair → assertion fails.
  - Without #288: the sub-system prompt carries 年級 8 / Ka-Ⅳ-1 example for
    a grade-11 request → sub-system prompt assertion fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import src.natural_sciences.cli as ns_cli
from src.config import Config
from src.natural_sciences.sampler import sample_params
from src.natural_sciences.schemas import ExamQuestion

# ---------------------------------------------------------------------------
# Pinned curriculum codes used in tests
# ---------------------------------------------------------------------------
# Stage-4 (第四學習階段, grades 7-9) codes — what the stubbed LLM returns
# Both codes confirmed present in data/natural_sciences/curriculum/
_STAGE4_LC = "Ka-Ⅳ-1"   # learning_content.json, 學習階段=第四學習階段
_STAGE4_LP = "tr-Ⅳ-1"   # learning_performance.json, 學習階段=第四學習階段

# Stage-5 (第五學習階段, grades 10-12) codes — expected in the grade-11 output
_STAGE5_LC = "BDa-Ⅴa-1"  # confirmed present, 學習階段=第五學習階段
_STAGE5_LP = "pa-Ⅴa-1"   # confirmed present, 學習階段=第五學習階段


# ---------------------------------------------------------------------------
# Fake clients
# ---------------------------------------------------------------------------

class _FakeTextClient:
    """Stubbed 文本生成器: returns a text-shell with one subquestion plan."""

    def get_observer(self) -> None:
        return None

    def generate_json(self, system_prompt: str, user_prompt: str, **_kwargs: Any) -> dict:
        return {
            "核心問題": "e2e test 核心問題",
            "文本": "e2e test 文本素材",
            "取材來源": ["e2e test"],
            # The text stage returns a single-item plan; the sub-client is called for its content.
            "subquestions": [
                {
                    "序號": 1,
                    "題型": "Simple multiple-choice",
                    "出題概念": "e2e test 概念",
                },
            ],
        }


class _FakeSubClientStage4:
    """Stubbed 子題產生器: deliberately returns 年級 8 and 第四學習階段 codes.

    This simulates the pre-fix behavior: the prompt's hard-coded example had
    年級=8 and stage-4 codes, so the LLM echoed them even for grade-11
    requests.  The three fixes transform this output before it is stored.
    """

    def __init__(self, captured_system_prompts: list[str]) -> None:
        self._captured = captured_system_prompts

    def set_observer(self, _obs: Any) -> None:
        pass

    def generate_json(self, system_prompt: str, user_prompt: str, **_kwargs: Any) -> dict:
        self._captured.append(system_prompt)
        return {
            "序號": 1,
            "年級": 8,                                      # wrong grade — fix #286 forces it
            "科目": ["自然科學"],
            "科學能力": ["能力一：以科學的角度解釋現象"],
            "核心素養": [],
            "題型": "Simple multiple-choice",
            "出題概念": "e2e test 概念",
            "題目": "下列何者最符合？(A) 甲 (B) 乙 (C) 丙 (D) 丁",
            "答案": "A",
            "答案解析": "解析說明",
            "評分規準": [],
            "學習內容": [{"編碼": _STAGE4_LC, "說明": "第四階段 LC (should be repaired)"}],
            "學習表現": [{"編碼": _STAGE4_LP, "說明": "第四階段 LP (should be repaired)"}],
        }


def _make_sub_factory(captured: list[str]):
    def factory() -> _FakeSubClientStage4:
        return _FakeSubClientStage4(captured)
    return factory


# ---------------------------------------------------------------------------
# AC 1: grade-11 request → every 小題 has 年級 11 and 第五學習階段 codes
# ---------------------------------------------------------------------------

def test_e2e_grade11_stub_stage4_produces_stage5_output(tmp_path) -> None:
    """Core E2E guard: grade-11 request with stage-4 LLM stub → stage-5 output.

    Failing assertions by reverted fix:
      - 年級 == 11          → fails without fix #286 (force_grade not called)
      - LC code is stage-5  → fails without fix #287 (repair_lc_refs not stage-aware)
      - LP code is stage-5  → fails without fix #287 (repair_lp_refs not stage-aware)
      - sub-system prompt   → fails without fix #288 (prompt example has stage-4 codes)
    """
    config = Config(data_dir=Path("data"), output_dir=tmp_path)
    # Pin the stage-5 fallback pool so the repaired result is deterministic.
    params = sample_params(
        grade=11,
        seed=7,
        q_type=["Simple multiple-choice"],
        learning_content=[_STAGE5_LC],
        learning_performance=[_STAGE5_LP],
    )

    captured_sub_systems: list[str] = []

    question = ns_cli.generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="e2e_grade11_001",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_make_sub_factory(captured_sub_systems),
    )

    assert isinstance(question, ExamQuestion), f"Expected ExamQuestion, got {type(question)}"
    assert len(question.subquestions) == 1, (
        f"Expected 1 subquestion, got {len(question.subquestions)}"
    )

    sq = question.subquestions[0]

    # Fix #286: 年級 must be forced from sampled params, not the LLM's value.
    assert sq.年級 == 11, (
        f"Fix #286 regression: expected 年級=11 (sampled), got 年級={sq.年級} (LLM value)"
    )

    # Fix #287: off-stage LC codes must be dropped; fallback pool (_STAGE5_LC) kicks in.
    lc_codes = [r.編碼 for r in sq.學習內容]
    for code in lc_codes:
        assert "Ⅴ" in code or "V" in code, (
            f"Fix #287 regression: expected a 第五學習階段 LC code but got '{code}' "
            f"(all codes: {lc_codes})"
        )
    assert _STAGE4_LC not in lc_codes, (
        f"Fix #287 regression: 第四學習階段 LC code '{_STAGE4_LC}' survived stage-aware repair"
    )

    # Fix #287: off-stage LP codes must be dropped; fallback pool (_STAGE5_LP) kicks in.
    lp_codes = [r.編碼 for r in sq.學習表現]
    for code in lp_codes:
        assert "Ⅴ" in code or "V" in code, (
            f"Fix #287 regression: expected a 第五學習階段 LP code but got '{code}' "
            f"(all codes: {lp_codes})"
        )
    assert _STAGE4_LP not in lp_codes, (
        f"Fix #287 regression: 第四學習階段 LP code '{_STAGE4_LP}' survived stage-aware repair"
    )

    # Fix #288: grade-11 sub-system prompt must not contain grade-8 / stage-4 example codes.
    assert len(captured_sub_systems) >= 1, "Expected at least one sub-system prompt to be captured"
    sub_system = captured_sub_systems[0]
    assert '"年級": 8' not in sub_system, (
        "Fix #288 regression: grade-11 sub-system prompt contains 年級 8 in the example block"
    )
    assert _STAGE4_LC not in sub_system, (
        f"Fix #288 regression: grade-11 sub-system prompt contains stage-4 LC '{_STAGE4_LC}' "
        "in the example block"
    )
    assert _STAGE4_LP not in sub_system, (
        f"Fix #288 regression: grade-11 sub-system prompt contains stage-4 LP '{_STAGE4_LP}' "
        "in the example block"
    )


# ---------------------------------------------------------------------------
# AC 2: grade-8 request (control) → still yields 第四學習階段 codes
# ---------------------------------------------------------------------------

def test_e2e_grade8_stub_stage4_keeps_stage4_output(tmp_path) -> None:
    """Control case: grade-8 request keeps 第四學習階段 codes — no over-correction.

    The fixes must not change behavior for grade-8 requests where the LLM
    correctly emits 年級=8 and 第四學習階段 LC/LP codes.
    """
    config = Config(data_dir=Path("data"), output_dir=tmp_path)
    # Pin the stage-4 fallback pool to match the LLM's response.
    params = sample_params(
        grade=8,
        seed=3,
        q_type=["Simple multiple-choice"],
        learning_content=[_STAGE4_LC],
        learning_performance=[_STAGE4_LP],
    )

    captured_sub_systems: list[str] = []

    question = ns_cli.generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="e2e_grade8_001",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=_make_sub_factory(captured_sub_systems),
    )

    assert isinstance(question, ExamQuestion), f"Expected ExamQuestion, got {type(question)}"
    assert len(question.subquestions) == 1

    sq = question.subquestions[0]

    # Grade must be 8 (sampled) — force_grade works correctly.
    assert sq.年級 == 8, f"Expected 年級=8 for grade-8 request, got {sq.年級}"

    # LC/LP codes: the LLM returned _STAGE4_LC / _STAGE4_LP, which are valid
    # for 第四學習階段.  Stage-aware repair must keep them, not replace them.
    lc_codes = [r.編碼 for r in sq.學習內容]
    lp_codes = [r.編碼 for r in sq.學習表現]
    assert _STAGE4_LC in lc_codes, (
        f"Over-correction: grade-8 LC code '{_STAGE4_LC}' was dropped from {lc_codes}"
    )
    assert _STAGE4_LP in lp_codes, (
        f"Over-correction: grade-8 LP code '{_STAGE4_LP}' was dropped from {lp_codes}"
    )

    # Stage-5 codes must NOT appear for a grade-8 request.
    for code in lc_codes:
        assert _STAGE5_LC not in code, (
            f"Over-correction: grade-8 output contains a stage-5 LC code: {code}"
        )
    for code in lp_codes:
        assert _STAGE5_LP not in code, (
            f"Over-correction: grade-8 output contains a stage-5 LP code: {code}"
        )
