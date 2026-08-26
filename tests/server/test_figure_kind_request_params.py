"""Request-to-subject-sampler coverage for figure-kind pins and the kill-switch."""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.generate.models import SubQuestionConfig
from src.common.resolver import resolve
from src.natural_sciences.cli import _ns_params_from_resolved
from src.social_studies.cli import _ss_params_from_resolved


def test_server_subquestion_config_declares_figure_kind_pin() -> None:
    config = SubQuestionConfig(figure_kind="地圖", content_type="含圖片")

    assert config.figure_kind == "地圖"
    assert config.content_type == "含圖片"


def test_ss_request_forwards_pin_and_duplicate_kill_switch_to_sampled_params() -> None:
    result = resolve(
        {
            "subject": "social_studies",
            "seed": 1,
            "content_type": "含圖片",
            "sub_question_count": 3,
            "subquestion_configs": [
                {"content_type": "含圖片", "figure_kind": "地圖"}, {}, {}
            ],
            "allow_duplicate_figure_kinds": True,
        }
    )
    sampled = _ss_params_from_resolved(result.payload)

    assert sampled.allow_duplicate_figure_kinds is True
    assert sampled.subquestion_configs[0].figure_kind == "地圖"


def test_ns_request_forwards_pin_and_duplicate_kill_switch_to_sampled_params() -> None:
    result = resolve(
        {
            "subject": "natural_sciences",
            "seed": 1,
            "context": ["Personal"],
            "sub_context": "Maintenance of health",
            "content_type": "含圖片",
            "sub_question_count": 3,
            "subquestion_configs": [
                {"content_type": "含圖片", "figure_kind": "電路圖"}, {}, {}
            ],
            "allow_duplicate_figure_kinds": True,
        }
    )
    sampled = _ns_params_from_resolved(result.payload)

    assert sampled.allow_duplicate_figure_kinds is True
    assert sampled.subquestion_configs[0].figure_kind == "電路圖"
