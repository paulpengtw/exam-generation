"""Regression tests for the social-studies retirement of the two legacy axes."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_exam_question_loads_arbitrary_legacy_axis_strings() -> None:
    from src.social_studies.schemas import ExamQuestion

    question = ExamQuestion.model_validate(
        {
            "id": "legacy-axis-values",
            "情境": ["個人"],
            "題型種類": "題組題",
            "題型": "選擇題",
            "閱讀歷程": ["legacy process value", "another retired value"],
            "文本形式": "legacy text-form value",
        }
    )

    assert question.閱讀歷程 == ["legacy process value", "another retired value"]
    assert question.文本形式 == "legacy text-form value"
    assert question.認知歷程 is None


def test_new_exam_question_has_empty_legacy_fields() -> None:
    from src.social_studies.schemas import ExamQuestion

    question = ExamQuestion(
        id="new-iccs-record",
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        認知歷程=["Knowing–Defining and Describing"],
    )

    assert question.閱讀歷程 == []
    assert question.文本形式 is None
    dumped = question.model_dump(exclude_none=True)
    assert not dumped["閱讀歷程"]
    assert "文本形式" not in dumped


def test_social_schema_and_enum_map_contain_only_live_categories() -> None:
    from src.common.subject_spec import SOCIAL_STUDIES
    from src.social_studies.schema_loader import build_enums_by_category, load_schemas

    expected = (
        "情境",
        "題型種類",
        "題型",
        "認知歷程",
        "內容領域",
        "科目",
        "題目內容類型",
        "難度",
    )
    schemas = load_schemas()
    enums = build_enums_by_category(schemas)

    assert SOCIAL_STUDIES.schema_categories == expected
    assert tuple(schemas) == ("學習階段", "grades", *expected)
    assert tuple(enums) == expected
    assert "閱讀歷程" not in schemas
    assert "文本形式" not in schemas


def test_natural_sciences_schema_categories_remain_unchanged() -> None:
    from src.common.subject_spec import NATURAL_SCIENCES
    from src.natural_sciences.schema_loader import load_schemas

    expected = (
        "情境",
        "情境子類別",
        "題型種類",
        "題型",
        "科學能力",
        "題目內容類型",
    )

    assert NATURAL_SCIENCES.schema_categories == expected
    assert tuple(load_schemas()) == ("學習階段", "grades", *expected)


def test_sampler_no_longer_draws_or_exposes_retired_axes() -> None:
    from src.social_studies import sampler

    params = sampler.sample_params(seed=498, content_type="graphs/charts/tables")

    assert not hasattr(params, "閱讀歷程")
    assert not hasattr(params, "文本形式")
    assert params.題目內容類型 == "graphs/charts/tables"
    assert "閱讀歷程" not in inspect.getsource(sampler)
    assert "文本形式" not in inspect.getsource(sampler)


def test_generation_path_does_not_populate_retired_axes(tmp_path: Path) -> None:
    from src.config import Config
    from src.social_studies import context_builder, sampler
    from src.social_studies.cli import generate_one
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=498, sub_question_count=3, content_type="純文字")

    class TextClient:
        def get_observer(self):
            return None

        def generate_json(self, *_args, **_kwargs):
            return {
                "核心問題": "測試核心問題",
                "文本": "測試文本",
                "取材來源": ["測試來源"],
                "subquestions": [
                    {"序號": index, "題型": "選擇題", "出題概念": f"概念{index}"}
                    for index in range(1, 4)
                ],
            }

    class SubClient:
        def set_observer(self, _observer) -> None:
            pass

        def generate_json(self, *_args, **_kwargs):
            return {
                "序號": 1,
                "題型": "選擇題",
                "題目": "測試題目",
                "答案": "A",
                "答案解析": "解析",
                "出題概念": "測試概念",
            }

    question = generate_one(
        config=Config(data_dir=Path("data"), output_dir=tmp_path, subgen_max_concurrency=3),
        client=TextClient(),
        params=params,
        question_id="retire-old-axes",
        skip_verify=True,
        disable_reference_fewshot=True,
        sub_client_factory=SubClient,
    )

    assert not question.閱讀歷程
    assert question.文本形式 is None
    payload = json.loads(question.model_dump_json(exclude_none=True))
    assert not payload["閱讀歷程"]
    assert "文本形式" not in payload
    payload_text = json.dumps(payload, ensure_ascii=False)
    assert "legacy process value" not in payload_text
    assert "legacy text-form value" not in payload_text

    prompt_sources = inspect.getsource(sampler) + inspect.getsource(context_builder)
    assert "閱讀歷程" not in prompt_sources
    assert "文本形式" not in prompt_sources
    assert "PISA閱讀" not in prompt_sources


def test_retired_axis_keys_are_unknown_per_question_parameters() -> None:
    from server.generate.models import GenerateParams

    with pytest.raises(ValidationError, match="unknown parameter"):
        GenerateParams(
            subject="social_studies",
            per_question_params=json.dumps(
                [{"閱讀歷程": ["legacy input"]}], ensure_ascii=False
            ),
        )

    with pytest.raises(ValidationError, match="unknown parameter"):
        GenerateParams(
            subject="social_studies",
            per_question_params=json.dumps(
                [{"文本形式": "legacy input"}], ensure_ascii=False
            ),
        )
