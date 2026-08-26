"""Social studies sampler difficulty passthrough and general sampler behaviour."""

from __future__ import annotations

from src.common.difficulty import Difficulty
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import QuestionType


def test_ss_sampler_difficulty_defaults_to_medium():
    p = sample_params(seed=1)
    assert p.difficulty is Difficulty.medium


def test_ss_sampler_difficulty_string_passthrough():
    for v in ("easy", "medium", "hard"):
        assert sample_params(seed=1, difficulty=v).difficulty is Difficulty(v)


def test_ss_sampler_difficulty_enum_passthrough():
    p = sample_params(seed=1, difficulty=Difficulty.hard)
    assert p.difficulty is Difficulty.hard


def test_ss_sampler_difficulty_not_randomized():
    for seed in range(50):
        assert sample_params(seed=seed).difficulty is Difficulty.medium


# ── Ported from deleted test_social_studies_sampler_assignments.py ─────────────

def test_empty_q_type_list_falls_back_to_full_pool() -> None:
    # q_type=[] means "not pinned" — the sampler draws from the full enum,
    # not an empty pool that would crash rng.sample/rng.randint.
    p = sample_params(seed=1, q_type=[])
    assert set(t.value for t in p.題型) <= {t.value for t in QuestionType}
    assert len(p.題型) >= 1


def test_default_call_is_deterministic_with_same_seed() -> None:
    # Two calls with the same seed must produce identical draws.
    p1 = sample_params(seed=42)
    p2 = sample_params(seed=42)
    assert [t.value for t in p1.題型] == [t.value for t in p2.題型]
    assert p1.學習內容_pool == p2.學習內容_pool


def test_pinning_social_content_type_does_not_shift_other_seeded_draws() -> None:
    baseline = sample_params(seed=0, sub_question_count=3, target_surface="數位")
    pinned = sample_params(
        seed=0,
        sub_question_count=3,
        target_surface="數位",
        content_type="純文字",
    )

    assert pinned.題目內容類型 == "純文字"
    baseline_payload = baseline.model_dump()
    pinned_payload = pinned.model_dump()
    baseline_payload.pop("題目內容類型")
    pinned_payload.pop("題目內容類型")
    assert pinned_payload == baseline_payload


def test_social_slot_redraw_uses_its_indexed_question_type_stream() -> None:
    baseline = sample_params(seed=0, sub_question_count=3, target_surface="數位")
    redrawn = sample_params(
        seed=0,
        sub_question_count=3,
        target_surface="數位",
        redraws={"subquestion_configs[2].question_type": 1},
    )
    replay = sample_params(
        seed=0,
        sub_question_count=3,
        target_surface="數位",
        redraws={"subquestion_configs[2].question_type": 1},
    )

    assert redrawn.subquestion_configs[2].question_type != (
        baseline.subquestion_configs[2].question_type
    )
    assert redrawn.subquestion_configs[:2] == baseline.subquestion_configs[:2]
    baseline_payload = baseline.model_dump()
    redrawn_payload = redrawn.model_dump()
    baseline_payload.pop("題型")
    redrawn_payload.pop("題型")
    baseline_payload["subquestion_configs"][2]["question_type"] = None
    redrawn_payload["subquestion_configs"][2]["question_type"] = None
    assert redrawn_payload == baseline_payload
    assert replay.model_dump_json() == redrawn.model_dump_json()


def test_pinning_one_social_slot_does_not_shift_other_slot_draws() -> None:
    baseline = sample_params(seed=0, sub_question_count=3, target_surface="數位")
    pinned = sample_params(
        seed=0,
        sub_question_count=3,
        target_surface="數位",
        subquestion_configs=[{"question_type": "選擇題"}, {}, {}],
    )

    assert pinned.subquestion_configs[0].question_type == QuestionType("選擇題")
    assert pinned.subquestion_configs[1:] == baseline.subquestion_configs[1:]


def test_subquestion_config_pin_wins_sampler_draw() -> None:
    # A question_type pinned in subquestion_configs slot 0 is preserved verbatim;
    # blank slots are filled from the full QuestionType pool.
    from src.social_studies.schemas import SubQuestionConfig

    cfg = SubQuestionConfig(question_type=QuestionType("開放式建構反應題"))
    p = sample_params(
        seed=1,
        sub_question_count=3,
        subquestion_configs=[cfg, {}, {}],
    )
    assert p.subquestion_configs[0].question_type.value == "開放式建構反應題"
    fill_types = {c.question_type.value for c in p.subquestion_configs[1:]}
    assert fill_types <= {t.value for t in QuestionType}
