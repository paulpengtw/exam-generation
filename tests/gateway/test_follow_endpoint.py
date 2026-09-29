from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from gateway.app import create_app
from gateway.release_controller import POLICY_SCHEMA, ReleaseController, ReleasePolicyError

_TOKEN = "tok"
_HEADERS = {"X-Gateway-Control-Token": _TOKEN}


def _policy(
    build_id: str = "build-a",
    revision: int = 1,
    *,
    admission: str = "open",
    **overrides,
) -> dict:
    value = {
        "schema": POLICY_SCHEMA,
        "environment": "test",
        "release_revision": revision,
        "released_build_id": build_id,
        "admission": admission,
        "supported_recovery_formats": ["json-v1"],
        "reader_version": "reader-1",
        "artifacts": {
            "current": {
                "build_id": build_id,
                "release_revision": revision,
                "reader_version": "reader-1",
            },
            "prepared_rollback": None,
            "transition": [],
        },
    }
    value.update(overrides)
    return value


def _make_app(
    tmp_path,
    *,
    build_id="build-a",
    admission="open",
    follow_frontend=True,
    token=_TOKEN,
):
    controller = ReleaseController(tmp_path, environment="test")
    controller.initialize(_policy(build_id, admission=admission))
    return create_app(
        backend_url="http://127.0.0.1:1",  # unreachable, never called
        state_dir=tmp_path,
        control_token=token,
        release_controller=controller,
        follow_frontend=follow_frontend,
    )


def test_follow_disabled_returns_404(tmp_path):
    app = _make_app(tmp_path, follow_frontend=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/gateway/release/follow",
            json={"build_id": "x"},
            headers=_HEADERS,
        )
        assert r.status_code == 404
        r2 = client.post("/gateway/release/follow", json={"build_id": "x"})
        assert r2.status_code == 404


def test_follow_wrong_token_403(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/gateway/release/follow",
            json={"build_id": "x"},
            headers={"X-Gateway-Control-Token": "wrong"},
        )
        assert r.status_code == 403


