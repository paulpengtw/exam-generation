"""Request-boundary tests for social-studies ICCS pins and surface flags."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from server.generate.models import GenerateParams

_DOMAINS = [
    "Civic Institutions and Systems",
    "Civic Principles",
    "Civic Participation",
    "Civic Roles and Identities",
]


@pytest.mark.parametrize("content_domain", ["not-an-iccs-domain", "公民"])
def test_social_request_rejects_unknown_content_domain(content_domain: str) -> None:
    with pytest.raises(ValidationError, match="content_domain"):
        GenerateParams(subject="social_studies", content_domain=content_domain)


@pytest.mark.parametrize("target_surface", ["電腦", "hybrid"])
def test_social_request_rejects_unknown_target_surface(target_surface: str) -> None:
    with pytest.raises(ValidationError, match="target_surface"):
        GenerateParams(subject="social_studies", target_surface=target_surface)


def test_social_request_accepts_valid_pins_and_keeps_absent_surface_unresolved() -> None:
    for content_domain in _DOMAINS:
        params = GenerateParams(
            subject="social_studies",
            content_domain=content_domain,
            target_surface="數位",
        )
        assert params.content_domain == content_domain
        assert params.target_surface == "數位"

    assert GenerateParams(subject="social_studies").target_surface is None


@pytest.mark.parametrize("subject", ["math", "natural_sciences"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content_domain", _DOMAINS[0]),
        ("target_surface", "數位"),
    ],
)
def test_non_social_subjects_reject_iccs_pin_fields(
    subject: str,
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError, match=field):
        GenerateParams(subject=subject, **{field: value})


def test_invalid_cognitive_process_is_accepted_by_tolerant_json_channel() -> None:
    params = GenerateParams(
        subject="social_studies",
        subquestion_configs=json.dumps(
            [{"cognitive_process": "not-an-iccs-process"}], ensure_ascii=False
        ),
    )

    assert params.subquestion_configs is not None


def test_paper_surface_rejects_synthetic_digital_only_question_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.social_studies import schema_loader

    original_load_schemas = schema_loader.load_schemas
    schemas = original_load_schemas()
    schemas["題型"] = [
        *schemas["題型"],
        {"value": "拖放題", "instruction": "僅限數位卷面"},
    ]
    monkeypatch.setattr(schema_loader, "load_schemas", lambda curriculum_dir=None: schemas)

    with pytest.raises(ValidationError, match="target_surface"):
        GenerateParams(
            subject="social_studies",
            subquestion_configs=json.dumps([{"question_type": "拖放題"}]),
        )

    with pytest.raises(ValidationError, match="target_surface"):
        GenerateParams(
            subject="social_studies",
            target_surface="紙本",
            subquestion_configs=json.dumps([{"question_type": "拖放題"}]),
        )

    with pytest.raises(ValidationError, match="target_surface"):
        GenerateParams(
            subject="social_studies",
            q_type=["拖放題"],
        )


def test_digital_surface_accepts_synthetic_digital_only_question_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.social_studies import schema_loader

    original_load_schemas = schema_loader.load_schemas
    schemas = original_load_schemas()
    schemas["題型"] = [
        *schemas["題型"],
        {"value": "拖放題", "instruction": "僅限數位卷面"},
    ]
    monkeypatch.setattr(schema_loader, "load_schemas", lambda curriculum_dir=None: schemas)

    params = GenerateParams(
        subject="social_studies",
        target_surface="數位",
        subquestion_configs=json.dumps([{"question_type": "拖放題"}]),
    )

    assert params.target_surface == "數位"


def test_social_sampler_defaults_absent_surface_to_paper() -> None:
    from src.social_studies.sampler import sample_params

    assert sample_params(seed=1).target_surface == "紙本"


def test_target_surface_reaches_sampled_params() -> None:
    from server.generate.subjects import _ss_coerce_overrides, _ss_do_sample_params

    request = GenerateParams(subject="social_studies", target_surface="數位")
    sampled = _ss_do_sample_params(
        request,
        _ss_coerce_overrides(request, object()),
        seed=3,
        subquestion_configs_decoded=None,
    )

    assert sampled.target_surface == "數位"


def test_target_surface_round_trips_into_social_response_metadata() -> None:
    from server.generate.subjects import _ss_patch_metadata
    from src.social_studies.schemas import ExamQuestion

    question = ExamQuestion.model_validate(
        {
            "id": "surface-round-trip",
            "情境": ["個人"],
            "題型種類": "題組題",
            "題型": "選擇題",
            "閱讀歷程": ["擷取訊息"],
            "文本形式": "連續文本—說明文",
        }
    )

    patched = _ss_patch_metadata(question, "balanced", "數位")

    assert patched.metadata is not None
    assert patched.metadata.surface_used == "數位"


def test_target_surface_reaches_direct_social_cli_metadata() -> None:
    from src.social_studies.cli import _parse_text_shell
    from src.social_studies.sampler import sample_params

    question = _parse_text_shell(
        {},
        "surface-cli-round-trip",
        sample_params(seed=3, target_surface="數位"),
        "test-model",
    )

    assert question.metadata is not None
    assert question.metadata.surface_used == "數位"


def test_social_schemas_report_approved_digital_only_question_types() -> None:
    pytest.importorskip("fastapi", reason="requires [web] extras: uv sync --extra web")
    from fastapi.testclient import TestClient

    from server.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/schemas?subject=social_studies")

    assert response.status_code == 200
    assert response.json()["digital_only_question_types"] == ["拖放題", "滑桿題"]


@pytest.mark.parametrize("question_type", ["拖放題", "滑桿題"])
def test_paper_surface_rejects_approved_digital_only_question_type(
    question_type: str,
) -> None:
    with pytest.raises(ValidationError, match="target_surface"):
        GenerateParams(
            subject="social_studies",
            target_surface="紙本",
            subquestion_configs=json.dumps([{"question_type": question_type}]),
        )


def test_social_schemas_report_injected_digital_only_question_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("fastapi", reason="requires [web] extras: uv sync --extra web")
    from fastapi.testclient import TestClient

    from server.app import create_app
    from server.generate import subjects

    schemas = subjects.ss_load_schemas()
    schemas["題型"] = [
        *schemas["題型"],
        {"value": "拖放題", "instruction": "僅限數位卷面"},
    ]
    monkeypatch.setattr(subjects, "ss_load_schemas", lambda *args: schemas)

    with TestClient(create_app()) as client:
        response = client.get("/api/schemas?subject=social_studies")

    assert response.status_code == 200
    assert response.json()["digital_only_question_types"] == ["拖放題", "滑桿題"]
