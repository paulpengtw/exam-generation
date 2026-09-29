"""Tests for the 50-follow-release.sh nginx entrypoint hook (issue #922)."""
from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[2] / "web" / "docker-entrypoint.d" / "50-follow-release.sh"
DOCKERFILE_PATH = Path(__file__).parents[2] / "web" / "Dockerfile"

# ---------------------------------------------------------------------------
# Static checks (no network, no shell)
# ---------------------------------------------------------------------------

def test_script_exists_and_is_executable():
    assert SCRIPT_PATH.exists(), f"Script not found: {SCRIPT_PATH}"
    assert os.access(SCRIPT_PATH, os.X_OK), "Script must have executable bit"

def test_script_starts_with_shebang():
    content = SCRIPT_PATH.read_text()
    assert content.startswith("#!/bin/sh"), "Script must start with #!/bin/sh"

def test_script_has_no_set_e():
    content = SCRIPT_PATH.read_text()
    assert "set -e" not in content, "Script must not contain 'set -e'"

def test_script_last_nonblank_line_is_exit_0():
    lines = SCRIPT_PATH.read_text().splitlines()
    nonblank = [line.strip() for line in lines if line.strip()]
    assert nonblank[-1] == "exit 0", (
        f"Last non-blank line must be 'exit 0', got: {nonblank[-1]!r}"
    )

def test_script_no_nonzero_exit():
    content = SCRIPT_PATH.read_text()
    import re
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        m = re.match(r"^exit\s+([1-9]\d*)$", stripped)
        if m:
            pytest.fail(f"Script contains non-zero exit: {line!r}")

def test_dockerfile_final_stage_has_copy_and_chmod():
    content = DOCKERFILE_PATH.read_text()
    lines = content.splitlines()
    last_from_idx = -1
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("FROM "):
            last_from_idx = i
    assert last_from_idx >= 0
    final_stage = "\n".join(lines[last_from_idx:])
    assert "50-follow-release.sh /docker-entrypoint.d/50-follow-release.sh" in final_stage
    assert "chmod +x /docker-entrypoint.d/50-follow-release.sh" in final_stage

# ---------------------------------------------------------------------------
# Shell execution tests (require curl)
# ---------------------------------------------------------------------------

CURL_AVAILABLE = shutil.which("curl") is not None
skip_no_curl = pytest.mark.skipif(not CURL_AVAILABLE, reason="curl not on PATH")


class _StubHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Records requests and returns a configured status code."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.server._requests.append({
            "method": "POST",
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
        })
        status = self.server._next_status
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{}')

    def log_message(self, *args):
        pass  # suppress server logs


def _start_stub_server(status_code: int = 200) -> tuple[http.server.HTTPServer, int, list]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _StubHTTPHandler)
    server._requests = []
    server._next_status = status_code
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port, server._requests