def test_follow_missing_token_403(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post("/gateway/release/follow", json={"build_id": "x"})
        assert r.status_code == 403


def test_follow_same_build_id_idempotent(tmp_path):
    app = _make_app(tmp_path, build_id="build-a")
    state_file = tmp_path / "admission.json"
    before = state_file.read_bytes()
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/gateway/release/follow",
            json={"build_id": "build-a"},
            headers=_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["released_build_id"] == "build-a"
    after = state_file.read_bytes()
    assert before == after


def test_follow_new_build_id_open_admission(tmp_path):
    app = _make_app(tmp_path, build_id="build-a", admission="open")
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/gateway/release/follow",
            json={"build_id": "build-b"},
            headers=_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["released_build_id"] == "build-b"
        assert data["release_revision"] == 2
        assert data["admission"] == "open"
        assert data["artifacts"]["current"]["build_id"] == "build-b"
        assert data["artifacts"]["current"]["release_revision"] == 2
        assert data["artifacts"]["prepared_rollback"]["build_id"] == "build-a"

        # GET /release/policy.json
        pr = client.get("/release/policy.json")
        assert pr.status_code == 200
        policy = pr.json()
        assert policy["released_build_id"] == "build-b"

        # GET /build-meta.json
        bm = client.get("/build-meta.json")
        assert bm.status_code == 200
        meta = bm.json()
        assert meta["build_id"] == "build-b"


def test_follow_new_build_id_paused_admission(tmp_path):
    import gateway.state as gstate

    controller = ReleaseController(tmp_path, environment="test")
    controller.initialize(_policy("build-a", admission="open"))
    # Pause with a specific reason
    gstate.pause(tmp_path, reason="operator paused")

    app = create_app(
        backend_url="http://127.0.0.1:1",
        state_dir=tmp_path,
        control_token=_TOKEN,
        release_controller=controller,
        follow_frontend=True,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/gateway/release/follow",
            json={"build_id": "build-b"},
            headers=_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["admission"] == "paused"
        assert data["released_build_id"] == "build-b"

    # Check that the paused reason is preserved
    state = gstate.read_state(tmp_path)
    assert state.reason == "operator paused"


def test_follow_preserves_paused_reason_none(tmp_path):
    """Paused with reason=None: after follow the reason is still None."""
    import gateway.state as gstate

    controller = ReleaseController(tmp_path, environment="test")
    controller.initialize(_policy("build-a", admission="open"))
    # Pause without a reason
    gstate.pause(tmp_path)

    app = create_app(
        backend_url="http://127.0.0.1:1",
        state_dir=tmp_path,
        control_token=_TOKEN,
        release_controller=controller,
        follow_frontend=True,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/gateway/release/follow",
            json={"build_id": "build-b"},
            headers=_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["admission"] == "paused"
        assert data["released_build_id"] == "build-b"

    state = gstate.read_state(tmp_path)
    assert state.reason is None


def test_follow_preparing_returns_409(tmp_path):
    controller = ReleaseController(tmp_path, environment="test")
    controller.initialize(_policy("build-a", admission="open"))
    # Now prepare a target to set admission to "preparing"
    controller.prepare_target({
        "build_id": "build-b",
        "release_revision": 2,
        "reader_version": "reader-1",
        "supported_recovery_formats": ["json-v1"],
    })

    state_file = tmp_path / "admission.json"
    before = state_file.read_bytes()

    app = create_app(
        backend_url="http://127.0.0.1:1",
        state_dir=tmp_path,
        control_token=_TOKEN,
        release_controller=controller,
        follow_frontend=True,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/gateway/release/follow",
            json={"build_id": "build-c"},
            headers=_HEADERS,
        )
        assert r.status_code == 409
        data = r.json()
        assert data["code"] == "RELEASE_TRANSITION_REJECTED"

    after = state_file.read_bytes()
    assert before == after


def test_follow_bad_request_400(tmp_path):
    app = _make_app(tmp_path, build_id="build-a")
    state_file = tmp_path / "admission.json"
    before = state_file.read_bytes()

    with TestClient(app, raise_server_exceptions=False) as client:
        # missing build_id key
        r = client.post("/gateway/release/follow", json={}, headers=_HEADERS)
        assert r.status_code == 400
        assert r.json()["detail"] == "build_id must be a non-empty string."

        # empty string
        r = client.post(
            "/gateway/release/follow", json={"build_id": ""}, headers=_HEADERS
        )
        assert r.status_code == 400

        # whitespace only
        r = client.post(
            "/gateway/release/follow", json={"build_id": "  "}, headers=_HEADERS
        )
        assert r.status_code == 400

        # integer
        r = client.post(
            "/gateway/release/follow", json={"build_id": 123}, headers=_HEADERS
        )
        assert r.status_code == 400

        # non-JSON body
        r = client.post(
            "/gateway/release/follow",
            content=b"not json",
            headers={**_HEADERS, "Content-Type": "application/json"},
        )
        assert r.status_code == 400

        # JSON array body
        r = client.post(
            "/gateway/release/follow", json=[1, 2, 3], headers=_HEADERS
        )
        assert r.status_code == 400

    after = state_file.read_bytes()
    assert before == after


def test_follow_error_responses_leave_state_unchanged(tmp_path):
    """404/403 leave state unchanged."""
    app = _make_app(tmp_path, build_id="build-a")
    state_file = tmp_path / "admission.json"
    before = state_file.read_bytes()

    with TestClient(app, raise_server_exceptions=False) as client:
        # 403
        r = client.post(
            "/gateway/release/follow", json={"build_id": "build-b"}
        )
        assert r.status_code == 403
        assert state_file.read_bytes() == before

    # 404 (disabled)
    app2 = _make_app(tmp_path, build_id="build-a", follow_frontend=False)
    with TestClient(app2, raise_server_exceptions=False) as client:
        r = client.post(
            "/gateway/release/follow",
            json={"build_id": "build-b"},
            headers=_HEADERS,
        )
        assert r.status_code == 404
        assert state_file.read_bytes() == before


def test_follow_build_controller_unit(tmp_path):
    controller = ReleaseController(tmp_path, environment="test")
    controller.initialize(_policy("build-a", 1))

    # Same build_id is idempotent
    result = controller.follow_build("build-a")
    assert result["released_build_id"] == "build-a"
    assert result["release_revision"] == 1

    # New build_id advances
    result2 = controller.follow_build("build-b")
    assert result2["released_build_id"] == "build-b"
    assert result2["release_revision"] == 2
    assert result2["artifacts"]["current"]["build_id"] == "build-b"
    assert result2["artifacts"]["prepared_rollback"]["build_id"] == "build-a"

    # Preparing blocks
    from copy import deepcopy
    from datetime import UTC, datetime

    p = controller._require_policy()
    prep = deepcopy(p)
    prep["admission"] = "preparing"
    prep["preparation"] = {
        "target": {
            "build_id": "build-c",
            "release_revision": 3,
            "reader_version": "reader-1",
            "supported_recovery_formats": ["json-v1"],
        },
        "prepared_at": datetime.now(UTC).isoformat(),
    }
    controller._write(prep, changed_by="test", reason="prep")
    with pytest.raises(ReleasePolicyError, match="release preparation is in progress"):
        controller.follow_build("build-c")

    # Invalid build_id
    with pytest.raises(ReleasePolicyError):
        controller.follow_build("")
    with pytest.raises(ReleasePolicyError):
        controller.follow_build(123)  # type: ignore


def test_follow_env_wiring(monkeypatch, tmp_path):
    import unittest.mock as mock

    captured = {}

    def mock_create_app(**kwargs):
        captured.update(kwargs)
        from starlette.applications import Starlette

        return Starlette(routes=[])

    def mock_uvicorn_run(app, **kwargs):
        pass

    monkeypatch.setenv("GATEWAY_BACKEND_URL", "http://localhost:9999")
    monkeypatch.setenv("GATEWAY_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("GATEWAY_FOLLOW_FRONTEND", "1")
    monkeypatch.setenv("PORT", "9999")

    with (
        mock.patch("gateway.__main__.create_app", side_effect=mock_create_app),
        mock.patch("uvicorn.run", mock_uvicorn_run),
    ):
        import gateway.__main__ as gm

        gm.main()

    assert captured.get("follow_frontend") is True

    # Test unset -> False
    captured.clear()
    monkeypatch.delenv("GATEWAY_FOLLOW_FRONTEND", raising=False)

    with (
        mock.patch("gateway.__main__.create_app", side_effect=mock_create_app),
        mock.patch("uvicorn.run", mock_uvicorn_run),
    ):
        gm.main()

    assert captured.get("follow_frontend") is False

    # Test "0" -> False
    captured.clear()
    monkeypatch.setenv("GATEWAY_FOLLOW_FRONTEND", "0")

    with (
        mock.patch("gateway.__main__.create_app", side_effect=mock_create_app),
        mock.patch("uvicorn.run", mock_uvicorn_run),
    ):
        gm.main()

    assert captured.get("follow_frontend") is False
