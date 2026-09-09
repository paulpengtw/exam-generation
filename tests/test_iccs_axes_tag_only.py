from __future__ import annotations

import pytest


def test_social_studies_loader_exposes_iccs_axis_enums_and_content_types() -> None:
    from src.social_studies.schema_loader import build_enums_by_category, load_schemas

    schemas = load_schemas()
    enums = build_enums_by_category(schemas)

    assert [member.value for member in enums["認知歷程"]] == [
        "Knowing–Defining and Describing",
        "Knowing–Illustrating with examples",
        "Reasoning and Applying–Interpret information",
        "Reasoning and Applying–Relate or Integrate",
    ]
    assert [member.value for member in enums["內容領域"]] == [
        "Civic Institutions and Systems",
        "Civic Principles",
        "Civic Participation",
        "Civic Roles and Identities",
    ]

    content_type_values = [member.value for member in enums["題目內容類型"]]
    assert "混合" in content_type_values
    assert "數位閱讀" in content_type_values


def test_relate_or_integrate_instruction_covers_cross_book_and_cross_domain() -> None:
    from src.social_studies.schema_loader import build_instructions, load_schemas

    instruction = build_instructions(load_schemas())["認知歷程"][
        "Reasoning and Applying–Relate or Integrate"
    ]

    assert "跨冊別" in instruction
    assert "跨領域" in instruction


def test_sampler_assigns_domain_and_cognitive_process_per_resolved_slot() -> None:
    from src.social_studies.sampler import sample_params
    from src.social_studies.schema_loader import build_enums_by_category, load_schemas

    enums = build_enums_by_category(load_schemas())
    domains = {member.value for member in enums["內容領域"]}
    processes = {member.value for member in enums["認知歷程"]}

    first = sample_params(seed=489, sub_question_count=4)
    second = sample_params(seed=489, sub_question_count=4)

    assert first.內容領域.value in domains
    assert [cfg.認知歷程 for cfg in first.subquestion_configs] == [
        cfg.認知歷程 for cfg in second.subquestion_configs
    ]
    assert all(cfg.認知歷程 in processes for cfg in first.subquestion_configs)
    assert [cfg.question_type for cfg in first.subquestion_configs] == [
        cfg.question_type for cfg in second.subquestion_configs
    ]


def test_sampler_reaches_all_cognitive_process_buckets_across_seeded_batch() -> None:
    from src.social_studies.sampler import sample_params

    observed = {
        sample_params(seed=seed, sub_question_count=3).subquestion_configs[0].認知歷程
        for seed in range(100)
    }

    assert observed == {
        "Knowing–Defining and Describing",
        "Knowing–Illustrating with examples",
        "Reasoning and Applying–Interpret information",
        "Reasoning and Applying–Relate or Integrate",
    }


def test_text_and_subquestion_prompts_name_sampled_iccs_assignments(tmp_path) -> None:
    from src.social_studies.context_builder import (
        build_subquestion_user_prompt,
        build_text_user_prompt,
    )
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=489, sub_question_count=3, content_type="純文字")
    text_prompt, _, _draws = build_text_user_prompt(
        params,
        tmp_path,
        disable_reference_fewshot=True,
    )
    sub_prompt, _, _draws = build_subquestion_user_prompt(
        核心問題="測試核心問題",
        文本="測試文本",
        取材來源=["測試來源"],
        sq_plan={"序號": 1, "題型": "選擇題", "出題概念": "測試"},
        params=params,
        few_shot_dir=tmp_path,
        cfg=params.subquestion_configs[0],
        disable_reference_fewshot=True,
    )

    assert f"- **內容領域**：{params.內容領域.value}" in text_prompt
    assert f"- **認知歷程**：{params.subquestion_configs[0].認知歷程}" in sub_prompt


