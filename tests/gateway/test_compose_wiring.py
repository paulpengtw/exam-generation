"""Slice 5 test — docker-compose.yml wiring for the gateway service."""

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def compose() -> dict:
    path = Path(__file__).parent.parent.parent / "docker-compose.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_gateway_service_present(compose):
    assert "gateway" in compose["services"], "gateway service must be defined"


def test_gateway_build(compose):
    gw = compose["services"]["gateway"]
    build = gw.get("build", {})
    assert build.get("context") == ".", "gateway build context must be '.'"
    assert build.get("dockerfile") == "Dockerfile.gateway"


def test_gateway_environment(compose):
    gw = compose["services"]["gateway"]
    env = gw.get("environment", {})
    # Accept both dict and list-of-"KEY=VALUE" forms
    if isinstance(env, list):
        env = dict(item.split("=", 1) for item in env)
    assert env.get("GATEWAY_BACKEND_URL") == "http://backend:8000"
    assert env.get("GATEWAY_STATE_DIR") == "/var/lib/examgen-gate"
    # GATEWAY_CONTROL_TOKEN may use shell variable syntax
    assert "GATEWAY_CONTROL_TOKEN" in env
    assert "RELEASE_ENVIRONMENT" in env
    assert "GATEWAY_RELEASED_BUILD_ID" in env
    assert env.get("GATEWAY_SUPPORTED_RECOVERY_FORMATS") == (
        "${SUPPORTED_RECOVERY_FORMATS:-exam-generation.recovery/1}"
    ), (
        f"docker-compose gateway GATEWAY_SUPPORTED_RECOVERY_FORMATS default must be "
        f"exam-generation.recovery/1, got {env.get('GATEWAY_SUPPORTED_RECOVERY_FORMATS')}"
    )


def test_gateway_ports(compose):
    gw = compose["services"]["gateway"]
    ports = gw.get("ports", [])
    assert "8000:8000" in ports, f"gateway must expose 8000:8000, got {ports}"


def test_gateway_volume(compose):
    gw = compose["services"]["gateway"]
    volumes = gw.get("volumes", [])
    assert any("gate-state" in str(v) and "/var/lib/examgen-gate" in str(v) for v in volumes), (
        f"gateway must mount gate-state at /var/lib/examgen-gate, got {volumes}"
    )


def test_gateway_depends_on_backend(compose):
    gw = compose["services"]["gateway"]
    depends = gw.get("depends_on", [])
    if isinstance(depends, dict):
        assert "backend" in depends
    else:
        assert "backend" in depends


def test_backend_loses_ports_mapping(compose):
    backend = compose["services"]["backend"]
    ports = backend.get("ports", [])
    assert not ports, f"backend must not have a ports mapping (bypasses gateway), got {ports}"


def test_backend_has_expose(compose):
    backend = compose["services"]["backend"]
    expose = backend.get("expose", [])
    assert "8000" in [str(e) for e in expose], (
        f"backend must expose 8000 internally, got {expose}"
    )


def test_frontend_backend_host_is_gateway(compose):
    frontend = compose["services"]["frontend"]
    env = frontend.get("environment", {})
    if isinstance(env, list):
        env = dict(item.split("=", 1) for item in env)
    assert env.get("BACKEND_HOST") == "gateway:8000", (
        f"frontend BACKEND_HOST must be gateway:8000, got {env.get('BACKEND_HOST')}"
    )


def test_backend_reads_policy_from_gateway_not_frontend(compose):
    backend = compose["services"]["backend"]
    env = backend.get("environment", {})
    assert env.get("RELEASE_AUTHORITY_URL") == "http://gateway:8000/release/policy.json"
    assert "RELEASE_ENVIRONMENT" in env


def test_frontend_depends_on_gateway(compose):
    frontend = compose["services"]["frontend"]
    depends = frontend.get("depends_on", [])
    if isinstance(depends, dict):
        assert "gateway" in depends
    else:
        assert "gateway" in depends


def test_named_volume_gate_state(compose):
    volumes = compose.get("volumes", {})
    assert "gate-state" in volumes, f"gate-state named volume must be declared, got {volumes}"
