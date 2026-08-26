"""Request-to-subject-sampler coverage for figure-kind pins and the kill-switch."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.generate.models import GenerateParams, SubQuestionConfig
from server.generate.service import _decode_subquestion_configs
from server.generate.subjects import (
    _ns_coerce_overrides,
    _ns_do_sample_params,
    _ss_coerce_overrides,
    _ss_do_sample_params,
)


def test_server_subquestion_config_declares_figure_kind_pin() -> None:
    config = SubQuestionConfig(figure_kind="地圖", content_type="含圖片")

    assert config.figure_kind == "地圖"
    assert config.content_type == "含圖片"


def test_ss_request_forwards_pin_and_duplicate_kill_switch_to_sampled_params() -> None:
    params = GenerateParams(
        subject="social_studies",
        content_type="含圖片",
        sub_question_count=3,
        subquestion_configs=json.dumps(
            [{"content_type": "含圖片", "figure_kind": "地圖"}, {}, {}],
            ensure_ascii=False,
        ),
        allow_duplicate_figure_kinds=True,
    )

    sampled = _ss_do_sample_params(
        params,
        _ss_coerce_overrides(params, None),
        seed=1,
        subquestion_configs_decoded=_decode_subquestion_configs(
            params.subquestion_configs
        ),
    )

    assert sampled.allow_duplicate_figure_kinds is True
    assert sampled.subquestion_configs[0].figure_kind == "地圖"


def test_ns_request_forwards_pin_and_duplicate_kill_switch_to_sampled_params() -> None:
    params = GenerateParams(
        subject="natural_sciences",
        content_type="含圖片",
        sub_question_count=3,
        subquestion_configs=json.dumps(
            [{"content_type": "含圖片", "figure_kind": "電路圖"}, {}, {}],
            ensure_ascii=False,
        ),
        allow_duplicate_figure_kinds=True,
    )

    sampled = _ns_do_sample_params(
        params,
        _ns_coerce_overrides(params, None),
        seed=1,
        subquestion_configs_decoded=_decode_subquestion_configs(
            params.subquestion_configs
        ),
    )

    assert sampled.allow_duplicate_figure_kinds is True
    assert sampled.subquestion_configs[0].figure_kind == "電路圖"
