"""Phase 3 math sampler regression tests."""

from __future__ import annotations

import pytest

from src.sampler import _MATH_SUBJECT_TO_PREFIXES, grade_to_learning_stage, sample_params


def test_grade_to_learning_stage():
    assert grade_to_learning_stage(2) == "第一學習階段"
    assert grade_to_learning_stage(4) == "第二學習階段"
    assert grade_to_learning_stage(6) == "第三學習階段"
    assert grade_to_learning_stage(8) == "第四學習階段"
    assert grade_to_learning_stage(11) == "第五學習階段"


def test_sample_params_seeded_deterministic():
    p1 = sample_params(grade=8, subject_filter="代數", seed=42)
    p2 = sample_params(grade=8, subject_filter="代數", seed=42)
    assert [c.編碼 for c in p1.學習內容] == [c.編碼 for c in p2.學習內容]
    assert p1.核心素養 == p2.核心素養


def test_sample_params_algebra_filter_picks_algebra_strand():
    p = sample_params(grade=8, subject_filter="代數", seed=1)
    allowed_prefixes = _MATH_SUBJECT_TO_PREFIXES["代數"]
    for item in p.學習內容:
        assert item.編碼[:1] in allowed_prefixes, (
            f"learning content {item.編碼} doesn't match 代數 prefixes {allowed_prefixes}"
        )


def test_sample_params_core_competency_codes_use_J_stage():
    """Grade 8 → 第四學習階段 → stage code J; all 核心素養 codes start with 數-J-."""
    p = sample_params(grade=8, seed=7)
    assert p.核心素養, "expected at least one core competency sampled"
    for code in p.核心素養:
        assert code.startswith("數-J-"), f"unexpected stage prefix: {code}"


def test_sample_params_content_type_random_excludes_customized():
    """Random pool should never auto-pick 'customized'."""
    seen = {
        sample_params(grade=8, seed=s).題目內容類型 for s in range(50)
    }
    assert "customized" not in seen


def test_sample_params_content_type_override_accepted():
    p = sample_params(grade=8, content_type="customized", seed=0)
    assert p.題目內容類型 == "customized"


def test_sample_params_subject_filter_stored():
    p = sample_params(grade=8, subject_filter="幾何", seed=3)
    assert p.subject_filter == "幾何"


def test_sample_params_sub_question_count_pins_math_to_group_question():
    p = sample_params(grade=8, seed=3, sub_question_count=4)

    assert p.sub_question_count == 4
    assert p.題型種類.value == "題組題"


def test_omitting_sub_question_count_preserves_the_seeded_math_draw_snapshot():
    p = sample_params(grade=8, seed=314159, sub_question_count=None)

    assert p.情境 == ["科學", "數學文字情境"]
    assert p.題型種類.value == "單一題"
    assert p.題型.value == "選擇題"
    assert [item.value for item in p.數學思考] == ["運用", "詮釋評估", "形成"]
    assert [item.編碼 for item in p.學習內容] == ["S-9-9"]
    assert [item.編碼 for item in p.學習表現] == ["a-IV-3", "n-IV-1", "s-IV-4"]
    assert p.核心素養 == ["數-J-A3", "數-J-C3", "數-J-C1"]
    assert p.題目內容類型 == "含圖片"
    assert p.style.value == "text_only"


def test_sample_params_unknown_grade_raises():
    with pytest.raises(ValueError):
        sample_params(grade=99, seed=0)


def test_sample_params_difficulty_defaults_to_medium():
    from src.common.difficulty import Difficulty
    from src.sampler import sample_params

    p = sample_params(grade=8, seed=0)
    assert p.difficulty is Difficulty.medium


def test_sample_params_difficulty_passthrough_string():
    from src.common.difficulty import Difficulty
    from src.sampler import sample_params

    for v in ("easy", "medium", "hard"):
        p = sample_params(grade=8, seed=0, difficulty=v)
        assert p.difficulty is Difficulty(v)


def test_sample_params_difficulty_passthrough_enum():
    from src.common.difficulty import Difficulty
    from src.sampler import sample_params

    p = sample_params(grade=8, seed=0, difficulty=Difficulty.hard)
    assert p.difficulty is Difficulty.hard


def test_sample_params_difficulty_is_not_randomized():
    from src.common.difficulty import Difficulty
    from src.sampler import sample_params

    # Every seed must yield the caller-supplied difficulty verbatim.
    for seed in range(50):
        assert sample_params(grade=8, seed=seed).difficulty is Difficulty.medium
        assert sample_params(grade=8, seed=seed, difficulty="hard").difficulty is Difficulty.hard
