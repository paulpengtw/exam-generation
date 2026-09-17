"""Tests for build-admission gate (issue #771)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.models import User
from server.rate_limit import limiter
from tests.server.generate_test_utils import complete_math_query_params


# Override the conftest bypass so route tests run the real check_build_admission.
import pytest as _pytest  # noqa: F401 (used in the fixture override below)


@_pytest.fixture(autouse=True)
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


def _make_client(policy_path: Path) -> TestClient:
    app = create_app()
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


def test_zero_dispatch_on_426(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.generate.service as svc

    calls: list[int] = []

    async def _fake_stream(*a: object, **kw: object):  # type: ignore[override]
        calls.append(1)
        return
        yield  # pragma: no cover

    monkeypatch.setattr(svc, "generate_question_stream", _fake_stream)

    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-abc"))
    client = _make_client(fixture)
    params = complete_math_query_params()

    resp = client.post("/api/generate", json={**params, "stream_version": 2})
    assert resp.status_code == 426
    assert calls == [], "generate_question_stream must not be called on 426"


def test_check_build_admission_unit(tmp_path: Path) -> None:
    from server.generate.release_authority import (
        FileAuthoritySource,
        check_build_admission,
    )

    fixture = tmp_path / "policy.json"
    _write_fixture(fixture, _make_fixture("build-unit"))
    source = FileAuthoritySource(fixture)

    assert check_build_admission("build-unit", source) is None

    resp = check_build_admission("wrong", source)
    assert resp is not None
    assert resp.status_code == 426

    resp2 = check_build_admission(None, source)
    assert resp2 is not None
    assert resp2.status_code == 426

    missing_source = FileAuthoritySource(tmp_path / "missing.json")
    resp3 = check_build_admission("build-unit", missing_source)
    assert resp3 is not None
    assert resp3.status_code == 503
