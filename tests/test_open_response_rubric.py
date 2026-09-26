"""Tests for src/common/open_response_rubric.py (issue #866).

Table-driven tests for the shape checker, constant assertions,
and the is_open_response predicate.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from src.common.open_response_rubric import (
    COUNTING_STEM_CORRECTION_ROUTING_LINE,
    EXPECTED_EXAMPLE_COUNTS,
    EXTRA_ITEMS_FIXED_SENTENCE,
    OPEN_RESPONSE_RUBRIC_RULE,
    check_open_response_rubric_shape,
    is_open_response,
)

# ---------------------------------------------------------------------------
# Helpers — lightweight stubs that match the duck-typed interface
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _RubricEntry:
    code: str
    規準說明: str
    學生作答實例: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class _SubQuestion:
    序號: int
    題型: str
    評分規準: list[_RubricEntry] = dataclasses.field(default_factory=list)


_FIXED = EXTRA_ITEMS_FIXED_SENTENCE  # shorthand


def _conforming_rubric(n: int = 1) -> list[_RubricEntry]:
    """Return a fully conforming 2/1/0 rubric with 1/2/1 examples."""
    return [
        _RubricEntry(
            code="2",
            規準說明=f"完整說明。{_FIXED}",
            學生作答實例=[f"完整作答第{n}題。"],
        ),
        _RubricEntry(
            code="1",
            規準說明=f"部分說明，推理有缺口。",
            學生作答實例=[f"稍有說明但不完整，第{n}題。", f"另一種缺口，第{n}題。"],
        ),
        _RubricEntry(
            code="0",
            規準說明=f"方向錯誤。",
            學生作答實例=[f"錯誤觀念作答，第{n}題。"],
        ),
    ]


def _sq(n: int, rubric: list[_RubricEntry], q_type: str = "Constructed response") -> _SubQuestion:
    return _SubQuestion(序號=n, 題型=q_type, 評分規準=rubric)


# ---------------------------------------------------------------------------
# Block constant tests
# ---------------------------------------------------------------------------

def test_block_contains_seven_clause_markers_each_at_line_start() -> None:
    """Each of the 7 clause markers starts exactly one indented line."""
    markers = ["【禁止】", "【判準】", "【注意】", "【提問】", "【額外項目】", "【具體性】", "【學生作答實例】"]
    for marker in markers:
        count = sum(
            1
            for line in OPEN_RESPONSE_RUBRIC_RULE.splitlines()
            if line.strip().startswith(marker)
        )
        assert count == 1, f"{marker} should start exactly one line; found {count}"


def test_block_contains_no_braces() -> None:
    assert "{" not in OPEN_RESPONSE_RUBRIC_RULE
    assert "}" not in OPEN_RESPONSE_RUBRIC_RULE


def test_extra_items_fixed_sentence_is_substring_of_block() -> None:
    assert EXTRA_ITEMS_FIXED_SENTENCE in OPEN_RESPONSE_RUBRIC_RULE


def test_block_byte_identical_to_final_block_txt() -> None:
    """OPEN_RESPONSE_RUBRIC_RULE must be byte-identical to the approved final_block.txt."""
    path = Path(
        "/tmp/claude-1000/-workspace/a5a1e464-5288-47d1-a5bc-fac46e4a8a92/scratchpad/final_block.txt"
    )
    if not path.exists():
        pytest.skip("final_block.txt not available in this environment")
    expected = path.read_text(encoding="utf-8")
    assert OPEN_RESPONSE_RUBRIC_RULE == expected


def test_expected_example_counts() -> None:
    assert EXPECTED_EXAMPLE_COUNTS == {"2": 1, "1": 2, "0": 1}


def test_counting_stem_routing_line_defined() -> None:
    assert "計數式提問" in COUNTING_STEM_CORRECTION_ROUTING_LINE
    assert "逐一點名各項或只要求一項" in COUNTING_STEM_CORRECTION_ROUTING_LINE


# ---------------------------------------------------------------------------
# is_open_response predicate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("開放式建構反應題", True),
    ("Constructed response", True),
    ("Simple multiple-choice", False),
    ("Complex multiple-choice", False),
    ("選擇題", False),
    ("", False),
])
def test_is_open_response_str(value: str, expected: bool) -> None:
    assert is_open_response(value) is expected


def test_is_open_response_accepts_enum_with_value_attribute() -> None:
    """Accepts enum instances that carry a .value attribute."""

    class FakeEnum:
        def __init__(self, val: str) -> None:
            self.value = val

    assert is_open_response(FakeEnum("Constructed response")) is True
    assert is_open_response(FakeEnum("開放式建構反應題")) is True
    assert is_open_response(FakeEnum("Simple multiple-choice")) is False


# ---------------------------------------------------------------------------
# check_open_response_rubric_shape — table-driven
# ---------------------------------------------------------------------------

def test_shape_check_conforming_no_issues() -> None:
    """A perfectly conforming rubric produces no issues."""
    sqs = [_sq(1, _conforming_rubric())]
    assert check_open_response_rubric_shape(sqs) == []


def test_shape_check_all_in_scope_by_default() -> None:
    """Without in_scope argument, every subquestion is checked."""
    rubric = _conforming_rubric()
    rubric[1].學生作答實例 = ["只有一個"]  # [1] needs 2
    sqs = [_sq(1, rubric)]
    issues = check_open_response_rubric_shape(sqs)
    assert any("[1]" in i and "2 個" in i for i in issues)


def test_shape_check_level_1_missing_one_example() -> None:
    """[1] with 1 example instead of 2 → count issue."""
    rubric = _conforming_rubric()
    rubric[1].學生作答實例 = ["只有一個"]
    sqs = [_sq(1, rubric)]
    issues = check_open_response_rubric_shape(sqs)
    assert len(issues) == 1
    assert "第1題 [1] 級距需要 2 個學生作答實例（目前 1 個）" in issues[0]
    assert "第一個是 [2] 實例的最小對照" in issues[0]


def test_shape_check_blank_example() -> None:
    """Whitespace-only example → blank-example issue + count issue."""
    rubric = _conforming_rubric()
    rubric[0].學生作答實例 = ["   "]  # blank — doesn't count
    sqs = [_sq(1, rubric)]
    issues = check_open_response_rubric_shape(sqs)
    # Both a blank-example issue and a count issue for [2]
    assert any("空白" in i and "[2]" in i for i in issues)
    assert any("[2] 級距需要 1 個" in i and "目前 0 個" in i for i in issues)


def test_shape_check_levels_3210() -> None:
    """Levels 3/2/1/0 → wrong level set issue plus count issues for existing 2/1/0."""
    rubric = [
        _RubricEntry(code="3", 規準說明=f"超完整。{_FIXED}", 學生作答實例=["完美答案。"]),
        _RubricEntry(code="2", 規準說明=f"完整。{_FIXED}", 學生作答實例=["完整作答。"]),
        _RubricEntry(
            code="1",
            規準說明="部分。",
            學生作答實例=["缺口一。", "缺口二。"],
        ),
        _RubricEntry(code="0", 規準說明="錯誤。", 學生作答實例=["錯誤作答。"]),
    ]
    sqs = [_sq(1, rubric)]
    issues = check_open_response_rubric_shape(sqs)
    # Level set issue
    assert any("評分規準級距必須恰為 2 / 1 / 0" in i for i in issues)
    # No count issues for the existing 2/1/0 levels (they all have correct counts)
    count_issues = [i for i in issues if "需要" in i and "個學生作答實例" in i]
    assert count_issues == [], f"Unexpected count issues: {count_issues}"


def test_shape_check_levels_20() -> None:
    """Levels 2/0 → wrong level set issue, no spurious count issues."""
    rubric = [
        _RubricEntry(code="2", 規準說明=f"完整。{_FIXED}", 學生作答實例=["完整。"]),
        _RubricEntry(code="0", 規準說明="錯誤。", 學生作答實例=["錯誤。"]),
    ]
    sqs = [_sq(1, rubric)]
    issues = check_open_response_rubric_shape(sqs)
    assert any("評分規準級距必須恰為 2 / 1 / 0" in i for i in issues)
    # [2] and [0] have correct counts; no count issues for them
    count_issues = [i for i in issues if "需要" in i]
    assert count_issues == []


def test_shape_check_duplicated_code() -> None:
    """Two entries with code '2' → level set issue (wrong count of codes)."""
    rubric = [
        _RubricEntry(code="2", 規準說明=f"完整A。{_FIXED}", 學生作答實例=["完整A。"]),
        _RubricEntry(code="2", 規準說明=f"完整B。{_FIXED}", 學生作答實例=["完整B。"]),
        _RubricEntry(code="1", 規準說明="部分。", 學生作答實例=["缺口一。", "缺口二。"]),
        _RubricEntry(code="0", 規準說明="錯誤。", 學生作答實例=["錯誤。"]),
    ]
    sqs = [_sq(1, rubric)]
    issues = check_open_response_rubric_shape(sqs)
    assert any("評分規準級距必須恰為 2 / 1 / 0" in i for i in issues)


def test_shape_check_several_subquestions() -> None:
    """Issues are reported per-subquestion with correct 序號."""
    rubric1 = _conforming_rubric(1)
    rubric1[0].學生作答實例 = ["一", "二"]  # [2] should have 1, has 2

    rubric2 = _conforming_rubric(2)
    rubric2[1].學生作答實例 = ["只有一個"]  # [1] should have 2, has 1

    sqs = [_sq(1, rubric1), _sq(2, rubric2)]
    issues = check_open_response_rubric_shape(sqs)

    assert any("第1題 [2] 級距需要 1 個學生作答實例（目前 2 個）" in i for i in issues)
    assert any("第2題 [1] 級距需要 2 個學生作答實例（目前 1 個）" in i for i in issues)


def test_shape_check_in_scope_false_skips() -> None:
    """Subquestions with in_scope=False are not checked."""
    bad_rubric = [_RubricEntry(code="2", 規準說明="incomplete", 學生作答實例=[])]
    sqs = [_sq(1, bad_rubric), _sq(2, _conforming_rubric())]
    issues = check_open_response_rubric_shape(sqs, in_scope=[False, True])
    # sq1 is skipped; sq2 is conforming → no issues
    assert issues == []


def test_shape_check_in_scope_partial() -> None:
    """Only the in-scope subquestion is checked."""
    bad_rubric = [_RubricEntry(code="2", 規準說明="incomplete", 學生作答實例=[])]
    good_rubric = _conforming_rubric()
    sqs = [_sq(1, good_rubric), _sq(2, bad_rubric)]
    # Only first is in scope
    issues = check_open_response_rubric_shape(sqs, in_scope=[True, False])
    assert issues == []


def test_shape_check_missing_fixed_sentence_in_level_2() -> None:
    """[2] 規準說明 without EXTRA_ITEMS_FIXED_SENTENCE → fixed-sentence issue."""
    rubric = _conforming_rubric()
    rubric[0].規準說明 = "完整說明但沒有固定句。"  # no fixed sentence
    sqs = [_sq(1, rubric)]
    issues = check_open_response_rubric_shape(sqs)
    assert len(issues) == 1
    assert "第1題 [2] 規準說明缺少固定句" in issues[0]
    assert EXTRA_ITEMS_FIXED_SENTENCE in issues[0]


def test_shape_check_level_set_wrong_still_reports_count_issues() -> None:
    """Even when the level set is wrong, count issues for existing 2/1/0 are reported."""
    rubric = [
        _RubricEntry(code="3", 規準說明="超完整。", 學生作答實例=["超完整。"]),
        _RubricEntry(code="2", 規準說明=f"完整。{_FIXED}", 學生作答實例=["一", "二"]),  # [2] has 2, should have 1
        _RubricEntry(code="1", 規準說明="部分。", 學生作答實例=["只有一個"]),  # [1] has 1, should have 2
        _RubricEntry(code="0", 規準說明="錯誤。", 學生作答實例=["錯誤。"]),
    ]
    sqs = [_sq(1, rubric)]
    issues = check_open_response_rubric_shape(sqs)
    # Level set issue
    assert any("評分規準級距必須恰為 2 / 1 / 0" in i for i in issues)
    # Count issues for [2] and [1]
    assert any("第1題 [2] 級距需要 1 個學生作答實例（目前 2 個）" in i for i in issues)
    assert any("第1題 [1] 級距需要 2 個學生作答實例（目前 1 個）" in i for i in issues)


def test_shape_check_empty_rubric() -> None:
    """An empty rubric reports the level-set issue."""
    sqs = [_sq(1, [])]
    issues = check_open_response_rubric_shape(sqs)
    assert any("評分規準級距必須恰為 2 / 1 / 0" in i for i in issues)


def test_shape_check_level_2_with_0_examples_and_no_fixed_sentence() -> None:
    """Multiple issues on [2]: count + missing fixed sentence."""
    rubric = [
        _RubricEntry(code="2", 規準說明="完整說明但沒有固定句。", 學生作答實例=[]),
        _RubricEntry(code="1", 規準說明="部分。", 學生作答實例=["一", "二"]),
        _RubricEntry(code="0", 規準說明="錯誤。", 學生作答實例=["錯誤。"]),
    ]
    sqs = [_sq(1, rubric)]
    issues = check_open_response_rubric_shape(sqs)
    assert any("[2] 級距需要 1 個學生作答實例（目前 0 個）" in i for i in issues)
    assert any("第1題 [2] 規準說明缺少固定句" in i for i in issues)


# ---------------------------------------------------------------------------
# Cross-prompt byte-identical tests (issues #866 / #868)
# ---------------------------------------------------------------------------


def test_four_rubric_authoring_prompts_carry_block_byte_identical() -> None:
    """The block in all four rubric-authoring prompts must be byte-identical (task 3.3).

    Extracts OPEN_RESPONSE_RUBRIC_RULE from:
    1. NS 子題產生器 system prompt
    2. NS corrector system prompt
    3. SS 子題產生器 system prompt (issue #868)
    4. SS corrector system prompt (issue #868)
    """
    from src.natural_sciences.context_builder import build_subquestion_system_prompt as ns_subq
    from src.natural_sciences.corrector import _CORRECTION_SYSTEM_PROMPT_CORE as ns_core
    from src.social_studies.context_builder import build_subquestion_system_prompt as ss_subq
    from src.social_studies.corrector import _CORRECTION_SYSTEM_PROMPT_CORE as ss_core

    ns_subq_prompt = ns_subq("第四學習階段")
    ss_subq_prompt = ss_subq("第四學習階段")

    for label, text in [
        ("NS subq", ns_subq_prompt),
        ("NS corrector", ns_core),
        ("SS subq", ss_subq_prompt),
        ("SS corrector", ss_core),
    ]:
        assert OPEN_RESPONSE_RUBRIC_RULE in text, (
            f"{label}: prompt does not contain OPEN_RESPONSE_RUBRIC_RULE"
        )
        # Count occurrences — must appear exactly once
        assert text.count(OPEN_RESPONSE_RUBRIC_RULE) == 1, (
            f"{label}: OPEN_RESPONSE_RUBRIC_RULE appears more than once"
        )


def test_ss_subquestion_system_prompt_contains_block_exactly_once_all_stages() -> None:
    """Task 3.1: for every 學習階段, the SS 子題產生器 system prompt contains the block exactly once.

    Also verifies it no longer says 「使用 0..N 並允許部分給分」 or 「1-2 個學生作答實例」,
    and that the prompt formats cleanly (no leftover unformatted placeholders from .format()).
    """
    from src.social_studies.context_builder import build_subquestion_system_prompt
    from src.social_studies.schema_loader import load_schemas

    schemas = load_schemas()
    # schema["學習階段"] is a plain string (the current stage), not a list.
    stage_val = schemas.get("學習階段")
    stages = [stage_val] if stage_val else ["第四學習階段"]

    for stage in stages:
        prompt = build_subquestion_system_prompt(stage)
        assert OPEN_RESPONSE_RUBRIC_RULE in prompt, (
            f"{stage}: prompt missing OPEN_RESPONSE_RUBRIC_RULE"
        )
        assert prompt.count(OPEN_RESPONSE_RUBRIC_RULE) == 1, (
            f"{stage}: OPEN_RESPONSE_RUBRIC_RULE appears more than once"
        )
        assert "使用 0..N 並允許部分給分" not in prompt, (
            f"{stage}: prompt still contains '使用 0..N 並允許部分給分'"
        )
        assert "1-2 個學生作答實例" not in prompt, (
            f"{stage}: prompt still contains '1-2 個學生作答實例'"
        )


# ---------------------------------------------------------------------------
# Issue #867: Sample guide example must pass shape check
# ---------------------------------------------------------------------------

def test_adding_samples_guide_example_rubric_conforms() -> None:
    """The Constructed response example in docs/ADDING_SAMPLES.md must pass shape check (issue #867).

    Parses the first JSON block containing '"Constructed response"' in the guide and verifies
    its 評分規準 returns no issues from check_open_response_rubric_shape, so the doc
    cannot drift from the rule.
    """
    import json
    import re

    REPO_ROOT = Path(__file__).parent.parent
    text = (REPO_ROOT / "docs" / "ADDING_SAMPLES.md").read_text(encoding="utf-8")

    # Find all ```json ... ``` blocks and pick the one for Constructed response.
    blocks = re.findall(r"```json\n(\{.*?\})\n```", text, re.DOTALL)
    cr_block = next((b for b in blocks if '"Constructed response"' in b), None)
    assert cr_block is not None, (
        "Could not find a Constructed response JSON example block in docs/ADDING_SAMPLES.md"
    )

    data = json.loads(cr_block)
    raw_rubric = data["question"]["subquestions"][0]["評分規準"]

    @dataclasses.dataclass
    class _GEntry:
        code: str
        規準說明: str
        學生作答實例: list[str] = dataclasses.field(default_factory=list)

    @dataclasses.dataclass
    class _GSQ:
        序號: int
        評分規準: list[_GEntry] = dataclasses.field(default_factory=list)

    entries = [
        _GEntry(
            code=e["code"],
            規準說明=e.get("規準說明", ""),
            學生作答實例=e.get("學生作答實例", []),
        )
        for e in raw_rubric
    ]
    subq = _GSQ(序號=1, 評分規準=entries)
    issues = check_open_response_rubric_shape([subq])
    assert issues == [], (
        f"Sample guide Constructed response example fails shape check:\n"
        + "\n".join(f"  - {i}" for i in issues)
    )
