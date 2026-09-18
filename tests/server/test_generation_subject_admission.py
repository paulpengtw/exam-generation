"""Generation-time 科目/code validation reads the shared admission lookup.

Exercises ``_validate_curriculum_subject_pairs`` directly with synthetic
loaders whose rows carry ``admitted_by`` — no prefix logic anywhere here.
"""

from __future__ import annotations

import types

import pytest

from server.generate.subjects import _validate_curriculum_subject_pairs


def _content_loader(rows: list[dict]) -> callable:
    def _load() -> dict:
        return {"學習內容": rows}

    return _load


def _performance_loader(rows: list[dict]) -> callable:
    def _load() -> dict:
        return {"學習表現": rows}

    return _load


def _counting_loader(data: dict) -> callable:
    calls: list[int] = []

    def _load() -> dict:
        calls.append(1)
        return data

    _load.calls = calls  # type: ignore[attr-defined]
    return _load


def test_admitting_subject_passes_for_request_and_subquestion_codes() -> None:
    params = types.SimpleNamespace(
        subject_filter=["公民與社會"],
        learning_content=["公Bj-Ⅳ-1"],
        learning_performance=["公1a-Ⅳ-1"],
    )
    load_content = _content_loader(
        [{"value": "公Bj-Ⅳ-1", "admitted_by": {"科目": ["公民與社會", "跨科"]}}]
    )
    load_performance = _performance_loader(
        [{"value": "公1a-Ⅳ-1", "admitted_by": {"科目": ["公民與社會", "跨科"]}}]
    )

    _validate_curriculum_subject_pairs(
        params,
        load_content=load_content,
        load_performance=load_performance,
        subquestion_configs=[
            {"learning_content": ["公Bj-Ⅳ-1"], "learning_performance": ["公1a-Ⅳ-1"]}
        ],
    )


def test_non_admitting_subject_rejects_learning_content_code() -> None:
    params = types.SimpleNamespace(
        subject_filter=["地理"],
        learning_content=["公Bj-Ⅳ-1"],
        learning_performance=None,
    )
    load_content = _content_loader(
        [{"value": "公Bj-Ⅳ-1", "admitted_by": {"科目": ["公民與社會", "跨科"]}}]
    )
    load_performance = _performance_loader([])

    with pytest.raises(ValueError, match="does not admit learning_content code"):
        _validate_curriculum_subject_pairs(
            params, load_content=load_content, load_performance=load_performance
        )


def test_non_admitting_subject_rejects_learning_performance_code() -> None:
    params = types.SimpleNamespace(
        subject_filter=["地理"],
        learning_content=None,
        learning_performance=["公1a-Ⅳ-1"],
    )
    load_content = _content_loader([])
    load_performance = _performance_loader(
        [{"value": "公1a-Ⅳ-1", "admitted_by": {"科目": ["公民與社會", "跨科"]}}]
    )

    with pytest.raises(ValueError, match="does not admit learning_performance code"):
        _validate_curriculum_subject_pairs(
            params, load_content=load_content, load_performance=load_performance
        )


def test_unknown_code_with_no_tagged_row_is_rejected() -> None:
    params = types.SimpleNamespace(
        subject_filter=["公民與社會"],
        learning_content=["不存在-Ⅳ-1"],
        learning_performance=None,
    )
    load_content = _content_loader(
        [{"value": "公Bj-Ⅳ-1", "admitted_by": {"科目": ["公民與社會"]}}]
    )
    load_performance = _performance_loader([])

    with pytest.raises(ValueError, match="does not admit learning_content code"):
        _validate_curriculum_subject_pairs(
            params, load_content=load_content, load_performance=load_performance
        )


def test_code_tagged_at_two_stages_is_accepted_for_either_subject() -> None:
    load_content = _content_loader(
        [
            {"value": "共用碼-1", "admitted_by": {"科目": ["公民與社會"]}},
            {"value": "共用碼-1", "admitted_by": {"科目": ["地理"]}},
        ]
    )
    load_performance = _performance_loader([])

    _validate_curriculum_subject_pairs(
        types.SimpleNamespace(
            subject_filter=["公民與社會"],
            learning_content=["共用碼-1"],
            learning_performance=None,
        ),
        load_content=load_content,
        load_performance=load_performance,
    )
    _validate_curriculum_subject_pairs(
        types.SimpleNamespace(
            subject_filter=["地理"],
            learning_content=["共用碼-1"],
            learning_performance=None,
        ),
        load_content=load_content,
        load_performance=load_performance,
    )


def test_multi_valued_subject_filter_passes_when_any_subject_admits() -> None:
    params = types.SimpleNamespace(
        subject_filter=["地理", "公民與社會"],
        learning_content=["公Bj-Ⅳ-1"],
        learning_performance=None,
    )
    load_content = _content_loader(
        [{"value": "公Bj-Ⅳ-1", "admitted_by": {"科目": ["公民與社會"]}}]
    )
    load_performance = _performance_loader([])

    _validate_curriculum_subject_pairs(
        params, load_content=load_content, load_performance=load_performance
    )


@pytest.mark.parametrize("subject_filter", [None, []])
def test_empty_or_none_subject_filter_returns_without_loading(subject_filter) -> None:
    params = types.SimpleNamespace(
        subject_filter=subject_filter,
        learning_content=["anything"],
        learning_performance=["anything"],
    )
    load_content = _counting_loader({"學習內容": []})
    load_performance = _counting_loader({"學習表現": []})

    _validate_curriculum_subject_pairs(
        params, load_content=load_content, load_performance=load_performance
    )

    assert load_content.calls == []  # type: ignore[attr-defined]
    assert load_performance.calls == []  # type: ignore[attr-defined]


def test_real_social_studies_data_rejects_and_accepts_by_subject() -> None:
    from src.social_studies.curriculum_loader import (
        load_learning_content as load_ss_learning_content,
    )
    from src.social_studies.curriculum_loader import (
        load_learning_performance as load_ss_learning_performance,
    )

    with pytest.raises(ValueError, match="does not admit learning_content code"):
        _validate_curriculum_subject_pairs(
            types.SimpleNamespace(
                subject_filter=["地理"],
                learning_content=["公Bj-Ⅳ-1"],
                learning_performance=None,
            ),
            load_content=load_ss_learning_content,
            load_performance=load_ss_learning_performance,
        )

    _validate_curriculum_subject_pairs(
        types.SimpleNamespace(
            subject_filter=["公民與社會"],
            learning_content=["公Bj-Ⅳ-1"],
            learning_performance=None,
        ),
        load_content=load_ss_learning_content,
        load_performance=load_ss_learning_performance,
    )
