"""Tests for build-admission gate (issue #771)."""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import httpx
import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.generate.release_authority import (
    FileAuthoritySource,
    HttpAuthoritySource,
    build_authority_source,
    check_build_admission,
)
from server.models import User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params


@pytest.fixture(autouse=True)
def _bypass_build_admission():  # type: ignore[override]
    """Re-enable the real check for this module's route tests."""
    yield


def _make_fixture(build_id: str = "build-abc", admission: str = "open") -> dict:
    return {
        "schema": "exam-generation.release-policy/1",
        "environment": "production",
        "release_revision": 1,
        "released_build_id": build_id,
        "admission": admission,
        "supported_recovery_formats": [],
    }


def _write_fixture(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_client(
    policy_path: Path | None = None,
    *,
    authority_source: object | None = None,
) -> TestClient:
    if authority_source is None and policy_path is not None:
        authority_source = FileAuthoritySource(policy_path)
    app = create_app(release_authority_source=authority_source)
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="u@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(
        api_key="x", gemini_api_key="x", release_authority_path=policy_path
    )
    limiter.reset()
    return TestClient(app, raise_server_exceptions=False)


def test_get_missing_header_returns_426(tmp_path: Path) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc"))
    client = _make_client(fixture)
    params = complete_math_query_params()
    resp = client.get("/api/generate", params=params)
    assert resp.status_code == 426
    body = resp.json()
    assert body["code"] == "CLIENT_UPDATE_REQUIRED"
    assert body["required_build_id"] == "build-abc"


def test_get_outdated_header_returns_426(tmp_path: Path) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc"))
    client = _make_client(fixture)
    params = complete_math_query_params()
    resp = client.get(
        "/api/generate",
        params=params,
        headers={"X-Frontend-Build-ID": "old-build-xyz"},
    )
    assert resp.status_code == 426
    assert resp.json()["code"] == "CLIENT_UPDATE_REQUIRED"


def test_get_current_build_passes(tmp_path: Path) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc"))
    client = _make_client(fixture)
    params = complete_math_query_params()
    resp = client.get(
        "/api/generate",
        params=params,
        headers={"X-Frontend-Build-ID": "build-abc"},
    )
    assert resp.status_code not in (426, 503)


def test_post_missing_header_returns_426(tmp_path: Path) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc"))
    client = _make_client(fixture)
    params = complete_math_query_params()
    resp = client.post("/api/generate", json={**params, "stream_version": 2})
    assert resp.status_code == 426
    assert resp.json()["code"] == "CLIENT_UPDATE_REQUIRED"


def test_post_current_build_passes(tmp_path: Path) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc"))
    client = _make_client(fixture)
    params = complete_math_query_params()
    resp = client.post(
        "/api/generate",
        json={**params, "stream_version": 2},
        headers={"X-Frontend-Build-ID": "build-abc"},
    )
    assert resp.status_code not in (426, 503)


@pytest.mark.parametrize("method", ["get", "post"])
def test_current_build_still_requires_supported_stream_version(
    tmp_path: Path, method: str
) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc"))
    client = _make_client(fixture)
    params = complete_math_query_params()
    params.pop("stream_version", None)

    response = (
        client.get(
            "/api/generate",
            params=params,
            headers={"X-Frontend-Build-ID": "build-abc"},
        )
        if method == "get"
        else client.post(
            "/api/generate",
            json=params,
            headers={"X-Frontend-Build-ID": "build-abc"},
        )
    )

    assert response.status_code == 426
    assert response.json()["code"] == "CLIENT_UPDATE_REQUIRED"
    assert response.json()["supported_stream_versions"] == [2]


def test_current_build_does_not_bypass_incomplete_predraw_validation(tmp_path: Path) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc"))
    client = _make_client(fixture)

    response = client.post(
        "/api/generate",
        json={"subject": "math", "stream_version": 2},
        headers={"X-Frontend-Build-ID": "build-abc"},
    )

    assert response.status_code == 422
    assert "unresolved" in response.text


def test_authority_policy_is_read_again_for_each_request(tmp_path: Path) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-a"))
    client = _make_client(fixture)
    incomplete = {"subject": "math", "stream_version": 2}

    first = client.post(
        "/api/generate",
        json=incomplete,
        headers={"X-Frontend-Build-ID": "build-a"},
    )
    assert first.status_code == 422

    _write_fixture(fixture, _make_fixture("build-b"))
    second = client.post(
        "/api/generate",
        json=incomplete,
        headers={"X-Frontend-Build-ID": "build-a"},
    )
    assert second.status_code == 426
    assert second.json()["required_build_id"] == "build-b"