def test_stubbed_subquestion_output_is_forced_to_sampled_cognitive_process(tmp_path) -> None:
    from pathlib import Path

    from src.config import Config
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=489, sub_question_count=3, content_type="純文字")
    assigned = params.subquestion_configs[0].認知歷程
    disagreeing = next(
        value
        for value in (
            "Knowing–Defining and Describing",
            "Knowing–Illustrating with examples",
            "Reasoning and Applying–Interpret information",
            "Reasoning and Applying–Relate or Integrate",
        )
        if value != assigned
    )

    class _TextClient:
        def get_observer(self):
            return None

        def generate_json(self, *_args, **_kwargs):
            return {
                "核心問題": "測試核心問題",
                "文本": "測試文本",
                "取材來源": ["測試來源"],
                "subquestions": [
                    {"序號": i, "題型": "選擇題", "出題概念": f"概念{i}"}
                    for i in range(1, 4)
                ],
            }

    class _DisagreeingSubClient:
        def set_observer(self, _observer) -> None:
            pass

        def generate_json(self, *_args, **_kwargs):
            return {
                "序號": 1,
                "科目": ["地理"],
                "題型": "選擇題",
                "題目": "測試題目",
                "答案": "A",
                "答案解析": "解析",
                "出題概念": "測試概念",
                "認知歷程": disagreeing,
            }

    question = generate_one(
        config=Config(
            data_dir=Path("data"),
            output_dir=tmp_path,
            subgen_max_concurrency=3,
        ),
        client=_TextClient(),
        params=params,
        question_id="iccs_axes_test",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=lambda: _DisagreeingSubClient(),
    )

    assert question.subquestions[0].認知歷程 == assigned


def test_assembly_derives_domain_and_ordered_unique_cognitive_processes() -> None:
    from src.social_studies.cli import _derive_iccs_axes
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import ExamQuestion, SubQuestion

    params = sample_params(seed=489, sub_question_count=3)
    first = "Knowing–Defining and Describing"
    second = "Reasoning and Applying–Interpret information"
    question = ExamQuestion(
        id="iccs-assembly",
        情境=["個人"],
        題型種類="題組題",
        題型="選擇題",
        subquestions=[
            SubQuestion(題型="選擇題", 題目="一", 認知歷程=first),
            SubQuestion(題型="選擇題", 題目="二", 認知歷程=second),
            SubQuestion(題型="選擇題", 題目="三", 認知歷程=first),
            SubQuestion(題型="選擇題", 題目="四"),
        ],
    )

    _derive_iccs_axes(question, params)

    assert question.內容領域 == params.內容領域.value
    assert question.認知歷程 == [first, second]
    dumped = question.model_dump()
    assert dumped["內容領域"] == params.內容領域.value
    assert dumped["認知歷程"] == [first, second]
    assert dumped["subquestions"][0]["認知歷程"] == first


def test_legacy_social_studies_record_without_iccs_fields_deserializes() -> None:
    from src.social_studies.schemas import ExamQuestion

    question = ExamQuestion.model_validate(
        {
            "id": "legacy",
            "核心問題": "舊核心問題",
            "文本": "舊文本",
            "取材來源": [],
            "subquestions": [],
            "情境": ["個人"],
            "題型種類": "題組題",
            "題型": "選擇題",
            "閱讀歷程": ["擷取訊息"],
            "文本形式": "連續文本—說明文",
        }
    )

    assert question.內容領域 is None
    assert question.認知歷程 is None


def test_subquestion_cognitive_process_rejects_unknown_values() -> None:
    from src.social_studies.schemas import SubQuestion

    with pytest.raises(ValueError, match="認知歷程"):
        SubQuestion(
            題型="選擇題",
            題目="測試題目",
            認知歷程="not-an-iccs-process",
        )


def test_sampler_does_not_assign_cognitive_processes_to_unconfigured_slots() -> None:
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=489)
    assert params.subquestion_configs == []
    assert params.認知歷程_pool == []


def test_social_corrector_preserves_iccs_tags_during_rebuild() -> None:
    from src.social_studies.corrector import (
        FROZEN_SUBQUESTION_FIELDS,
        FROZEN_TOP_LEVEL_FIELDS,
        _ss_rebuild_subquestion,
    )
    from src.social_studies.schemas import SubQuestion

    assigned = "Reasoning and Applying–Relate or Integrate"
    original = SubQuestion(
        序號=1,
        題型="選擇題",
        題目="原題目",
        認知歷程=assigned,
    )
    rebuilt = _ss_rebuild_subquestion(
        {
            "序號": 1,
            "題型": "選擇題",
            "題目": "修正後題目",
            "認知歷程": "Knowing–Defining and Describing",
        },
        original,
        0,
    )

    assert rebuilt is not None
    assert rebuilt.認知歷程 == assigned
    assert "內容領域" in FROZEN_TOP_LEVEL_FIELDS
    assert "認知歷程" in FROZEN_TOP_LEVEL_FIELDS
    assert "認知歷程" in FROZEN_SUBQUESTION_FIELDS
