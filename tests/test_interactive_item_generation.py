"""Contract tests for digital interactive social-studies subquestions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def _drag_spec(*, exact_match: bool = False) -> dict:
    return {
        "draggables": [
            {"id": "d1", "label": "甲"},
            {"id": "d2", "label": "乙"},
        ],
        "targets": [
            {"id": "t1", "label": "左類", "capacity": 1},
            {"id": "t2", "label": "右類", "capacity": 1},
        ],
        "correct_mapping": {"d1": "t1", "d2": "t2"},
        "exact_match": exact_match,
    }


def test_drag_drop_subquestion_accepts_and_serializes_interaction_spec() -> None:
    from src.social_studies.schemas import DragDropSpec, SubQuestion

    question = SubQuestion(
        題型="拖放題",
        題目="請配對。",
        interaction=_drag_spec(),
    )

    assert isinstance(question.interaction, DragDropSpec)
    assert question.interaction.shuffle_draggables is True
    assert question.model_dump(mode="json")["interaction"]["correct_mapping"] == {
        "d1": "t1",
        "d2": "t2",
    }


def test_exam_question_response_serializes_nested_interaction() -> None:
    from src.social_studies.schemas import ExamQuestion

    question = ExamQuestion(
        id="serialized-interactive",
        情境=["教育"],
        題型種類="題組題",
        題型="拖放題",
        subquestions=[
            {
                "題型": "拖放題",
                "題目": "配對",
                "interaction": _drag_spec(),
            }
        ],
    )

    payload = question.model_dump(mode="json", exclude_none=True)

    assert payload["subquestions"][0]["interaction"]["targets"][0]["capacity"] == 1


@pytest.mark.parametrize(
    ("question_type", "interaction"),
    [
        ("拖放題", None),
        (
            "拖放題",
            {
                "min": 0,
                "max": 10,
                "step": 1,
                "correct_value": 5,
                "tolerance": 0,
            },
        ),
        ("滑桿題", _drag_spec()),
        ("選擇題", _drag_spec()),
    ],
)
def test_interaction_kind_is_required_and_matches_question_type(
    question_type: str,
    interaction: dict | None,
) -> None:
    from src.social_studies.schemas import SubQuestion

    with pytest.raises(ValidationError, match="interaction"):
        SubQuestion(
            題型=question_type,
            題目="測試題目",
            interaction=interaction,
        )


def test_drag_drop_partial_credit_uses_mapping_count_as_max_score() -> None:
    from src.social_studies.interaction_scoring import score_interaction
    from src.social_studies.schemas import DragDropSpec

    score, max_score = score_interaction(
        DragDropSpec.model_validate(_drag_spec()),
        {"placements": {"d1": "t1", "d2": "t1"}},
    )

    assert (score, max_score) == (1, 2)


def test_drag_drop_exact_match_is_all_or_zero() -> None:
    from src.social_studies.interaction_scoring import score_interaction
    from src.social_studies.schemas import DragDropSpec

    spec = DragDropSpec.model_validate(_drag_spec(exact_match=True))

    assert score_interaction(spec, {"d1": "t1", "d2": "t2"}) == (2, 2)
    assert score_interaction(spec, {"d1": "t1", "d2": "t1"}) == (0, 2)
    assert score_interaction(
        spec,
        {"d1": "t1", "d2": "t2", "extra": "t1"},
    ) == (0, 2)


def test_slider_scores_one_only_inside_inclusive_tolerance() -> None:
    from src.social_studies.interaction_scoring import score_interaction
    from src.social_studies.schemas import SliderSpec

    spec = SliderSpec(
        min=0,
        max=10,
        step=0.5,
        correct_value=5,
        tolerance=0.5,
    )

    assert score_interaction(spec, {"value": 5.5}) == (1, 1)
    assert score_interaction(spec, 4.49) == (0, 1)


def test_schema_loader_reports_approved_interactive_types() -> None:
    from src.social_studies.schema_loader import digital_only_question_types

    assert digital_only_question_types() == ["拖放題", "滑桿題"]


def test_digital_sampler_keeps_selection_dominant_and_draws_interactive_types() -> None:
    from collections import Counter

    from src.social_studies.sampler import sample_params

    counts: Counter[str] = Counter()
    for seed in range(300):
        params = sample_params(
            seed=seed,
            target_surface="數位",
            sub_question_count=7,
        )
        counts.update(cfg.question_type.value for cfg in params.subquestion_configs)

    total = sum(counts.values())
    assert 0.76 <= counts["選擇題"] / total <= 0.93
    assert counts["開放式建構反應題"] > 0
    assert counts["拖放題"] > 0
    assert counts["滑桿題"] > 0


@pytest.mark.parametrize("target_surface", [None, "紙本"])
def test_paper_or_absent_surface_never_draws_interactive_types(
    target_surface: str | None,
) -> None:
    from src.social_studies.sampler import sample_params

    for seed in range(100):
        params = sample_params(
            seed=seed,
            target_surface=target_surface,
            sub_question_count=7,
        )
        assert all(
            cfg.question_type.value not in {"拖放題", "滑桿題"}
            for cfg in params.subquestion_configs
        )


def test_digital_interactive_question_type_pin_is_preserved() -> None:
    from src.social_studies.sampler import sample_params

    params = sample_params(
        seed=21,
        target_surface="數位",
        sub_question_count=4,
        subquestion_configs=[{"question_type": "拖放題"}, {}, {}, {}],
    )

    assert params.subquestion_configs[0].question_type.value == "拖放題"


def test_interactive_subquestion_prompts_define_drag_and_distractor_contract(tmp_path) -> None:
    from src.social_studies.context_builder import build_subquestion_user_prompt
    from src.social_studies.sampler import sample_params

    params = sample_params(
        seed=4,
        target_surface="數位",
        subquestion_configs=[{"question_type": "拖放題"}],
    )
    prompt, _ = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["測試來源"],
        sq_plan={"序號": 1, "題型": "拖放題", "出題概念": "配對"},
        params=params,
        few_shot_dir=tmp_path,
        cfg=params.subquestion_configs[0],
        disable_reference_fewshot=True,
    )

    assert '"draggables"' in prompt
    assert '"targets"' in prompt
    assert '"correct_mapping"' in prompt
    assert '"exact_match"' in prompt
    assert '"shuffle_draggables"' in prompt
    assert "d1->t2" in prompt
    assert "interaction" in prompt and "答案" in prompt


def test_interactive_subquestion_prompts_define_slider_and_wrong_zone_contract(tmp_path) -> None:
    from src.social_studies.context_builder import build_subquestion_user_prompt
    from src.social_studies.sampler import sample_params

    params = sample_params(
        seed=4,
        target_surface="數位",
        subquestion_configs=[{"question_type": "滑桿題"}],
    )
    prompt, _ = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["測試來源"],
        sq_plan={"序號": 1, "題型": "滑桿題", "出題概念": "估值"},
        params=params,
        few_shot_dir=tmp_path,
        cfg=params.subquestion_configs[0],
        disable_reference_fewshot=True,
    )

    for field in ("min", "max", "step", "unit", "correct_value", "tolerance"):
        assert f'"{field}"' in prompt
    assert "below_range" in prompt
    assert "far_off" in prompt


def test_parser_keeps_valid_drag_drop_interaction() -> None:
    from src.social_studies.cli import _parse_subquestion
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import DragDropSpec

    params = sample_params(
        seed=4,
        target_surface="數位",
        subquestion_configs=[{"question_type": "拖放題"}],
    )
    question = _parse_subquestion(
        {"序號": 1, "題型": "拖放題", "題目": "配對", "interaction": _drag_spec()},
        "interactive",
        params,
        1,
    )

    assert question is not None
    assert isinstance(question.interaction, DragDropSpec)


def test_parser_retries_when_noninteractive_question_contains_interaction() -> None:
    from src.social_studies.cli import _parse_subquestion
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=4)

    question = _parse_subquestion(
        {"序號": 1, "題型": "選擇題", "題目": "選擇", "interaction": _drag_spec()},
        "interactive",
        params,
        1,
    )

    assert question is None


def test_corrector_restores_original_interaction_spec_verbatim() -> None:
    from src.social_studies.corrector import _ss_rebuild_subquestion
    from src.social_studies.schemas import SubQuestion

    original = SubQuestion(
        題型="拖放題",
        題目="原始互動題",
        interaction=_drag_spec(),
    )
    candidate = {
        "題目": "修正後互動題",
        "答案": "修正後答案",
        "interaction": {
            **_drag_spec(),
            "correct_mapping": {"d1": "t2", "d2": "t1"},
        },
    }

    rebuilt = _ss_rebuild_subquestion(candidate, original, 0)

    assert rebuilt is not None
    assert rebuilt.interaction == original.interaction
    assert rebuilt.題目 == "修正後互動題"


def test_scoped_modification_merge_ignores_interaction_paths() -> None:
    pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")
    from server.generate.modification_service import _merge_scoped

    base = {"subquestions": [{"題目": "舊題目", "interaction": _drag_spec()}]}
    candidate = {
        "subquestions": [
            {
                "題目": "新題目",
                "interaction": {
                    **_drag_spec(),
                    "correct_mapping": {"d1": "t2", "d2": "t1"},
                },
            }
        ]
    }

    merged = _merge_scoped(
        base,
        candidate,
        {"subquestions[0].題目", "subquestions[0].interaction.correct_mapping"},
    )

    assert merged["subquestions"][0]["題目"] == "新題目"
    assert merged["subquestions"][0]["interaction"] == base["subquestions"][0]["interaction"]