def test_authority_unavailable_returns_503(tmp_path: Path) -> None:
    nonexistent = tmp_path / "no-such-file.json"
    client = _make_client(nonexistent)
    params = complete_math_query_params()
    resp = client.get(
        "/api/generate",
        params=params,
        headers={"X-Frontend-Build-ID": "build-abc"},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "AUTHORITY_UNAVAILABLE"
    assert resp.headers.get("retry-after") == "30"


def test_paused_returns_503(tmp_path: Path) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc", admission="paused"))
    client = _make_client(fixture)
    params = complete_math_query_params()
    resp = client.get(
        "/api/generate",
        params=params,
        headers={"X-Frontend-Build-ID": "build-abc"},
    )
    assert resp.status_code == 503
    assert resp.json()["code"] == "SERVICE_PAUSED"
    assert resp.headers.get("retry-after") == "60"


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("admission", ["426", "503"])
def test_zero_dispatch_and_provider_calls_before_build_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    admission: str,
) -> None:
    import server.generate.routes as routes

    dispatch_calls: list[int] = []
    provider_calls: list[int] = []

    async def _fake_stream(*a: object, **kw: object):  # type: ignore[override]
        dispatch_calls.append(1)
        return
        yield  # pragma: no cover

    def _fake_provider(*a: object, **kw: object) -> None:
        provider_calls.append(1)

    monkeypatch.setattr(routes, "generate_question_stream", _fake_stream)
    monkeypatch.setattr(routes, "_check_provider_key_for_model", _fake_provider)

    fixture = tmp_path / "policy.json"
    _write_fixture(
        fixture,
        _make_fixture("build-abc", admission="paused" if admission == "503" else "open"),
    )
    client = _make_client(fixture)
    params = complete_math_query_params()

    headers = {"X-Frontend-Build-ID": "build-abc"}
    if admission == "426":
        headers = {}
    resp = (
        client.get("/api/generate", params=params, headers=headers)
        if method == "get"
        else client.post("/api/generate", json=params, headers=headers)
    )
    assert resp.status_code == int(admission)
    assert dispatch_calls == []
    assert provider_calls == []


def test_url_source_timeout_returns_retryable_503(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    source = HttpAuthoritySource(
        "https://frontend.example/release/policy.json",
        transport=httpx.MockTransport(handler),
    )
    client = _make_client(authority_source=source)
    response = client.post(
        "/api/generate",
        json={"subject": "math", "stream_version": 2},
        headers={"X-Frontend-Build-ID": "build-abc"},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "AUTHORITY_UNAVAILABLE"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"error": "down"}),
        httpx.Response(200, content=b"not-json"),
    ],
)
def test_url_source_non_2xx_or_invalid_json_returns_503(
    response: httpx.Response,
) -> None:
    source = HttpAuthoritySource(
        "https://frontend.example/release/policy.json",
        transport=httpx.MockTransport(lambda request: response),
    )
    result = asyncio.run(check_build_admission("build-abc", source))
    assert result is not None
    assert result.status_code == 503
    assert json.loads(result.body)["code"] == "AUTHORITY_UNAVAILABLE"


def test_authority_source_selection_prefers_url_then_path(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    assert isinstance(
        build_authority_source("https://frontend.example/release/policy.json", path),
        HttpAuthoritySource,
    )
    assert isinstance(build_authority_source("", path), FileAuthoritySource)
    assert build_authority_source("", None) is None


def test_excluded_endpoints_do_not_require_build_header(tmp_path: Path) -> None:
    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc", admission="paused"))
    client = _make_client(fixture)

    resolve_response = client.post(
        "/api/generate/resolve",
        json={
            "subject": "math",
            "seed": 41,
            "grade": 8,
            "context": ["個人"],
            "set_type": "單一題",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "learning_content": ["A-7-7"],
            "learning_performance": ["s-IV-12"],
            "core_competency": ["數-J-A2"],
        },
    )
    assert resolve_response.status_code == 200
    assert client.get("/api/generate/preview", params={"subject": "math"}).status_code == 422
    assert client.get("/api/schemas", params={"subject": "math"}).status_code == 200

    unauthenticated = TestClient(create_app(release_authority_source=None))
    assert unauthenticated.get("/api/history").status_code == 401
    assert unauthenticated.post(
        "/api/generation-records/not-a-record/modifications",
        json={"annotations": []},
    ).status_code == 401


def test_check_build_admission_unit(tmp_path: Path) -> None:
    from server.generate.release_authority import (
        FileAuthoritySource,
        check_build_admission,
    )

    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-unit"))
    source = FileAuthoritySource(fixture)

    assert asyncio.run(check_build_admission("build-unit", source)) is None

    resp = asyncio.run(check_build_admission("wrong", source))
    assert resp is not None
    assert resp.status_code == 426

    resp2 = asyncio.run(check_build_admission(None, source))
    assert resp2 is not None
    assert resp2.status_code == 426

    missing_source = FileAuthoritySource(tmp_path / "missing.json")
    resp3 = asyncio.run(check_build_admission("build-unit", missing_source))
    assert resp3 is not None
    assert resp3.status_code == 503