def _run_script(
    env_overrides: dict,
    meta_content: str | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run the hook script with controlled env."""
    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
    }

    with tempfile.TemporaryDirectory() as td:
        if meta_content is not None:
            meta_path = os.path.join(td, "build-meta.json")
            Path(meta_path).write_text(meta_content)
            env_overrides = dict(env_overrides, FOLLOW_RELEASE_BUILD_META=meta_path)

        env = {**base_env, **env_overrides}
        result = subprocess.run(
            ["sh", str(SCRIPT_PATH)],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    return result


def _valid_meta(build_id: str = "abc123") -> str:
    return json.dumps({
        "schema": "exam-generation.build-meta/1",
        "build_id": build_id,
        "release_revision": 1,
    })


@skip_no_curl
def test_hook_inert_when_no_env_vars():
    """Exit 0, one log line, zero requests when neither var is set."""
    result = _run_script({})
    assert result.returncode == 0
    assert result.stderr.strip() != ""  # one log line


@skip_no_curl
def test_hook_inert_when_only_url_set():
    """Exit 0, zero requests when only GATEWAY_FOLLOW_URL is set."""
    server, port, requests = _start_stub_server(200)
    url = f"http://127.0.0.1:{port}/gateway/release/follow"
    result = _run_script({"GATEWAY_FOLLOW_URL": url})
    server.shutdown()
    assert result.returncode == 0
    assert len(requests) == 0


@skip_no_curl
def test_hook_inert_when_only_token_set():
    """Exit 0, zero requests when only GATEWAY_CONTROL_TOKEN is set."""
    result = _run_script({"GATEWAY_CONTROL_TOKEN": "secret"})
    assert result.returncode == 0


@skip_no_curl
def test_hook_inert_when_meta_missing():
    """Exit 0, zero requests when the meta file does not exist."""
    server, port, requests = _start_stub_server(200)
    url = f"http://127.0.0.1:{port}/gateway/release/follow"
    result = _run_script({
        "GATEWAY_FOLLOW_URL": url,
        "GATEWAY_CONTROL_TOKEN": "secret",
        "FOLLOW_RELEASE_BUILD_META": "/tmp/nonexistent-build-meta-99999.json",
    })
    server.shutdown()
    assert result.returncode == 0
    assert len(requests) == 0


@skip_no_curl
def test_hook_inert_when_meta_has_no_build_id():
    """Exit 0, zero requests when the meta file has no build_id."""
    server, port, requests = _start_stub_server(200)
    url = f"http://127.0.0.1:{port}/gateway/release/follow"
    result = _run_script(
        {
            "GATEWAY_FOLLOW_URL": url,
            "GATEWAY_CONTROL_TOKEN": "secret",
        },
        meta_content='{"schema": "exam-generation.build-meta/1"}',
    )
    server.shutdown()
    assert result.returncode == 0
    assert len(requests) == 0


@skip_no_curl
def test_hook_posts_correct_build_id(tmp_path):
    """Stub 200: one POST with correct build_id, exit 0, token not in stdout/stderr."""
    server, port, requests = _start_stub_server(200)
    url = f"http://127.0.0.1:{port}/gateway/release/follow"
    token = "super-secret-token"

    result = _run_script(
        {"GATEWAY_FOLLOW_URL": url, "GATEWAY_CONTROL_TOKEN": token},
        meta_content=_valid_meta("mybuild-abc123"),
        timeout=15,
    )

    server.shutdown()
    assert result.returncode == 0
    assert len(requests) == 1
    assert requests[0]["path"] == "/gateway/release/follow"
    body = json.loads(requests[0]["body"])
    assert body["build_id"] == "mybuild-abc123"
    headers_lower = {k.lower(): v for k, v in requests[0]["headers"].items()}
    assert headers_lower.get("x-gateway-control-token") == token
    # Token must NOT appear in stdout or stderr
    assert token not in result.stdout
    assert token not in result.stderr


@skip_no_curl
def test_hook_stub_403_one_request_exit_0():
    """Stub 403: exactly one request, exit 0 (4xx does not retry)."""
    server, port, requests = _start_stub_server(403)
    url = f"http://127.0.0.1:{port}/gateway/release/follow"

    result = _run_script(
        {"GATEWAY_FOLLOW_URL": url, "GATEWAY_CONTROL_TOKEN": "tok"},
        meta_content=_valid_meta("build-x"),
        timeout=15,
    )

    server.shutdown()
    assert result.returncode == 0
    assert len(requests) == 1


@skip_no_curl
def test_hook_stub_503_three_requests_exit_0():
    """Stub 503: 3 requests (retries), exit 0."""
    server, port, requests = _start_stub_server(503)
    url = f"http://127.0.0.1:{port}/gateway/release/follow"

    result = _run_script(
        {"GATEWAY_FOLLOW_URL": url, "GATEWAY_CONTROL_TOKEN": "tok"},
        meta_content=_valid_meta("build-y"),
        timeout=35,
    )

    server.shutdown()
    assert result.returncode == 0
    assert len(requests) == 3


@skip_no_curl
def test_hook_unreachable_url_exit_0_within_30s():
    """Unreachable URL: exit 0 within 30 seconds."""
    result = _run_script(
        {
            "GATEWAY_FOLLOW_URL": "http://127.0.0.1:1/gateway/release/follow",
            "GATEWAY_CONTROL_TOKEN": "tok",
        },
        meta_content=_valid_meta("build-z"),
        timeout=35,
    )
    assert result.returncode == 0
