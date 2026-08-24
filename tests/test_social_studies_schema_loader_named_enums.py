from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

_PUBLIC_ENUM_NAMES = {
    "情境": "QuestionContext",
    "題型種類": "QuestionSetType",
    "題型": "QuestionType",
    "科目": "QuestionSubject",
}


def _assert_str_enum(enum_type: type) -> None:
    assert issubclass(enum_type, str)
    assert issubclass(enum_type, Enum)


def test_named_accessor_builds_enums_for_all_social_studies_categories() -> None:
    from src.common.subject_spec import SOCIAL_STUDIES
    from src.social_studies import schema_loader
    from src.social_studies.schema_loader import load_schemas

    assert hasattr(schema_loader, "build_enums_by_category")
    schemas = load_schemas()
    enums = schema_loader.build_enums_by_category(schemas)

    assert isinstance(enums, Mapping)
    assert set(_PUBLIC_ENUM_NAMES) <= set(enums)
    assert set(SOCIAL_STUDIES.schema_categories) <= set(enums)

    for category in SOCIAL_STUDIES.schema_categories:
        enum_type = enums[category]
        _assert_str_enum(enum_type)
        assert [member.value for member in enum_type] == [
            entry["value"] for entry in schemas[category]
        ]

    assert [member.value for member in enums["情境"]] == ["個人", "公共", "職業", "教育"]
    assert [member.value for member in enums["科目"]] == [
        "歷史",
        "地理",
        "公民與社會",
        "跨科",
    ]


def test_named_accessor_builds_enum_for_a_new_schema_category() -> None:
    from src.social_studies import schema_loader
    from src.social_studies.schema_loader import load_schemas

    assert hasattr(schema_loader, "build_enums_by_category")
    schemas = load_schemas()
    schemas["假想類別"] = [
        {"value": "甲", "instruction": ""},
        {"value": "乙", "instruction": ""},
    ]

    enums = schema_loader.build_enums_by_category(schemas)

    _assert_str_enum(enums["假想類別"])
    assert [member.value for member in enums["假想類別"]] == ["甲", "乙"]


def test_social_studies_schema_exports_preserve_current_enum_members() -> None:
    from src.social_studies import schemas as public_schemas

    expected_values = {
        "QuestionContext": ["個人", "公共", "職業", "教育"],
        "QuestionSetType": ["題組題"],
        "QuestionType": ["選擇題", "開放式建構反應題", "拖放題", "滑桿題"],
        "QuestionSubject": ["歷史", "地理", "公民與社會", "跨科"],
    }

    for enum_name, values in expected_values.items():
        enum_type = getattr(public_schemas, enum_name)
        _assert_str_enum(enum_type)
        assert [member.value for member in enum_type] == values
